import os, json, threading, string, random, base64, time, logging, uuid, sqlite3
from flask import Blueprint, render_template, jsonify, request, session, g, redirect, url_for, current_app
from functools import wraps
from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient, SubscriptionClient
from azure.core.exceptions import ClientAuthenticationError, ResourceNotFoundError, HttpResponseError

# --- Blueprint Setup ---
azure_bp = Blueprint('azure', __name__, template_folder='../templates', static_folder='../static')

# --- Configuration ---
KEYS_FILE = "azure_keys.json"
DATABASE = 'azure_tasks.db'

# --- Helpers & DB ---
def get_db():
    db = getattr(g, '_azure_database', None)
    if db is None:
        db = g._azure_database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@azure_bp.teardown_request
def close_connection(exception):
    db = getattr(g, '_azure_database', None)
    if db is not None:
        db.close()

def init_db():
    # 直接连接数据库文件，如果不存在则会创建
    db = sqlite3.connect(DATABASE)
    cursor = db.cursor()
    
    # 检查 'tasks' 表在数据库中是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
    table_exists = cursor.fetchone()
    
    # 如果表不存在，就创建它
    if not table_exists:
        print("Initializing Azure database table 'tasks'...")
        logging.info("Azure database file found, but 'tasks' table is missing. Creating table...")
        schema_sql = "CREATE TABLE tasks (id TEXT PRIMARY KEY, type TEXT, name TEXT, status TEXT NOT NULL, result TEXT, created_at TEXT);"
        cursor.executescript(schema_sql)
        db.commit()
        logging.info("'tasks' table created successfully in Azure database.")
    
    db.close()

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def load_keys():
    if not os.path.exists(KEYS_FILE): return []
    try:
        with open(KEYS_FILE, 'r') as f: content = f.read(); return json.loads(content) if content else []
    except json.JSONDecodeError: return []

def save_keys(keys):
    with open(KEYS_FILE, 'w') as f: json.dump(keys, f, indent=4)

def generate_password(length=12):
    characters = string.ascii_letters + string.digits + "!@#$%^&*()"
    return ''.join(random.choice(characters) for i in range(length))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_logged_in" not in session: return jsonify({"error": "用户未登录"}), 401
        return f(*args, **kwargs)
    return decorated_function

def azure_credentials_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'azure_credentials' not in session: return jsonify({"error": "请先选择一个Azure账户"}), 403
        g.azure_creds = session['azure_credentials']
        return f(*args, **kwargs)
    return decorated_function

# --- Routes ---
@azure_bp.route("/")
@login_required
def azure_index():
    return render_template("azure.html")

@azure_bp.route("/api/accounts", methods=["GET", "POST"])
@login_required
def manage_accounts():
    if request.method == "GET": accounts = load_keys(); return jsonify(accounts)
    data = request.json; keys = load_keys()
    if any(k['name'] == data['name'] for k in keys): return jsonify({"error": "账户名称已存在"}), 400
    keys.append(data); save_keys(keys); return jsonify({"success": True}), 201

@azure_bp.route("/api/accounts/<name>", methods=["DELETE"])
@login_required
def delete_account(name):
    keys = load_keys(); keys_to_keep = [k for k in keys if k['name'] != name]
    if len(keys) == len(keys_to_keep): return jsonify({"error": "账户未找到"}), 404
    save_keys(keys_to_keep)
    if session.get('azure_credentials', {}).get('name') == name: session.pop('azure_credentials', None)
    return jsonify({"success": True})
    
@azure_bp.route('/api/accounts/edit', methods=['POST'])
@login_required
def edit_account():
    data = request.json; original_name, new_name, expiration_date = data.get('original_name'), data.get('new_name'), data.get('expiration_date')
    if not original_name or not new_name: return jsonify({"error": "账户名称不能为空"}), 400
    keys = load_keys(); account_to_edit = next((k for k in keys if k['name'] == original_name), None)
    if not account_to_edit: return jsonify({"error": "未找到原始账户"}), 404
    if new_name != original_name and any(k['name'] == new_name for k in keys): return jsonify({"error": "新的账户名称已存在"}), 400
    account_to_edit['name'] = new_name; account_to_edit['expiration_date'] = expiration_date; save_keys(keys)
    if session.get('azure_credentials', {}).get('name') == original_name:
        session['azure_credentials']['name'] = new_name; session['azure_credentials']['expiration_date'] = expiration_date
    return jsonify({"success": True})
    
