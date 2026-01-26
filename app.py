import os
import json
import secrets
import io
import base64
import sys # 新增：用于CLI命令行操作
# --- 新增依赖 ---
import pyotp
import qrcode
import redis # 新增：用于连接Redis实现防火墙
import requests # 新增：用于查询 IP 地理位置
# ----------------
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from celery import Celery
from celery.signals import worker_ready
import logging
from datetime import timedelta

# --- App Configuration ---
app = Flask(__name__)

# --- Redis 连接 (用于防火墙) ---
# 使用 docker-compose 中定义的服务名 'redis'
redis_conn_url = os.environ.get('REDIS_URL', 'redis://redis:6379/0')
try:
    # decode_responses=True 让我们直接获取字符串而不是 bytes
    redis_client = redis.from_url(redis_conn_url, decode_responses=True)
except Exception as e:
    print(f"Warning: Redis connection failed: {e}")
    redis_client = None

# 防火墙配置
MAX_RETRIES = 3          # 允许连续错误次数
BAN_TIME = 86400         # 封禁时间 (秒) -> 24小时

# --- 会话过期设置 ---
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=3650)
CONFIG_FILE = 'config.json'
MFA_FILE = 'mfa_secret.json'

# --- ✨ 新增：动态 IP 白名单机制 ---
TRUSTED_WHITELIST_IPS = []

def load_whitelist():
    """从 config.json 加载白名单"""
    global TRUSTED_WHITELIST_IPS
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                TRUSTED_WHITELIST_IPS = config.get('whitelist_ips', [])
        except Exception: pass

# 启动时加载白名单
load_whitelist()

# --- ✨ 新增：IP 地理位置缓存与查询 ---
IP_GEO_CACHE = {}

def fetch_geo_from_ip(ip_address):
    """查询 IP 归属地 (精确到省份/州)"""
    try:
        # 跳过内网 IP
        if ip_address.startswith('192.168.') or ip_address.startswith('10.') or ip_address == '127.0.0.1':
            return None
        if ip_address in IP_GEO_CACHE:
            return IP_GEO_CACHE[ip_address]
        
        with requests.Session() as s:
            url = f"http://ip-api.com/json/{ip_address}?lang=zh-CN&fields=status,lat,lon,country,regionName"
            r = s.get(url, timeout=3)
            if r.status_code == 200:
                data = r.json()
                if data.get('status') == 'success':
                    result = (data['lat'], data['lon'], data['country'], data.get('regionName', '未知'))
                    IP_GEO_CACHE[ip_address] = result
                    return result
    except Exception as e:
        pass
    return None

# --- 辅助函数：获取真实IP ---
def get_real_ip():
    """获取真实用户IP，兼容 Caddy/Nginx 反向代理"""
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0]
    return request.remote_addr

# --- 辅助函数：处理登录失败 (按设备指纹封禁) ---
def handle_login_failure(client_id):
    """
    增加错误计数，如果达到阈值则封禁该设备指纹(或IP)
    返回: (是否被封禁, 错误提示信息)
    """
    if not redis_client:
        return False, "❌ 系统错误: Redis未连接，防火墙未生效。"

    attempt_key = f"login_attempts:{client_id}"
    ban_key = f"blacklist:{client_id}"

    try:
        # 原子递增错误计数
        attempts = redis_client.incr(attempt_key)
        
        # 如果是第一次错误，设置计数器窗口期（例如5分钟内输错3次才算）
        if attempts == 1:
            redis_client.expire(attempt_key, 300) 

        # 检查是否达到封禁阈值
        if attempts >= MAX_RETRIES:
            # 写入黑名单，封禁 24 小时
            redis_client.setex(ban_key, BAN_TIME, "banned")
            redis_client.delete(attempt_key)
            return True, f"❌ 错误次数过多，该设备已被封禁 24 小时。"
        
        remaining = MAX_RETRIES - attempts
        return False, f"❌ 验证失败。再试 {remaining} 次后将被封禁设备。"
    except Exception as e:
        print(f"Firewall Logic Error: {e}")
        return False, "❌ 验证失败。"

