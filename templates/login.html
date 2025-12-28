import os
import json
import secrets
import io
import base64
# --- 新增依赖 ---
import pyotp
import qrcode
# ----------------
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from celery import Celery
from celery.signals import worker_ready
import logging
from datetime import timedelta

# --- App Configuration ---
app = Flask(__name__)

# --- 会话过期设置 ---
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)

@app.before_request
def make_session_permanent():
    """让会话在每次请求后都重置计时器 (滑动窗口)"""
    session.permanent = True

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
redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
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

# --- Shared Routes (修改后的登录逻辑) ---

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
    if request.method == 'POST':
        password = request.form.get('password')
        mfa_code = request.form.get('mfa_code')
        
        if password == PASSWORD:
            # 1. 密码正确
            secret = get_mfa_secret()
            
            if secret:
                # 2. 已配置 MFA，必须校验验证码
                if not mfa_code:
                    # 如果用户只输了密码没输验证码，提示他
                    return render_template('login.html', error='请先在下方输入二次验证码')
                
                totp = pyotp.TOTP(secret)
                if totp.verify(mfa_code):
                    # 验证通过，授予登录权限
                    session.clear() # <--- 关键：先清除旧会话残留
                    session['user_logged_in'] = True
                    return redirect(url_for('index'))
                else:
                    return render_template('login.html', error='二次验证码错误')
            else:
                # 3. 未配置 MFA，强制跳转到设置页面
                session.clear() # <--- 关键：清除可能存在的旧登录状态
                session['pre_mfa_auth'] = True # 标记为"密码验证通过，待绑定MFA"
                return redirect(url_for('setup_mfa'))
        else:
            return render_template('login.html', error='密码错误')
            
    return render_template('login.html')

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

with app.app_context():
    print("Checking and initializing databases if necessary...")
    init_azure_db()
    init_oci_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=DEBUG_MODE)