@azure_bp.route("/api/session", methods=["POST", "DELETE", "GET"])
@login_required
def azure_session():
    if request.method == "POST":
        name = request.json.get("name"); account = next((k for k in load_keys() if k['name'] == name), None)
        if not account: return jsonify({"error": "账户未找到"}), 404
        session['azure_credentials'] = account; return jsonify({"success": True, "name": account['name']})
    if request.method == "DELETE": session.pop('azure_credentials', None); return jsonify({"success": True})
    if 'azure_credentials' in session: return jsonify({"logged_in": True, "name": session['azure_credentials']['name']})
    return jsonify({"logged_in": False})

@azure_bp.route('/api/vms')
@login_required
@azure_credentials_required
def get_vms():
    try:
        credential = ClientSecretCredential(tenant_id=g.azure_creds['tenant_id'], client_id=g.azure_creds['client_id'], client_secret=g.azure_creds['client_secret'])
        subscription_id = g.azure_creds['subscription_id']
        compute_client, network_client = ComputeManagementClient(credential, subscription_id), NetworkManagementClient(credential, subscription_id)
        vm_list = []
        for vm in compute_client.virtual_machines.list_all():
            resource_group = vm.id.split('/')[4]
            try:
                instance_view = compute_client.virtual_machines.instance_view(resource_group, vm.name)
                status, public_ip = "Unknown", "N/A"
                power_state = next((s for s in instance_view.statuses if s.code.startswith('PowerState/')), None)
                if power_state: status = power_state.display_status.replace("VM ", "")
            except ResourceNotFoundError:
                status = "Not Found"

            try:
                if vm.network_profile and vm.network_profile.network_interfaces:
                    nic_id = vm.network_profile.network_interfaces[0].id; nic_name = nic_id.split('/')[-1]
                    nic = network_client.network_interfaces.get(resource_group, nic_name)
                    if nic.ip_configurations and nic.ip_configurations[0].public_ip_address:
                        pip_id = nic.ip_configurations[0].public_ip_address.id; pip_name = pip_id.split('/')[-1]
                        pip = network_client.public_ip_addresses.get(resource_group, pip_name); public_ip = pip.ip_address
            except Exception: public_ip = "查询失败"
            vm_list.append({"name": vm.name, "location": vm.location, "vm_size": vm.hardware_profile.vm_size, "status": status, "resource_group": resource_group, "public_ip": public_ip, "time_created": vm.time_created.isoformat() if vm.time_created else None})
        return jsonify(vm_list)
    except Exception as e: return jsonify({"error": str(e)}), 500

@azure_bp.route('/api/regions')
@login_required
@azure_credentials_required
def get_regions():
    try:
        credential = ClientSecretCredential(tenant_id=g.azure_creds['tenant_id'], client_id=g.azure_creds['client_id'], client_secret=g.azure_creds['client_secret'])
        subscription_client = SubscriptionClient(credential)
        locations = subscription_client.subscriptions.list_locations(g.azure_creds['subscription_id'])
        region_list = [{"name": loc.name, "display_name": loc.display_name} for loc in locations]
        return jsonify(region_list)
    except Exception as e: return jsonify({"error": f"获取区域列表失败: {str(e)}"}), 500

def _run_background_task(target_func, **kwargs):
    app = current_app._get_current_object()
    threading.Thread(target=target_func, args=(app,), kwargs=kwargs).start()