# --- 安全大脑中间件 ---
@app.before_request
def make_session_permanent():
    """每次请求检查：白名单特权 > IP 地理围栏 > 指纹核对"""
    session.permanent = True

    # 仅针对已登录用户进行安全风控
    if 'user_logged_in' in session:
        current_ip = get_real_ip()

        # ✨✨✨ 1. 白名单特权通道：如果在白名单中，无条件放行 ✨✨✨
        if current_ip in TRUSTED_WHITELIST_IPS:
            session['login_ip'] = current_ip
            return

        current_device_id = request.cookies.get('fp_device_id', 'Unknown')
        last_ip = session.get('login_ip')
        last_device_id = session.get('device_id')
        login_region = session.get('login_region', '未知区域')

        # 2. IP 完全没变，直接放行
        if last_ip == current_ip:
            return

        # 3. IP 变了，先看浏览器指纹对不对
        if last_device_id and last_device_id == current_device_id:
            # 指纹一致，查一下新 IP 在哪个省份
            current_geo = fetch_geo_from_ip(current_ip)
            current_region = f"{current_geo[2]}-{current_geo[3]}" if current_geo else "未知区域"

            # 如果是在同一个省份切换网络，静默放行并更新 IP
            if current_region == login_region or "未知" in current_region:
                session['login_ip'] = current_ip
                return
            else:
                # ❌ 危险：指纹对，但瞬间跨省/跨国。高度疑似 Cookie 劫持！
                session.clear()
                print(f"⚠️ [安全警报] 异地 Cookie 劫持拦截！原归属地: {login_region}, 现归属地: {current_region}")
                return redirect(url_for('login'))
        else:
            # ❌ 危险：完全陌生的设备尝试使用旧 Session
            session.clear()
            print(f"⚠️ [安全警报] 未知设备尝试使用旧 Session！")
            return redirect(url_for('login'))

app.secret_key = os.getenv('SECRET_KEY', 'a_very_secret_key_for_the_3in1_panel')
PASSWORD = os.getenv("PANEL_PASSWORD", "You22kme#12345")
DEBUG_MODE = os.getenv("FLASK_DEBUG", "false").lower() in ['true', '1', 't']

# --- API 密钥初始化 ---
def initialize_app_config():
    """初始化 API 密钥配置"""
    config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    if 'api_secret_key' not in config or not config.get('api_secret_key'):
        print("首次启动或API密钥不存在，正在生成新的API密钥...")
        new_key = secrets.token_hex(32) 
        config['api_secret_key'] = new_key

        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
            print(f"新的API密钥已生成并保存到 {CONFIG_FILE}")
        except IOError as e:
            pass

initialize_app_config()

# --- Celery Configuration ---
redis_url = os.environ.get('REDIS_URL', 'redis://redis:6379/0')
app.config.update(
    broker_url=redis_url,
    result_backend=redis_url,
    broker_connection_retry_on_startup=True,
    SEND_FILE_MAX_AGE_DEFAULT=0,
    TEMPLATES_AUTO_RELOAD=DEBUG_MODE
)

celery = Celery(app.name, broker=app.config['broker_url'])
celery.conf.update(app.config)

# --- Import and Register Blueprints ---
from blueprints.aws_panel import aws_bp
from blueprints.azure_panel import azure_bp, init_db as init_azure_db
from blueprints.oci_panel import oci_bp, init_db as init_oci_db, recover_snatching_tasks
from blueprints.api_bp import api_bp

app.register_blueprint(aws_bp, url_prefix='/aws')
app.register_blueprint(azure_bp, url_prefix='/azure')
app.register_blueprint(oci_bp, url_prefix='/oci')
app.register_blueprint(api_bp, url_prefix='/api/v1/oci')

@worker_ready.connect
def on_worker_ready(**kwargs):
    print("Celery worker is ready. Running OCI task recovery check...")
    with app.app_context():
        recover_snatching_tasks()

# --- MFA Helper Functions ---
def get_mfa_secret():
    if os.path.exists(MFA_FILE):
        try:
            with open(MFA_FILE, 'r') as f:
                data = json.load(f)
                return data.get('secret')
        except:
            return None
    return None

def save_mfa_secret(secret):
    with open(MFA_FILE, 'w') as f:
        json.dump({'secret': secret}, f)

# --- Routes ---

@app.route('/setup-mfa', methods=['GET', 'POST'])
def setup_mfa():
    """首次登录强制绑定 MFA"""
    if not session.get('pre_mfa_auth'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        secret = session.get('temp_mfa_secret')
        code = request.form.get('code')
        totp = pyotp.TOTP(secret)
        
        if totp.verify(code):
            # 验证成功，保存密钥并正式登录
            save_mfa_secret(secret)
            session['user_logged_in'] = True
            
            # 记录登录 IP、设备指纹 和 登录区域
            client_ip = get_real_ip()
            session['login_ip'] = client_ip
            session['device_id'] = request.cookies.get('fp_device_id', 'Unknown_Device')
            
            geo = fetch_geo_from_ip(client_ip)
            if geo:
                session['login_region'] = f"{geo[2]}-{geo[3]}"
            else:
                session['login_region'] = "未知区域"
            
            session.pop('pre_mfa_auth', None)
            session.pop('temp_mfa_secret', None)
            return redirect(url_for('index'))
        else:
            return render_template('mfa_setup.html', error="验证码错误，请重试", secret=secret, qr_code=session.get('temp_mfa_qr'))

    secret = pyotp.random_base32()
    session['temp_mfa_secret'] = secret
    
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name="CloudManagerAdmin", issuer_name="CloudManager")
    img = qrcode.make(uri)
    buffered = io.BytesIO()
    img.save(buffered) 
    img_str = base64.b64encode(buffered.getvalue()).decode()
    session['temp_mfa_qr'] = img_str
    
    return render_template('mfa_setup.html', secret=secret, qr_code=img_str)

