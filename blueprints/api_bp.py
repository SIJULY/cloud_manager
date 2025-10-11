# /app/blueprints/api_bp.py (完整替换代码)

import os
import json
import sqlite3
import uuid
from flask import Blueprint, request, jsonify, current_app
from functools import wraps
from app import celery

# 导入需要暴露给API的任务
from .oci_panel import (
    load_profiles, 
    get_oci_clients, 
    _instance_action_task, 
    _snatch_instance_task,
    _create_task_entry,
    _ensure_subnet_in_profile,
    oci
)
from .azure_panel import (
    _create_vm_task,
    _vm_action_task,
    _change_ip_task
)

api_bp = Blueprint('api', __name__)

DATABASE = 'oci_tasks.db'
CONFIG_FILE = 'config.json'

def get_api_key():
    if not os.path.exists(CONFIG_FILE): return None
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f).get('api_secret_key')
    except: return None

def query_db_api(query, args=(), one=False):
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(query, args)
    rv = cur.fetchall()
    cur.close()
    conn.close()
    return (rv[0] if rv else None) if one else rv

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = get_api_key()
        if not api_key:
            return jsonify({"error": "API Key not configured on the server."}), 500
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        provided_key = auth_header.split(' ')[1]
        
        import secrets
        if not secrets.compare_digest(provided_key, api_key):
            return jsonify({"error": "Invalid API Key"}), 403
        return f(*args, **kwargs)
    return decorated_function

@api_bp.route('/status', methods=['GET'])
def status():
    return jsonify({"status": "ok", "message": "Cloud Manager OCI API is running"})

@api_bp.route('/get-app-api-key', methods=['GET'])
def get_api_key_route():
    # 注意：在生产环境中，应保护此端点
    return jsonify({"api_key": current_app.config.get('API_KEY')})

@api_bp.route('/profiles', methods=['GET'])
@require_api_key
def get_profiles():
    try:
        return jsonify(list(load_profiles().keys()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_bp.route('/<string:alias>/instances', methods=['GET'])
@require_api_key
def get_instances_for_alias(alias):
    profiles = load_profiles()
    profile_config = profiles.get(alias)
    if not profile_config:
        return jsonify({"error": f"Profile with alias '{alias}' not found"}), 404

    clients, error = get_oci_clients(profile_config, validate=False)
    if error:
        return jsonify({"error": error}), 500

    try:
        compute_client = clients['compute']
        compartment_id = profile_config['tenancy']
        
        instances_raw = oci.pagination.list_call_get_all_results(
            compute_client.list_instances, compartment_id=compartment_id
        ).data

        instance_details_list = []
        for instance in instances_raw:
            if instance.lifecycle_state not in ['TERMINATED', 'TERMINATING']:
                vnic_id = None
                try:
                    vnic_attachments = oci.pagination.list_call_get_all_results(compute_client.list_vnic_attachments, compartment_id=compartment_id, instance_id=instance.id).data
                    if vnic_attachments:
                        vnic_id = vnic_attachments[0].vnic_id
                except:
                    pass
                
                instance_details_list.append({
                    "id": instance.id,
                    "display_name": instance.display_name,
                    "lifecycle_state": instance.lifecycle_state,
                    "vnic_id": vnic_id
                })
        
        return jsonify(instance_details_list)
    except Exception as e:
        return jsonify({"error": f"获取实例列表失败: {str(e)}"}), 500

@api_bp.route('/<string:alias>/network/security-list', methods=['GET'])
@require_api_key
def get_security_list_for_alias(alias):
    profiles = load_profiles()
    profile_config = profiles.get(alias)
    if not profile_config:
        return jsonify({"error": f"Profile '{alias}' not found"}), 404

    clients, error = get_oci_clients(profile_config, validate=False)
    if error:
        return jsonify({"error": error}), 500
        
    try:
        vnet_client = clients['vnet']
        tenancy_ocid = profile_config['tenancy']
        subnet_id = _ensure_subnet_in_profile(None, alias, vnet_client, tenancy_ocid)
        subnet = vnet_client.get_subnet(subnet_id).data
        if not subnet.security_list_ids:
            return jsonify({"error": "默认子网没有关联任何安全列表。"}), 404
        security_list_id = subnet.security_list_ids[0]
        security_list = vnet_client.get_security_list(security_list_id).data
        return jsonify(json.loads(str(security_list)))
    except Exception as e:
        return jsonify({"error": f"获取安全列表失败: {e}"}), 500

@api_bp.route('/<string:alias>/instance-action', methods=['POST'])
@require_api_key
def instance_action_for_alias(alias):
    data = request.json
    action, instance_id = data.get('action'), data.get('instance_id')
    if not all([action, instance_id]):
        return jsonify({"error": "Missing required parameters: action, instance_id"}), 400
    profiles = load_profiles()
    profile_config = profiles.get(alias)
    if not profile_config:
        return jsonify({"error": f"Profile with alias '{alias}' not found"}), 404
    task_name = f"{action} on instance {instance_id[-12:]}"
    task_id = _create_task_entry('action', task_name, alias)
    _instance_action_task.delay(task_id, profile_config, action, instance_id, data)
    return jsonify({"success": True, "message": f"Action '{action}' for instance '{instance_id}' has been queued.", "task_id": task_id}), 202

@api_bp.route('/<string:alias>/snatch-instance', methods=['POST'])
@require_api_key
def snatch_instance_for_alias(alias):
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
    try:
        task = query_db_api('SELECT id, type, name, status, result, created_at, account_alias FROM tasks WHERE id = ?', [task_id], one=True)
        if task:
            task_dict = dict(task)
            if 'account_alias' in task_dict:
                task_dict['alias'] = task_dict.pop('account_alias')
            return jsonify(task_dict)

        res = celery.AsyncResult(task_id)
        if res:
             return jsonify({'status': res.state, 'result': str(res.info)})
        return jsonify({'status': 'not_found'}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_bp.route('/tasks/<string:task_type>/<string:task_status>', methods=['GET'])
@require_api_key
def get_tasks_by_type_and_status(task_type, task_status):
    try:
        if task_status == 'running':
            tasks = query_db_api("SELECT id, name, result, account_alias FROM tasks WHERE type = ? AND status IN ('running', 'pending') ORDER BY created_at DESC", [task_type])
        elif task_status == 'completed':
            tasks = query_db_api("SELECT id, name, status, result, account_alias, created_at FROM tasks WHERE type = ? AND (status = 'success' OR 'failure') ORDER BY created_at DESC LIMIT 20", [task_type])
        else:
            return jsonify({"error": "Invalid task status"}), 400
        
        tasks_list = [dict(task) for task in tasks]
        for task_dict in tasks_list:
            if 'account_alias' in task_dict:
                task_dict['alias'] = task_dict.pop('account_alias')
        
        return jsonify(tasks_list)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