@azure_bp.route('/api/vm-action', methods=['POST'])
@login_required
@azure_credentials_required
def vm_action():
    data = request.json
    action = data.get('action')
    vm_name = data.get('vm_name')
    
    task_id = str(uuid.uuid4())
    db = get_db()
    db.execute('INSERT INTO tasks (id, status, result) VALUES (?, ?, ?)', (task_id, 'pending', f"任务已提交: {action} on {vm_name}"))
    db.commit()

    task_kwargs = {
        'task_id': task_id,
        'credential_dict': {k: g.azure_creds[k] for k in ['tenant_id', 'client_id', 'client_secret']},
        'subscription_id': g.azure_creds['subscription_id'],
        'action': action,
        'resource_group': data.get('resource_group'),
        'vm_name': vm_name
    }
    
    _run_background_task(_vm_action_task, **task_kwargs)
    return jsonify({"message": f"操作已提交，将在后台执行...", "task_id": task_id})

def _vm_action_task(app, task_id, credential_dict, subscription_id, action, resource_group, vm_name):
    with app.app_context():
        db = sqlite3.connect(DATABASE)
        db.execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('running', f'正在对 {vm_name} 执行 {action} 操作...', task_id)); db.commit()
        try:
            credential = ClientSecretCredential(**credential_dict)
            compute_client = ComputeManagementClient(credential, subscription_id)
            
            if action == 'start': 
                poller = compute_client.virtual_machines.begin_start(resource_group, vm_name)
                result_message = f"✅ 虚拟机 {vm_name} 启动成功！"
            elif action == 'stop': 
                poller = compute_client.virtual_machines.begin_deallocate(resource_group, vm_name)
                result_message = f"✅ 虚拟机 {vm_name} 停止成功！"
            elif action == 'restart': 
                poller = compute_client.virtual_machines.begin_restart(resource_group, vm_name)
                result_message = f"✅ 虚拟机 {vm_name} 重启成功！"
            elif action == 'delete':
                resource_client = ResourceManagementClient(credential, subscription_id)
                poller = resource_client.resource_groups.begin_delete(resource_group)
                result_message = f"✅ 资源组 {resource_group} 及内部资源删除成功！"
            else: 
                raise ValueError("未知的操作")
            
            poller.result()
            db.execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('success', result_message, task_id)); db.commit()
        except Exception as e:
            error_message = f"❌ 对 {vm_name} 执行 {action} 失败: {str(e)}"
            db.execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', error_message, task_id)); db.commit()
            logging.error(f"后台任务 '{action}' 失败: {e}")
        finally:
            db.close()
    
@azure_bp.route('/api/vm-change-ip', methods=['POST'])
@login_required
@azure_credentials_required
def change_vm_ip():
    data = request.json
    vm_name = data.get('vm_name')

    task_id = str(uuid.uuid4())
    db = get_db()
    db.execute('INSERT INTO tasks (id, status, result) VALUES (?, ?, ?)', (task_id, 'pending', f"任务已提交: change IP on {vm_name}"))
    db.commit()

    task_kwargs = {
        'task_id': task_id,
        'credential_dict': {k: g.azure_creds[k] for k in ['tenant_id', 'client_id', 'client_secret']},
        'subscription_id': g.azure_creds['subscription_id'],
        'rg_name': data.get('resource_group'),
        'vm_name': vm_name
    }
    _run_background_task(_change_ip_task, **task_kwargs)
    return jsonify({"message": f"正在为虚拟机 {vm_name} 申请新的IP地址...", "task_id": task_id})
    
