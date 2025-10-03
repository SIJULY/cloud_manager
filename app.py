import os
import json
import secrets # <<< 新增导入
from flask import Flask, render_template, request, session, redirect, url_for
from celery import Celery, bootsteps
from kombu import Consumer, Exchange, Queue
import logging

# --- App Configuration ---
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'a_very_secret_key_for_the_3in1_panel')
PASSWORD = os.getenv("PANEL_PASSWORD", "050148Sq$")
DEBUG_MODE = os.getenv("FLASK_DEBUG", "false").lower() in ['true', '1', 't']

# <<< 新增：配置文件和密钥初始化 >>>
CONFIG_FILE = 'config.json'

def initialize_app_config():
    """
    检查并初始化应用配置，特别是API密钥。
    此函数将在程序首次启动时自动生成一个安全的API密钥。
    """
    config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass 

    if 'api_secret_key' not in config or not config.get('api_secret_key'):
        print("首次启动或API密钥不存在，正在生成新的API密钥...")
        new_key = secrets.token_hex(32) # 生成一个64位的安全随机字符串
        config['api_secret_key'] = new_key
        
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
            print(f"新的API密钥已生成并保存到 {CONFIG_FILE}")
        except IOError as e:
            print(f"错误：无法写入API密钥到文件 {CONFIG_FILE}: {e}")

# 在Flask App启动时执行初始化
initialize_app_config()
# <<< 初始化代码结束 >>>


# --- Celery Configuration ---
redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
app.config.update(
    broker_url=redis_url,
    result_backend=redis_url,
    broker_connection_retry_on_startup=True,
    SEND_FILE_MAX_AGE_DEFAULT=0,
    TEMPLATES_AUTO_RELOAD=DEBUG_MODE
)

# --- Create Celery Instance ---
celery = Celery(app.name, broker=app.config['broker_url'])
celery.conf.update(app.config)

# --- Import and Register Blueprints ---
from blueprints.aws_panel import aws_bp
from blueprints.azure_panel import azure_bp, init_db as init_azure_db
from blueprints.oci_panel import oci_bp, init_db as init_oci_db
from blueprints.api_bp import api_bp # <<< 新增导入 API 蓝图

app.register_blueprint(aws_bp, url_prefix='/aws')
app.register_blueprint(azure_bp, url_prefix='/azure')
app.register_blueprint(oci_bp, url_prefix='/oci')
app.register_blueprint(api_bp, url_prefix='/api/v1/oci') # <<< 新增注册 API 蓝图

# --- Shared Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == PASSWORD:
            session['user_logged_in'] = True
            return redirect(url_for('index'))
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
    return redirect(url_for('aws.aws_index')) # 默认跳转保持不变

# --- Database Initialization ---
with app.app_context():
    print("Checking and initializing databases if necessary...")
    init_azure_db()
    init_oci_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=DEBUG_MODE)