@app.route('/login', methods=['GET', 'POST'])
def login():
    # 1. 获取客户端 IP 和 设备指纹
    client_ip = get_real_ip()
    client_id = request.cookies.get('fp_device_id') or client_ip

    # 2. 检查黑名单 (查设备指纹或IP是否被封禁)
    if redis_client:
        ban_key = f"blacklist:{client_id}"
        if redis_client.exists(ban_key):
             return render_template('login.html', error="❌ 该设备因多次尝试失败已被暂时封禁，请 24 小时后再试。"), 403

    if request.method == 'POST':
        password = request.form.get('password')
        mfa_code = request.form.get('mfa_code')
        
        # 优先使用表单传来的指纹
        form_device_id = request.form.get('device_id')
        if form_device_id:
            client_id = form_device_id

        # 3. 验证密码
        if password == PASSWORD:
            secret = get_mfa_secret()
            
            if secret:
                # 4. 验证 MFA
                if not mfa_code:
                    return render_template('login.html', error='请输入二次验证码', mfa_enabled=True)
                
                totp = pyotp.TOTP(secret)
                if totp.verify(mfa_code):
                    # === 登录成功 ===
                    if redis_client:
                        redis_client.delete(f"login_attempts:{client_id}")

                    session.clear() 
                    session['user_logged_in'] = True
                    session['login_ip'] = client_ip
                    session['device_id'] = client_id

                    # 记录地理围栏基准点
                    geo = fetch_geo_from_ip(client_ip)
                    if geo:
                        session['login_region'] = f"{geo[2]}-{geo[3]}"
                    else:
                        session['login_region'] = "未知区域"

                    return redirect(url_for('index'))
                else:
                    is_banned, err_msg = handle_login_failure(client_id)
                    return render_template('login.html', error=err_msg, mfa_enabled=True)
            else:
                if redis_client:
                    redis_client.delete(f"login_attempts:{client_id}")
                session.clear()
                session['pre_mfa_auth'] = True
                return redirect(url_for('setup_mfa'))
        else:
            is_banned, err_msg = handle_login_failure(client_id)
            is_mfa = get_mfa_secret() is not None
            return render_template('login.html', error=err_msg, mfa_enabled=is_mfa)
            
    is_mfa = get_mfa_secret() is not None
    return render_template('login.html', mfa_enabled=is_mfa)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'user_logged_in' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('oci.oci_index')) 

# --- API 接口：获取 API 密钥 ---
@app.route('/api/get-app-api-key')
def get_app_api_key():
    if 'user_logged_in' not in session:
        return jsonify({"error": "用户未登录"}), 401

    api_key = None
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                api_key = config.get('api_secret_key')
        except (IOError, json.JSONDecodeError):
            pass 

    if api_key:
        return jsonify({"api_key": api_key})
    else:
        return jsonify({"error": "未能在服务器上找到或配置API密钥。"}), 500

# --- ✨ 新增 API 接口：将 IP 写入白名单 ---
@app.route('/api/add-whitelist', methods=['POST'])
def add_whitelist():
    """将当前 IP 添加到配置文件白名单中"""
    if 'user_logged_in' not in session:
        return jsonify({"success": False, "error": "用户未登录"}), 401

    data = request.get_json()
    target_ip = data.get('ip')

    if not target_ip:
        return jsonify({"success": False, "error": "未提供 IP 地址"}), 400

    global TRUSTED_WHITELIST_IPS
    config = {}

    # 读取现有配置
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception: pass

    whitelist = config.get('whitelist_ips', [])
    
    # 如果 IP 不在列表里，则添加并保存
    if target_ip not in whitelist:
        whitelist.append(target_ip)
        config['whitelist_ips'] = whitelist
        
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
            TRUSTED_WHITELIST_IPS = whitelist # 同步更新内存
            return jsonify({"success": True, "msg": f"✅ IP [{target_ip}] 已成功加入白名单！此后该 IP 登录将免受一切限制。"})
        except Exception as e:
            return jsonify({"success": False, "error": f"写入配置文件失败: {e}"}), 500
    
    return jsonify({"success": True, "msg": "该 IP 已经在白名单中，无需重复添加。"})

# --- CLI 工具：手动解封 设备指纹/IP ---
def cli_unban():
    if len(sys.argv) > 2 and sys.argv[1] == 'unban':
        if not redis_client:
            print("Error: Redis connection failed.")
            sys.exit(1)
            
        target_id = sys.argv[2]
        redis_client.delete(f"blacklist:{target_id}")
        redis_client.delete(f"login_attempts:{target_id}")
        print(f"✅ 已成功解封设备/IP: {target_id}")
        sys.exit(0)

cli_unban()

with app.app_context():
    print("Checking and initializing databases if necessary...")
    init_azure_db()
    init_oci_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=DEBUG_MODE)
