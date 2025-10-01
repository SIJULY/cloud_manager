import os
from flask import Flask, render_template, request, session, redirect, url_for
from blueprints.azure_panel import azure_bp, init_db as init_azure_db
from blueprints.oci_panel import oci_bp, init_db as init_oci_db, celery
from blueprints.aws_panel import aws_bp

# --- App Configuration ---
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'a_very_secret_key_for_the_3in1_panel')
PASSWORD = os.getenv("PANEL_PASSWORD", "050148Sq$")
DEBUG_MODE = os.getenv("FLASK_DEBUG", "false").lower() in ['true', '1', 't']

# --- Celery Configuration (for OCI) ---
redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
app.config.update(
    broker_url=redis_url,
    result_backend=redis_url,
    SEND_FILE_MAX_AGE_DEFAULT = 0,
    TEMPLATES_AUTO_RELOAD = DEBUG_MODE
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

# 【核心修正】无条件调用 init_db 函数。
# init_db 函数现在足够智能，可以自己判断是否需要创建表。
with app.app_context():
    print("Checking and initializing databases if necessary...")
    init_azure_db()
    init_oci_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=DEBUG_MODE)
