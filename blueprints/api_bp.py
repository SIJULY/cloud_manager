# 文件名: blueprints/api_bp.py

import os
import json
import sqlite3
import uuid
from flask import Blueprint, request, jsonify
from functools import wraps
from app import celery # 从主程序导入共享的 Celery 实例

# 从 oci_panel 导入需要复用的核心业务逻辑
from .oci_panel import (
    load_profiles,
    get_oci_clients,
    _instance_action_task,
    _create_instance_task,
    _snatch_instance_task,
    _create_task_entry # 导入我们重构过的函数
)

# --- Blueprint Setup ---
api_bp = Blueprint('api', __name__)

# --- Configuration ---
CONFIG_FILE = 'config.json'
DATABASE = 'oci_tasks.db'

# --- 辅助函数 ---
def get_api_key():
    """从配置文件安全地加载 API 密钥"""
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            return config.get('api_secret_key')
    except (IOError, json.JSONDecodeError):
        return None

def query_db_api(query, args=(), one=False):
    """API 使用的独立数据库查询函数"""
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(query, args)
    rv = cur.fetchall()
    cur.close()
    conn.close()
    return (rv[0] if rv else None) if one else rv

# --- 安全验证装饰器 ---
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = get_api_key()
        if not api_key:
            return jsonify({"error": "API Key not configured on the server. Please restart the panel to generate one."}), 500

        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        
        provided_key = auth_header.split(' ')[1]
        if provided_key != api_key:
            return jsonify({"error": "Invalid API Key"}), 403
            
        return f(*args, **kwargs)
    return decorated_function

# --- API 路由 ---

@api_bp.route('/status', methods=['GET'])
def status():
    """一个简单的状态检查端点，用于测试API是否工作"""
    return jsonify({"status": "ok", "message": "Cloud Manager OCI API is running"})

@api_bp.route('/profiles', methods=['GET'])
@require_api_key
def get_profiles():
    """获取所有已配置的OCI账号别名列表"""
    try:
        profiles = load_profiles()
        return jsonify(list(profiles.keys()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_bp.route('/<string:alias>/instance-action', methods=['POST'])
@require_api_key
def instance_action_for_alias(alias):
    """对指定账号下的实例执行操作 (START, STOP, RESTART, TERMINATE 等)"""
    data = request.json
    action = data.get('action')
    instance_id = data.get('instance_id')

    if not all([action, instance_id]):
        return jsonify({"error": "Missing required parameters: action, instance_id"}), 400

    profiles = load_profiles()
    profile_config = profiles.get(alias)
    if not profile_config:
        return jsonify({"error": f"Profile with alias '{alias}' not found"}), 404

    task_name = f"{action} on instance {instance_id[-12:]}"
    # 使用重构后的函数创建任务记录，并直接传入 alias
    task_id = _create_task_entry('action', task_name, alias)

    # 异步执行任务
    _instance_action_task.delay(task_id, profile_config, action, instance_id, data)

    return jsonify({
        "success": True,
        "message": f"Action '{action}' for instance '{instance_id}' has been queued.",
        "task_id": task_id
    }), 202

@api_bp.route('/<string:alias>/create-instance', methods=['POST'])
@require_api_key
def create_instance_for_alias(alias):
    """为指定账号创建实例"""
    data = request.json
    profiles = load_profiles()
    profile_config = profiles.get(alias)
    if not profile_config:
        return jsonify({"error": f"Profile with alias '{alias}' not found"}), 404
    
    task_name = data.get('display_name_prefix', 'create-instance')
    task_id = _create_task_entry('create', task_name, alias)
    _create_instance_task.delay(task_id, profile_config, alias, data)
    
    return jsonify({"success": True, "message": "创建实例请求已提交...", "task_id": task_id}), 202

@api_bp.route('/<string:alias>/snatch-instance', methods=['POST'])
@require_api_key
def snatch_instance_for_alias(alias):
    """为指定账号启动抢占实例任务"""
    data = request.json
    profiles = load_profiles()
    profile_config = profiles.get(alias)
    if not profile_config:
        return jsonify({"error": f"Profile with alias '{alias}' not found"}), 404
        
    task_name = data.get('display_name_prefix', 'snatch-instance')
    task_id = _create_task_entry('snatch', task_name, alias)
    _snatch_instance_task.delay(task_id, profile_config, alias, data)

    return jsonify({"success": True, "message": "抢占实例任务已提交...", "task_id": task_id}), 202


@api_bp.route('/task-status/<string:task_id>', methods=['GET'])
@require_api_key
def get_task_status(task_id):
    """获取一个异步任务的状态和结果"""
    try:
        task = query_db_api('SELECT status, result FROM tasks WHERE id = ?', [task_id], one=True)
        if task:
            return jsonify({'status': task['status'], 'result': task['result']})
        
        # 如果数据库没有，可以再检查一下 Celery 的状态
        res = celery.AsyncResult(task_id)
        if res:
             return jsonify({'status': res.state, 'result': str(res.info)})
             
        return jsonify({'status': 'not_found'}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
