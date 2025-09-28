import os
from flask import Flask, render_template, request, session, redirect, url_for, g
# 导入新的AWS蓝图和数据库初始化函数
from blueprints.azure_panel import azure_bp, init_db as init_azure_db
from blueprints.oci_panel import oci_bp, init_db as init_oci_db, celery
from blueprints.aws_panel import aws_bp, init_db as init_aws_db

# --- App Configuration ---
app = Flask(__name__)
app.secret_key = 'a_very_secret_key_for_the_3in1_panel' 
PASSWORD = "You22kme#12345" 

# --- Celery Configuration (for OCI) ---
app.config.update(
    CELERY_BROKER_URL='redis://localhost:6379/0',
    CELERY_RESULT_BACKEND='redis://localhost:6379/0',
    SEND_FILE_MAX_AGE_DEFAULT = 0,
    TEMPLATES_AUTO_RELOAD = True
)
celery.conf.update(app.config)

# --- Register Blueprints ---
app.register_blueprint(azure_bp, url_prefix='/azure')
app.register_blueprint(oci_bp, url_prefix='/oci')
# 注册新的AWS蓝图
app.register_blueprint(aws_bp, url_prefix='/aws')

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
    # 默认重定向到AWS面板 (最新加入的)
    return redirect(url_for('aws.aws_index'))

if __name__ == '__main__':
    # Initialize databases for all panels on first run
    with app.app_context():
        # 确保数据库文件在项目根目录
        if not os.path.exists('azure_tasks.db'):
            init_azure_db()
        if not os.path.exists('oci_tasks.db'):
            init_oci_db()
        # 初始化AWS数据库
        if not os.path.exists('aws_tasks.db'):
            init_aws_db()
    
    app.run(host='0.0.0.0', port=5000, debug=True)