def _change_ip_task(app, task_id, credential_dict, subscription_id, rg_name, vm_name):
    with app.app_context():
        db = sqlite3.connect(DATABASE)
        db.execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('running', f'正在为 {vm_name} 更换IP...', task_id)); db.commit()
        try:
            credential = ClientSecretCredential(**credential_dict)
            compute_client = ComputeManagementClient(credential, subscription_id)
            network_client = NetworkManagementClient(credential, subscription_id)
            vm = compute_client.virtual_machines.get(rg_name, vm_name)
            nic_id = vm.network_profile.network_interfaces[0].id
            nic_name = nic_id.split('/')[-1]
            nic = network_client.network_interfaces.get(rg_name, nic_name)
            ip_config = nic.ip_configurations[0]
            old_pip_id = ip_config.public_ip_address.id if ip_config.public_ip_address else None
            
            if old_pip_id:
                old_pip_name = old_pip_id.split('/')[-1]
                db.execute('UPDATE tasks SET result = ? WHERE id = ?', ('正在解绑旧IP...', task_id)); db.commit()
                ip_config.public_ip_address = None
                network_client.network_interfaces.begin_create_or_update(rg_name, nic_name, nic).result()
                db.execute('UPDATE tasks SET result = ? WHERE id = ?', ('正在删除旧IP...', task_id)); db.commit()
                network_client.public_ip_addresses.begin_delete(rg_name, old_pip_name).result()

            new_pip_name = f"pip-{vm_name}-{int(time.time())}"
            pip_params = {"location": vm.location, "sku": {"name": "Standard"}, "public_ip_allocation_method": "Static"}
            db.execute('UPDATE tasks SET result = ? WHERE id = ?', ('正在创建新IP...', task_id)); db.commit()
            new_pip = network_client.public_ip_addresses.begin_create_or_update(rg_name, new_pip_name, pip_params).result()
            
            db.execute('UPDATE tasks SET result = ? WHERE id = ?', ('正在绑定新IP...', task_id)); db.commit()
            ip_config.public_ip_address = new_pip
            network_client.network_interfaces.begin_create_or_update(rg_name, nic_name, nic).result()
            
            db.execute('UPDATE tasks SET result = ? WHERE id = ?', ('正在检查网络安全组(NSG)...', task_id)); db.commit()
            if nic.network_security_group:
                nsg_id = nic.network_security_group.id
                nsg_name = nsg_id.split('/')[-1]
                nsg = network_client.network_security_groups.get(rg_name, nsg_name)
                
                ssh_rule_exists = any(
                    rule.destination_port_range == '22' and rule.protocol.lower() == 'tcp' and rule.access.lower() == 'allow' and rule.direction.lower() == 'inbound'
                    for rule in nsg.security_rules
                )

                if not ssh_rule_exists:
                    db.execute('UPDATE tasks SET result = ? WHERE id = ?', ('未找到SSH规则，正在创建...', task_id)); db.commit()
                    highest_priority = max([rule.priority for rule in nsg.security_rules] + [999])
                    
                    rule_params = {
                        'name': 'AllowSSH_Auto_Panel', 'protocol': 'Tcp',
                        'source_address_prefix': 'Internet', 'source_port_range': '*',
                        'destination_address_prefix': '*', 'destination_port_range': '22',
                        'access': 'Allow', 'direction': 'Inbound', 'priority': highest_priority + 10
                    }
                    nsg.security_rules.append(rule_params)
                    network_client.network_security_groups.begin_create_or_update(rg_name, nsg_name, nsg).result()
                    db.execute('UPDATE tasks SET result = ? WHERE id = ?', ('SSH规则创建成功！', task_id)); db.commit()
                else:
                    db.execute('UPDATE tasks SET result = ? WHERE id = ?', ('检测到已存在SSH规则。', task_id)); db.commit()
            else:
                 logging.warning(f"网卡 {nic_name} 未关联任何NSG，无法自动添加SSH规则。")

            result_message = f"✅ IP更换成功！\n- 虚拟机: {vm_name}\n- 新IP地址: {new_pip.ip_address}\n- SSH(22)端口已确保开放。"
            db.execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('success', result_message, task_id)); db.commit()
        except Exception as e:
            error_message = f"❌ 更换IP失败 for {vm_name}: {str(e)}"
            db.execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', error_message, task_id)); db.commit()
            logging.error(error_message)
        finally:
            db.close()

