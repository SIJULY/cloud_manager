import os
from flask import Flask, render_template, request, session, redirect, url_for
from blueprints.azure_panel import azure_bp, init_db as init_azure_db
from blueprints.oci_panel import oci_bp, init_db as init_oci_db, celery
from blueprints.aws_panel import aws_bp

# --- App Configuration ---
app = Flask(__name__)
app.secret_key = 'a_very_secret_key_for_the_3in1_panel'
# 从环境变量读取密码，如果找不到，则使用一个默认值
PASSWORD = os.getenv("PANEL_PASSWORD", "default_password") 

# --- Celery Configuration (for OCI) ---
app.config.update(
    broker_url='redis://localhost:6379/0',
    result_backend='redis://localhost:6379/0',
    SEND_FILE_MAX_AGE_DEFAULT = 0,
    TEMPLATES_AUTO_RELOAD = True
)
celery.conf.update(app.config)

# --- Register Blueprints ---
app.register_blueprint(aws_bp, url_prefix='/aws')
app.register_blueprint(azure_bp, url_prefix='/azure')
app.register_blueprint(oci_bp, url_prefix='/oci')

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
    return redirect(url_for('aws.aws_index'))

# --- Database Initialization on First Run ---
with app.app_context():
    if not os.path.exists('azure_tasks.db'):
        print("Initializing Azure database...")
        init_azure_db()
    if not os.path.exists('oci_tasks.db'):
        print("Initializing OCI database...")
        init_oci_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
