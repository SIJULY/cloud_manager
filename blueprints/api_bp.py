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
    api_key = current_app.config.get('PANEL_API_KEY')
    if api_key:
        return api_key
    if not os.path.exists(CONFIG_FILE): return None
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            return config_data.get('PANEL_API_KEY') or config_data.get('api_secret_key')
    except: 
        return None

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

# --- ✨ 关键修复点在这里 ✨ ---
@api_bp.route('/profiles', methods=['GET'])
@require_api_key
def get_profiles():
    """
    获取OCI账户列表。
    这个接口现在会解析新的 profiles.json 结构，
    并返回一个按照用户自定义顺序（或字母顺序）排列的账户名列表。
    """
    try:
        # 1. 加载包含排序信息的完整数据
        all_data = load_profiles()
        profiles_dict = all_data.get("profiles", {})
        profile_order = all_data.get("profile_order", [])

        # 2. 确保返回的列表是完整且有序的
        #    - 先按用户自定义的顺序排列
        #    - 再把可能遗漏的（新添加的）账户按字母顺序追加到末尾
        ordered_profiles = [p for p in profile_order if p in profiles_dict]
        missing_profiles = sorted(
            [p for p in profiles_dict if p not in ordered_profiles],
            key=lambda name: name.lower()
        )
        
        final_order = ordered_profiles + missing_profiles
        
        # 3. 返回TGBot期望的、纯净的账户名列表
        return jsonify(final_order)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
# --- ✨ 修复结束 ✨ ---

@api_bp.route('/<string:alias>/instances', methods=['GET'])
@require_api_key
def get_instances_for_alias(alias):
    # ✨ 逻辑调整：从新的数据结构中获取账户配置
    all_data = load_profiles()
    profile_config = all_data.get("profiles", {}).get(alias)
    if not profile_config:
        return jsonify({"error": f"Profile with alias '{alias}' not found"}), 404

    clients, error = get_oci_clients(profile_config, validate=False)
    if error:
        return jsonify({"error": error}), 500

    try:
        compute_client = clients['compute']
        vnet_client = clients['vnet']
        bs_client = clients['bs']
        compartment_id = profile_config['tenancy']
        
        instances = oci.pagination.list_call_get_all_results(
            compute_client.list_instances, compartment_id=compartment_id
        ).data

        instance_details_list = []
        for instance in instances:
            data = {"display_name": instance.display_name, "id": instance.id, "lifecycle_state": instance.lifecycle_state, "shape": instance.shape, "time_created": instance.time_created.isoformat() if instance.time_created else None, "ocpus": getattr(instance.shape_config, 'ocpus', 'N/A'), "memory_in_gbs": getattr(instance.shape_config, 'memory_in_gbs', 'N/A'), "public_ip": "无", "ipv6_address": "无", "boot_volume_size_gb": "N/A", "vnic_id": None, "subnet_id": None}
            try:
                if instance.lifecycle_state not in ['TERMINATED', 'TERMINATING']:
                    vnic_attachments = oci.pagination.list_call_get_all_results(compute_client.list_vnic_attachments, compartment_id=compartment_id, instance_id=instance.id).data
                    if vnic_attachments:
                        vnic_id = vnic_attachments[0].vnic_id
                        data.update({'vnic_id': vnic_id, 'subnet_id': vnic_attachments[0].subnet_id})
                        vnic = vnet_client.get_vnic(vnic_id).data
                        data.update({'public_ip': vnic.public_ip or "无"})
                        ipv6s = vnet_client.list_ipv6s(vnic_id=vnic_id).data
                        if ipv6s: data['ipv6_address'] = ipv6s[0].ip_address
                    boot_vol_attachments = oci.pagination.list_call_get_all_results(compute_client.list_boot_volume_attachments, instance.availability_domain, compartment_id, instance_id=instance.id).data
                    if boot_vol_attachments:
                        boot_vol = bs_client.get_boot_volume(boot_vol_attachments[0].boot_volume_id).data
                        data['boot_volume_size_gb'] = f"{int(boot_vol.size_in_gbs)} GB"
            except Exception:
                pass
            instance_details_list.append(data)
        
        return jsonify(instance_details_list)
    except Exception as e:
        return jsonify({"error": f"获取实例列表失败: {str(e)}"}), 500

@api_bp.route('/<string:alias>/instance-action', methods=['POST'])
@require_api_key
def instance_action_for_alias(alias):
    data = request.json
    action, instance_id = data.get('action'), data.get('instance_id')
    if not all([action, instance_id]):
        return jsonify({"error": "Missing required parameters: action, instance_id"}), 400
    
    # ✨ 逻辑调整：从新的数据结构中获取账户配置
    all_data = load_profiles()
    profile_config = all_data.get("profiles", {}).get(alias)
    if not profile_config:
        return jsonify({"error": f"Profile with alias '{alias}' not found"}), 404
        
    task_name = f"{action} on {data.get('instance_name', instance_id[-12:])}"
    task_id = _create_task_entry('action', task_name, alias)
    
    config_with_alias = profile_config.copy()
    config_with_alias['alias'] = alias
    
    data['_source'] = 'bot'
    _instance_action_task.delay(task_id, config_with_alias, action, instance_id, data)

    return jsonify({"success": True, "message": f"Action '{action}' for instance '{instance_id}' has been queued.", "task_id": task_id}), 202

@api_bp.route('/<string:alias>/snatch-instance', methods=['POST'])
@require_api_key
def snatch_instance_for_alias(alias):
    data = request.json
    
    # ✨ 逻辑调整：从新的数据结构中获取账户配置
    all_data = load_profiles()
    profile_config = all_data.get("profiles", {}).get(alias)
    if not profile_config:
        return jsonify({"error": f"Profile with alias '{alias}' not found"}), 404
        
    task_name = data.get('display_name_prefix', 'snatch-instance')
    task_id = _create_task_entry('snatch', task_name, alias)
    
    run_id = str(uuid.uuid4())
    auto_bind_domain = data.get('auto_bind_domain', False)
    
    data['_source'] = 'bot'
    _snatch_instance_task.delay(task_id, profile_config, alias, data, run_id, auto_bind_domain)

    return jsonify({"success": True, "message": "抢占实例任务已提交...", "task_id": task_id}), 202

@api_bp.route('/task-status/<string:task_id>', methods=['GET'])
@require_api_key
def get_task_status(task_id):
    try:
        task = query_db_api('SELECT status, result, type FROM tasks WHERE id = ?', [task_id], one=True)
        if task:
            return jsonify({'status': task['status'], 'result': task['result'], 'type': task['type']})
        
        res = celery.AsyncResult(task_id)
        if res:
             return jsonify({'status': res.state, 'result': str(res.info)})
             
        return jsonify({'status': 'not_found'}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_bp.route('/tasks/snatch/running', methods=['GET'])
@require_api_key
def get_running_snatch_tasks():
    try:
        tasks = query_db_api("SELECT id, name, result, created_at, account_alias, status FROM tasks WHERE type = 'snatch' AND status IN ('running', 'paused') ORDER BY created_at DESC")
        return jsonify([dict(task) for task in tasks])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_bp.route('/tasks/snatch/completed', methods=['GET'])
@require_api_key
def get_completed_snatch_tasks():
    try:
        tasks = query_db_api("SELECT id, name, status, result, created_at, account_alias FROM tasks WHERE type = 'snatch' AND (status = 'success' OR status = 'failure') ORDER BY created_at DESC LIMIT 50")
        return jsonify([dict(task) for task in tasks])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