def _create_vm_task(app, task_id, credential_dict, subscription_id, vm_name, rg_name, admin_password, data):
    with app.app_context():
        db = sqlite3.connect(DATABASE)
        db.execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('running', '正在创建资源组...', task_id))
        db.commit()
        try:
            logging.info(f"后台任务({task_id})开始：为 {rg_name} 创建VM...")
            credential = ClientSecretCredential(**credential_dict)
            compute_client = ComputeManagementClient(credential, subscription_id)
            network_client = NetworkManagementClient(credential, subscription_id)
            resource_client = ResourceManagementClient(credential, subscription_id)

            location = data.get('region')
            ip_type = data.get('ip_type')
            os_images = {
                "debian12": {"publisher": "Debian", "offer": "debian-12", "sku": "12-gen2", "version": "latest"},
                "debian11": {"publisher": "Debian", "offer": "debian-11", "sku": "11-gen2", "version": "latest"},
                "ubuntu22": {"publisher": "Canonical", "offer": "0001-com-ubuntu-server-jammy", "sku": "22_04-lts-gen2", "version": "latest"},
                "ubuntu20": {"publisher": "Canonical", "offer": "0001-com-ubuntu-server-focal", "sku": "20_04-lts-gen2", "version": "latest"},
            }
            image_reference = os_images.get(data.get('os_image'))
            admin_username = "azureuser"

            resource_client.resource_groups.create_or_update(rg_name, {"location": location})
            
            db.execute('UPDATE tasks SET result = ? WHERE id = ?', ('正在创建虚拟网络...', task_id)); db.commit()
            vnet_poller = network_client.virtual_networks.begin_create_or_update(rg_name, f"vnet-{vm_name}", {
                "location": location,
                "address_space": {"address_prefixes": ["10.0.0.0/16"]},
                "subnets": [{"name": "default", "address_prefix": "10.0.0.0/24"}]
            })
            subnet_id = vnet_poller.result().subnets[0].id

            db.execute('UPDATE tasks SET result = ? WHERE id = ?', ('正在创建公网IP...', task_id)); db.commit()
            ip_sku = {"name": "Basic"} if ip_type == "Dynamic" else {"name": "Standard"}
            pip_poller = network_client.public_ip_addresses.begin_create_or_update(rg_name, f"pip-{vm_name}", {
                "location": location, "sku": ip_sku, "public_ip_allocation_method": ip_type
            })
            public_ip_id = pip_poller.result().id
            
            # --- 核心修改：创建并配置包含所有规则的NSG ---
            nsg_name = f"nsg-{vm_name}"
            db.execute('UPDATE tasks SET result = ? WHERE id = ?', ('正在创建并配置网络安全组(NSG)...', task_id)); db.commit()
            nsg_params = {
                'location': location,
                'security_rules': [
                    {
                        'name': 'AllowSSH_Default',
                        'protocol': 'Tcp',
                        'source_address_prefix': 'Internet',
                        'source_port_range': '*',
                        'destination_address_prefix': '*',
                        'destination_port_range': '22',
                        'access': 'Allow',
                        'direction': 'Inbound',
                        'priority': 1000
                    },
                    {
                        'name': 'AllowAll_Inbound_DANGEROUS',
                        'protocol': '*',
                        'source_address_prefix': '*',
                        'source_port_range': '*',
                        'destination_address_prefix': '*',
                        'destination_port_range': '*',
                        'access': 'Allow',
                        'direction': 'Inbound',
                        'priority': 1010
                    },
                     {
                        'name': 'AllowAll_Outbound',
                        'protocol': '*',
                        'source_address_prefix': '*',
                        'source_port_range': '*',
                        'destination_address_prefix': '*',
                        'destination_port_range': '*',
                        'access': 'Allow',
                        'direction': 'Outbound',
                        'priority': 1000
                    }
                ]
            }
            nsg_poller = network_client.network_security_groups.begin_create_or_update(rg_name, nsg_name, nsg_params)
            nsg_id = nsg_poller.result().id
            
            db.execute('UPDATE tasks SET result = ? WHERE id = ?', ('正在创建网络接口并关联NSG...', task_id)); db.commit()
            nic_poller = network_client.network_interfaces.begin_create_or_update(rg_name, f"nic-{vm_name}", {
                "location": location,
                "ip_configurations": [{
                    "name": "ipconfig1",
                    "subnet": {"id": subnet_id},
                    "public_ip_address": {"id": public_ip_id}
                }],
                "network_security_group": {"id": nsg_id}
            })
            nic_id = nic_poller.result().id
            
            azure_params = {
                "location": location,
                "storage_profile": {
                    "image_reference": image_reference,
                    "os_disk": {"create_option": "FromImage", "disk_size_gb": data.get('disk_size')}
                },
                "hardware_profile": {"vm_size": data.get('vm_size')},
                "os_profile": {
                    "computer_name": vm_name,
                    "admin_username": admin_username,
                    "admin_password": admin_password
                },
                "network_profile": {"network_interfaces": [{"id": nic_id}]}
            }
            
            user_data_b64 = data.get('user_data')
            if user_data_b64:
                azure_params["os_profile"]["custom_data"] = user_data_b64
            
            db.execute('UPDATE tasks SET result = ? WHERE id = ?', ('正在创建虚拟机，此过程可能需要几分钟...', task_id)); db.commit()
            vm_poller = compute_client.virtual_machines.begin_create_or_update(rg_name, vm_name, azure_params)
            vm_poller.result()

            final_pip = network_client.public_ip_addresses.get(rg_name, f"pip-{vm_name}")
            success_message = f"🎉 虚拟机 {vm_name} 创建成功! \n- 公网 IP: {final_pip.ip_address}\n- 用户名: {admin_username}\n- 密  码: {admin_password}\n- 所有网络端口已自动开放"
            db.execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('success', success_message, task_id)); db.commit()
            logging.info(f"后台任务({task_id})成功")
        except Exception as e:
            user_friendly_reason = str(e)
            if isinstance(e, HttpResponseError) and hasattr(e, 'error') and e.error and hasattr(e.error, 'code') and e.error.code == "RequestDisallowedByPolicy":
                user_friendly_reason = "账号不支持在该区域创建实例或所选配置"
            
            error_message = f"❌ 虚拟机 {rg_name} 创建失败! \n    - 原因: {user_friendly_reason}"
            db.execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', error_message, task_id)); db.commit()
            logging.error(f"后台任务({task_id})失败: {str(e)}")
            try:
                resource_client = ResourceManagementClient(ClientSecretCredential(**credential_dict), subscription_id)
                resource_client.resource_groups.begin_delete(rg_name).wait()
                logging.info(f"已清理失败任务的资源组: {rg_name}")
            except Exception as cleanup_e:
                 logging.error(f"清理资源组 {rg_name} 失败: {cleanup_e}")
        finally:
            db.close()

