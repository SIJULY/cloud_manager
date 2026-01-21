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

# --- 辅助函数：获取真实IP ---
def get_real_ip():
    """获取真实用户IP，兼容 Caddy/Nginx 反向代理"""
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0]
    return request.remote_addr

# --- 辅助函数：处理登录失败 ---
def handle_login_failure(ip_address):
    """
    增加错误计数，如果达到阈值则封禁IP
    返回: (是否被封禁, 错误提示信息)
    """
    if not redis_client:
        return False, "❌ 系统错误: Redis未连接，防火墙未生效。"

    attempt_key = f"login_attempts:{ip_address}"
    ban_key = f"blacklist:{ip_address}"

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
            # 删除临时计数器
            redis_client.delete(attempt_key)
            return True, f"❌ 错误次数过多，IP 已被封禁 24 小时。"
        
        remaining = MAX_RETRIES - attempts
        return False, f"❌ 验证失败。再试 {remaining} 次后将被封禁 IP。"
    except Exception as e:
        print(f"Firewall Logic Error: {e}")
        return False, "❌ 验证失败。"

@app.before_request
def make_session_permanent():
    """每次请求检查 IP 是否一致，一致则自动续期"""
    session.permanent = True

    # 获取当前请求的真实 IP
    current_ip = get_real_ip()

    # 检查逻辑：如果已登录，但 IP 变了 -> 踢下线
    if 'user_logged_in' in session:
        recorded_ip = session.get('login_ip')
        
        # 如果 Session 里存了 IP，但和现在的 IP 不一样
        if recorded_ip and recorded_ip != current_ip:
            session.clear() # 销毁凭证
            print(f"⚠️ [安全警报] 会话劫持拦截！原IP: {recorded_ip}, 现IP: {current_ip}")
            return redirect(url_for('login'))

app.secret_key = os.getenv('SECRET_KEY', 'a_very_secret_key_for_the_3in1_panel')
PASSWORD = os.getenv("PANEL_PASSWORD", "You22kme#12345")
DEBUG_MODE = os.getenv("FLASK_DEBUG", "false").lower() in ['true', '1', 't']

# --- 配置文件和密钥初始化 ---
CONFIG_FILE = 'config.json'
MFA_FILE = 'mfa_secret.json'  # MFA 密钥存储文件

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
            print(f"错误：无法写入API密钥到文件 {CONFIG_FILE}: {e}")

initialize_app_config()

# --- Celery Configuration ---
# Celery 也使用同一个 Redis URL
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
    # 只有通过了密码验证但未绑定MFA的用户才能访问
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
            
            # 记录登录 IP
            session['login_ip'] = get_real_ip()
            
            session.pop('pre_mfa_auth', None)
            session.pop('temp_mfa_secret', None)
            return redirect(url_for('index'))
        else:
            return render_template('mfa_setup.html', error="验证码错误，请重试", secret=secret, qr_code=session.get('temp_mfa_qr'))

    # 生成新密钥
    secret = pyotp.random_base32()
    session['temp_mfa_secret'] = secret
    
    # 生成二维码
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
    # 1. 优先检查 IP 黑名单
    client_ip = get_real_ip()
    if redis_client:
        ban_key = f"blacklist:{client_ip}"
        if redis_client.exists(ban_key):
             return render_template('login.html', error="❌ 该IP因多次尝试失败已被暂时封禁，请 24 小时后再试。"), 403

    if request.method == 'POST':
        password = request.form.get('password')
        mfa_code = request.form.get('mfa_code')
        
        # 2. 验证密码
        if password == PASSWORD:
            secret = get_mfa_secret()
            
            if secret:
                # 3. 验证 MFA
                if not mfa_code:
                    return render_template('login.html', error='请输入二次验证码', mfa_enabled=True)
                
                totp = pyotp.TOTP(secret)
                if totp.verify(mfa_code):
                    # === 登录成功 ===
                    # 清除错误计数
                    if redis_client:
                        redis_client.delete(f"login_attempts:{client_ip}")

                    session.clear() # 清除旧会话
                    session['user_logged_in'] = True
                    session['login_ip'] = client_ip
                    return redirect(url_for('index'))
                else:
                    # === MFA 错误 (计入失败次数) ===
                    is_banned, err_msg = handle_login_failure(client_ip)
                    return render_template('login.html', error=err_msg, mfa_enabled=True)
            else:
                # 未配置 MFA，进入设置流程 (通常不算失败，可以清除计数)
                if redis_client:
                    redis_client.delete(f"login_attempts:{client_ip}")
                session.clear()
                session['pre_mfa_auth'] = True
                return redirect(url_for('setup_mfa'))
        else:
            # === 密码错误 (计入失败次数) ===
            is_banned, err_msg = handle_login_failure(client_ip)
            # 即使密码错了，如果系统配置了MFA，也要显示MFA框（防止枚举）
            is_mfa = get_mfa_secret() is not None
            return render_template('login.html', error=err_msg, mfa_enabled=is_mfa)
            
    # GET 请求：进入页面
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

# --- CLI 工具：手动解封 IP ---
# 使用方法: docker compose exec web python app.py unban <IP>
def cli_unban():
    if len(sys.argv) > 2 and sys.argv[1] == 'unban':
        if not redis_client:
            print("Error: Redis connection failed.")
            sys.exit(1)
            
        target_ip = sys.argv[2]
        redis_client.delete(f"blacklist:{target_ip}")
        redis_client.delete(f"login_attempts:{target_ip}")
        print(f"✅ 已成功解封 IP: {target_ip}")
        sys.exit(0)

# 在初始化数据库之前检查 CLI 命令
cli_unban()

with app.app_context():
    print("Checking and initializing databases if necessary...")
    init_azure_db()
    init_oci_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=DEBUG_MODE)