@azure_bp.route('/api/create-vm', methods=['POST'])
@login_required
@azure_credentials_required
def create_vm():
    task_id = str(uuid.uuid4())
    db = get_db()
    db.execute('INSERT INTO tasks (id, status, result) VALUES (?, ?, ?)', (task_id, 'pending', '任务已加入队列...'))
    db.commit()
    data = request.json
    task_kwargs = {
        'task_id': task_id,
        'credential_dict': {k: g.azure_creds[k] for k in ['tenant_id', 'client_id', 'client_secret']},
        'subscription_id': g.azure_creds['subscription_id'],
        'vm_name': f"vm-{data.get('region').replace(' ','').lower()}-{int(time.time())}",
        'rg_name': f"rg-{data.get('region').replace(' ','').lower()}-{int(time.time())}", 
        'admin_password': generate_password(),
        'data': data
    }
    _run_background_task(_create_vm_task, **task_kwargs)
    return jsonify({ "message": f"创建请求已提交...", "task_id": task_id })

@azure_bp.route('/api/task_status/<task_id>')
@login_required
def task_status(task_id):
    task = query_db('SELECT * FROM tasks WHERE id = ?', [task_id], one=True)
    if task is None: return jsonify({'status': 'not_found'}), 404
    return jsonify({'status': task['status'], 'result': task['result']})
