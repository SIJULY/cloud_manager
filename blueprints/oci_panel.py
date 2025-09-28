import os, json, threading, string, random, base64, time, logging, uuid, sqlite3, datetime
from flask import Blueprint, render_template, jsonify, request, session, g, redirect, url_for
from functools import wraps
import oci
from oci.core.models import CreateVcnDetails, CreateSubnetDetails, CreateInternetGatewayDetails, UpdateRouteTableDetails, RouteRule, CreatePublicIpDetails, CreateIpv6Details, UpdateInstanceDetails, UpdateInstanceShapeConfigDetails
from oci.exceptions import ServiceError
from celery import Celery

# --- Blueprint Setup ---
oci_bp = Blueprint('oci', __name__, template_folder='../templates', static_folder='../static')

# --- Celery Setup ---
celery = Celery(oci_bp.import_name)

# --- Configuration ---
KEYS_FILE = "oci_profiles.json"
DATABASE = 'oci_tasks.db' # Renamed to avoid conflict

# --- Helpers & DB ---
def get_db():
    db = getattr(g, '_oci_database', None)
    if db is None:
        db = g._oci_database = sqlite3.connect(DATABASE, check_same_thread=False)
        db.row_factory = sqlite3.Row
    return db

def close_connection(exception):
    db = getattr(g, '_oci_database', None)
    if db is not None: db.close()

def init_db():
    db = sqlite3.connect(DATABASE, check_same_thread=False)
    db.cursor().executescript("CREATE TABLE tasks (id TEXT PRIMARY KEY, type TEXT, name TEXT, status TEXT NOT NULL, result TEXT, created_at TEXT, account_alias TEXT);")
    db.commit()
    db.close()
    logging.info("OCI database initialized.")

def query_db(query, args=(), one=False):
    db = sqlite3.connect(DATABASE); db.row_factory = sqlite3.Row; cur = db.execute(query, args)
    rv = cur.fetchall(); cur.close(); db.close()
    return (rv[0] if rv else None) if one else rv

def load_profiles():
    if not os.path.exists(KEYS_FILE): return {}
    try:
        with open(KEYS_FILE, 'r', encoding='utf-8') as f: 
            content = f.read()
            if not content: return {}
            return json.loads(content)
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"FATAL: Could not read or parse {KEYS_FILE}: {e}")
        return {}

def save_profiles(profiles):
    with open(KEYS_FILE, 'w', encoding='utf-8') as f: json.dump(profiles, f, indent=4, ensure_ascii=False)

def generate_oci_password(length=16):
    chars = string.ascii_letters + string.digits + "!@#$%^&*()_+=-`~[]{};:,.<>?"
    return ''.join(random.choice(chars) for i in range(length))

def get_oci_clients(profile_config):
    try:
        if 'key_content' in profile_config and 'key_file' not in profile_config:
            key_file_path = f"/tmp/{uuid.uuid4()}.pem"
            with open(key_file_path, 'w') as key_file:
                key_file.write(profile_config['key_content'])
            os.chmod(key_file_path, 0o600)
            
            config_for_sdk = profile_config.copy()
            config_for_sdk['key_file'] = key_file_path
        else:
            config_for_sdk = profile_config

        oci.config.validate_config(config_for_sdk)
        clients = { 
            "identity": oci.identity.IdentityClient(config_for_sdk), 
            "compute": oci.core.ComputeClient(config_for_sdk), 
            "vnet": oci.core.VirtualNetworkClient(config_for_sdk), 
            "bs": oci.core.BlockstorageClient(config_for_sdk) 
        }

        if 'key_content' in profile_config and 'key_file' not in profile_config:
            if os.path.exists(key_file_path):
                os.remove(key_file_path)

        return clients, None
    except Exception as e:
        return None, f"创建OCI客户端失败: {str(e)}"

def _ensure_subnet_in_profile(alias, vnet_client, tenancy_ocid):
    profiles = load_profiles()
    profile_config = profiles.get(alias, {})
    subnet_id = profile_config.get('default_subnet_ocid')

    if subnet_id:
        try:
            get_subnet_response = vnet_client.get_subnet(subnet_id)
            if get_subnet_response.data.lifecycle_state == 'AVAILABLE': return subnet_id
        except ServiceError as e:
            if e.status != 404: raise

    vcn_name = f"vcn-autocreated-{alias}-{random.randint(100, 999)}"
    vcn = vnet_client.create_vcn(CreateVcnDetails(cidr_block="10.0.0.0/16", display_name=vcn_name, compartment_id=tenancy_ocid)).data
    oci.waiter.wait_for_resource(vnet_client, vnet_client.get_vcn(vcn.id), 'lifecycle_state', 'AVAILABLE')
    
    ig_name = f"ig-autocreated-{alias}-{random.randint(100, 999)}"
    ig = vnet_client.create_internet_gateway(CreateInternetGatewayDetails(display_name=ig_name, compartment_id=tenancy_ocid, is_enabled=True, vcn_id=vcn.id)).data
    oci.waiter.wait_for_resource(vnet_client, vnet_client.get_internet_gateway(ig.id), 'lifecycle_state', 'AVAILABLE')

    route_table = vnet_client.get_route_table(vcn.default_route_table_id).data
    route_table.route_rules.append(RouteRule(destination="0.0.0.0/0", network_entity_id=ig.id))
    vnet_client.update_route_table(vcn.default_route_table_id, UpdateRouteTableDetails(route_rules=route_table.route_rules))

    subnet_name = f"subnet-autocreated-{alias}-{random.randint(100, 999)}"
    subnet = vnet_client.create_subnet(CreateSubnetDetails(compartment_id=tenancy_ocid, vcn_id=vcn.id, cidr_block="10.0.1.0/24", display_name=subnet_name)).data
    oci.waiter.wait_for_resource(vnet_client, vnet_client.get_subnet(subnet.id), 'lifecycle_state', 'AVAILABLE')

    profiles[alias]['default_subnet_ocid'] = subnet.id
    save_profiles(profiles)
    return subnet.id

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_logged_in" not in session: return jsonify({"error": "用户未登录"}), 401
        return f(*args, **kwargs)
    return decorated_function

def oci_clients_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'oci_profile_alias' not in session: return jsonify({"error": "请先选择一个OCI账号"}), 403
        alias = session['oci_profile_alias']
        profile_config = load_profiles().get(alias)
        if not profile_config: return jsonify({"error": f"账号 '{alias}' 未找到"}), 404
        clients, error = get_oci_clients(profile_config)
        if error: return jsonify({"error": error}), 500
        g.oci_clients = clients
        g.oci_config = profile_config
        return f(*args, **kwargs)
    return decorated_function

# --- Routes ---
@oci_bp.route("/")
@login_required
def oci_index():
    return render_template("oci.html")

@oci_bp.route("/api/profiles", methods=["GET", "POST"])
@login_required
def manage_profiles():
    profiles = load_profiles()
    if request.method == "GET": return jsonify(list(profiles.keys()))
    data = request.json
    alias, profile_data = data.get("alias"), data.get("profile_data")
    if not alias or not profile_data: return jsonify({"error": "别名和配置数据不能为空"}), 400
    profiles[alias] = profile_data
    save_profiles(profiles)
    return jsonify({"success": True, "alias": alias})

@oci_bp.route("/api/profiles/<alias>", methods=["GET", "DELETE"])
@login_required
def handle_single_profile(alias):
    profiles = load_profiles()
    if alias not in profiles: return jsonify({"error": "账号未找到"}), 404
    if request.method == "GET": return jsonify(profiles[alias])
    if request.method == "DELETE":
        del profiles[alias]
        save_profiles(profiles)
        if session.get('oci_profile_alias') == alias: session.pop('oci_profile_alias', None)
        return jsonify({"success": True})

@oci_bp.route('/api/tasks/snatching/running', methods=['GET'])
@login_required
def get_running_snatching_tasks():
    tasks = query_db("SELECT id, name, result, created_at, account_alias FROM tasks WHERE type = 'snatch' AND status = 'running' ORDER BY created_at DESC")
    return jsonify([dict(task) for task in tasks])

@oci_bp.route('/api/tasks/snatching/completed', methods=['GET'])
@login_required
def get_completed_snatching_tasks():
    tasks = query_db("SELECT id, name, status, result, created_at, account_alias FROM tasks WHERE type = 'snatch' AND (status = 'success' OR status = 'failure') ORDER BY created_at DESC LIMIT 50")
    return jsonify([dict(task) for task in tasks])

@oci_bp.route('/api/tasks/<task_id>', methods=['DELETE'])
@login_required
def delete_task_record(task_id):
    task = query_db("SELECT status FROM tasks WHERE id = ?", [task_id], one=True)
    if task and task['status'] in ['success', 'failure']:
        db = get_db()
        db.execute('DELETE FROM tasks WHERE id = ?', (task_id,)); db.commit()
        return jsonify({"success": True, "message": "任务记录已删除。"})
    return jsonify({"error": "只能删除已完成或失败的任务记录。"}), 400

@oci_bp.route('/api/tasks/<task_id>/stop', methods=['POST'])
@login_required
def stop_task(task_id):
    celery.control.revoke(task_id, terminate=True, signal='SIGKILL')
    db = get_db()
    db.execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', '任务已被用户手动停止。', task_id)); db.commit()
    return jsonify({"success": True, "message": f"停止任务 {task_id} 的请求已发送。"})

@oci_bp.route("/api/session", methods=["POST", "GET", "DELETE"])
@login_required
def oci_session():
    if request.method == "POST":
        alias = request.json.get("alias")
        profiles = load_profiles()
        if not alias or alias not in profiles: return jsonify({"error": "无效的账号别名"}), 400
        session['oci_profile_alias'] = alias
        profile_config = profiles.get(alias)
        _, error = get_oci_clients(profile_config)
        if error: return jsonify({"error": f"连接验证失败: {error}"}), 400
        can_create_and_snatch = bool(profile_config.get('default_ssh_public_key'))
        return jsonify({"success": True, "alias": alias, "can_create": can_create_and_snatch, "can_snatch": can_create_and_snatch})
    if request.method == "GET":
        alias = session.get('oci_profile_alias')
        if alias:
            profile_config = load_profiles().get(alias, {})
            can_create = bool(profile_config.get('default_ssh_public_key'))
            return jsonify({"logged_in": True, "alias": alias, "can_create": can_create, "can_snatch": can_create})
        return jsonify({"logged_in": False})
    if request.method == "DELETE":
        session.pop('oci_profile_alias', None); return jsonify({"success": True})

@oci_bp.route('/api/instances')
@login_required
@oci_clients_required
def get_instances():
    compute_client, vnet_client, bs_client = g.oci_clients['compute'], g.oci_clients['vnet'], g.oci_clients['bs']
    compartment_id = g.oci_config['tenancy']
    instances = oci.pagination.list_call_get_all_results(compute_client.list_instances, compartment_id=compartment_id).data
    details = []
    for inst in instances:
        data = {
            "display_name": inst.display_name, "id": inst.id, "lifecycle_state": inst.lifecycle_state,
            "shape": inst.shape, "time_created": inst.time_created.isoformat() if inst.time_created else 'N/A',
            "ocpus": getattr(inst.shape_config, 'ocpus', 'N/A'),
            "memory_in_gbs": getattr(inst.shape_config, 'memory_in_gbs', 'N/A'),
            "public_ip": "无", "ipv6_address": "无", "vnic_id": None, "subnet_id": None
        }
        vnics = oci.pagination.list_call_get_all_results(compute_client.list_vnic_attachments, compartment_id, instance_id=inst.id).data
        if vnics:
            vnic = vnet_client.get_vnic(vnics[0].vnic_id).data
            data.update({"public_ip": vnic.public_ip or "无", "vnic_id": vnic.id, "subnet_id": vnic.subnet_id})
            ipv6s = vnet_client.list_ipv6s(vnic_id=vnic.id).data
            if ipv6s: data["ipv6_address"] = ipv6s[0].ip_address
        
        bvs = oci.pagination.list_call_get_all_results(compute_client.list_boot_volume_attachments, inst.availability_domain, compartment_id, instance_id=inst.id).data
        if bvs: data["boot_volume_size_gb"] = f"{int(bs_client.get_boot_volume(bvs[0].boot_volume_id).data.size_in_gbs)} GB"
        
        details.append(data)
    return jsonify(details)

@oci_bp.route('/api/instance-action', methods=['POST'])
@login_required
@oci_clients_required
def instance_action():
    data = request.json
    alias = session.get('oci_profile_alias', 'N/A')
    task_id = str(uuid.uuid4()); db = get_db()
    db.execute('INSERT INTO tasks (id, type, name, status, created_at, account_alias) VALUES (?, ?, ?, ?, ?, ?)',
               (task_id, 'action', f"{data.get('action')} on {data.get('instance_name', 'N/A')}", 'pending', datetime.datetime.utcnow().isoformat(), alias))
    db.commit()
    _instance_action_task.delay(task_id, g.oci_config, data.get('action'), data.get('instance_id'), data)
    return jsonify({"message": f"'{data.get('action')}' 请求已提交...", "task_id": task_id})

@oci_bp.route('/api/create-instance', methods=['POST'])
@login_required
@oci_clients_required
def create_instance():
    data = request.json
    alias = session.get('oci_profile_alias', 'N/A')
    task_id = str(uuid.uuid4()); db = get_db()
    db.execute('INSERT INTO tasks (id, type, name, status, created_at, account_alias) VALUES (?, ?, ?, ?, ?, ?)',
               (task_id, 'create', data.get('display_name_prefix', 'N/A'), 'pending', datetime.datetime.utcnow().isoformat(), alias))
    db.commit()
    _create_instance_task.delay(task_id, g.oci_config, alias, data)
    return jsonify({"message": "创建实例请求已提交...", "task_id": task_id})

@oci_bp.route('/api/snatch-instance', methods=['POST'])
@login_required
@oci_clients_required
def snatch_instance():
    data = request.json
    alias = session.get('oci_profile_alias', 'N/A')
    task_id = str(uuid.uuid4()); db = get_db()
    db.execute('INSERT INTO tasks (id, type, name, status, created_at, account_alias) VALUES (?, ?, ?, ?, ?, ?)',
               (task_id, 'snatch', data.get('display_name_prefix', 'N/A'), 'pending', datetime.datetime.utcnow().isoformat(), alias))
    db.commit()
    _snatch_instance_task.delay(task_id, g.oci_config, alias, data)
    return jsonify({"message": "抢占实例任务已提交...", "task_id": task_id})

@oci_bp.route('/api/task_status/<task_id>')
@login_required
def task_status(task_id):
    task = query_db('SELECT * FROM tasks WHERE id = ?', [task_id], one=True)
    return jsonify({'status': 'not_found' if not task else task['status'], 'result': '' if not task else task['result']})

# --- Celery Tasks ---
def _db_execute(query, params=()):
    db = sqlite3.connect(DATABASE); db.execute(query, params); db.commit(); db.close()

@celery.task
def _instance_action_task(task_id, profile_config, action, instance_id, data):
    _db_execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('running', '正在执行操作...', task_id))
    try:
        clients, error = get_oci_clients(profile_config)
        if error: raise Exception(error)
        compute_client, vnet_client = clients['compute'], clients['vnet']
        action_upper = action.upper()
        if action_upper in ["START", "STOP", "SOFTRESET"]:
            compute_client.instance_action(instance_id, action_upper)
            result_message = f"实例 {action_upper} 命令已发送。"
        elif action_upper == "TERMINATE":
            compute_client.terminate_instance(instance_id, preserve_boot_volume=data.get('preserve_boot_volume', False))
            result_message = "实例终止命令已发送。"
        elif action_upper == "CHANGEIP":
            vnic_id = data.get('vnic_id')
            private_ips = oci.pagination.list_call_get_all_results(vnet_client.list_private_ips, vnic_id=vnic_id).data
            primary_private_ip = next((p for p in private_ips if p.is_primary), None)
            try:
                pub_ip_details = oci.core.models.GetPublicIpByPrivateIpIdDetails(private_ip_id=primary_private_ip.id)
                existing_pub_ip = vnet_client.get_public_ip_by_private_ip_id(pub_ip_details).data
                if existing_pub_ip.lifetime == "EPHEMERAL":
                    vnet_client.delete_public_ip(existing_pub_ip.id); time.sleep(5)
            except ServiceError as e:
                if e.status != 404: raise
            new_pub_ip = vnet_client.create_public_ip(CreatePublicIpDetails(compartment_id=profile_config['tenancy'], lifetime="EPHEMERAL", private_ip_id=primary_private_ip.id)).data
            result_message = f"更换IP请求成功，新IP: {new_pub_ip.ip_address}"
        elif action_upper == "ASSIGNIPV6":
            subnet = vnet_client.get_subnet(data.get('subnet_id')).data
            if not subnet.ipv6_cidr_block: raise Exception("子网未配置IPv6")
            new_ipv6 = vnet_client.create_ipv6(CreateIpv6Details(vnic_id=data.get('vnic_id'))).data
            result_message = f"已成功请求IPv6地址: {new_ipv6.ip_address}"
        
        _db_execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('success', result_message, task_id))
    except Exception as e:
        _db_execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', f"操作失败: {e}", task_id))

def get_user_data(root_password):
    return base64.b64encode(f"""#cloud-config
chpasswd:
  list: |
    root:{root_password}
  expire: False
runcmd:
  - sed -i 's/^#?PermitRootLogin.*/PermitRootLogin yes/g' /etc/ssh/sshd_config
  - sed -i 's/^#?PasswordAuthentication.*/PasswordAuthentication yes/g' /etc/ssh/sshd_config
  - systemctl restart sshd || service sshd restart || service ssh restart
""".encode('utf-8')).decode('utf-8')

@celery.task
def _create_instance_task(task_id, profile_config, alias, details):
    try:
        clients, error = get_oci_clients(profile_config)
        if error: raise Exception(error)
        compute_client, identity_client, vnet_client = clients['compute'], clients['identity'], clients['vnet']
        tenancy_ocid = profile_config.get('tenancy')
        ssh_key = profile_config.get('default_ssh_public_key')
        if not ssh_key: raise Exception("账号配置缺少默认SSH公钥")

        subnet_id = _ensure_subnet_in_profile(alias, vnet_client, tenancy_ocid)
        
        ad_name = identity_client.list_availability_domains(tenancy_ocid).data[0].name
        os_name, os_version = details['os_name_version'].split('-')
        shape = details['shape']
        images = oci.pagination.list_call_get_all_results(compute_client.list_images, tenancy_ocid, operating_system=os_name, operating_system_version=os_version, shape=shape, sort_by="TIMECREATED", sort_order="DESC").data
        if not images: raise Exception(f"未找到兼容的镜像 for {os_name} {os_version}")

        root_password = generate_oci_password()
        user_data_encoded = get_user_data(root_password)

        created = []
        for i in range(details.get('instance_count', 1)):
            name = f"{details.get('display_name_prefix', 'Instance')}-{i+1}" if details.get('instance_count', 1) > 1 else details.get('display_name_prefix', 'Instance')
            launch_details = oci.core.models.LaunchInstanceDetails(
                compartment_id=tenancy_ocid, availability_domain=ad_name, shape=shape, display_name=name,
                create_vnic_details=oci.core.models.CreateVnicDetails(subnet_id=subnet_id, assign_public_ip=True),
                metadata={"ssh_authorized_keys": ssh_key, "user_data": user_data_encoded},
                source_details=oci.core.models.InstanceSourceViaImageDetails(image_id=images[0].id, boot_volume_size_in_gbs=details['boot_volume_size']),
                shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=details.get('ocpus'), memory_in_gbs=details.get('memory_in_gbs')) if "Flex" in shape else None
            )
            compute_client.launch_instance(launch_details)
            created.append(name)
            if i < details.get('instance_count', 1) - 1: time.sleep(3)
        
        msg = f"🎉 {len(created)}个实例创建成功!\n- 实例名: {', '.join(created)}\n- Root 密码: {root_password}"
        _db_execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('success', msg, task_id))
    except Exception as e:
        msg = f"❌ 实例创建失败! \n- 原因: {e}"
        _db_execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', msg, task_id))

@celery.task
def _snatch_instance_task(task_id, profile_config, alias, details):
    try:
        clients, error = get_oci_clients(profile_config)
        if error: raise Exception(error)
        compute_client, identity_client, vnet_client = clients['compute'], clients['identity'], clients['vnet']
        tenancy_ocid = profile_config.get('tenancy')
        ssh_key = profile_config.get('default_ssh_public_key')
        if not ssh_key: raise Exception("账号配置缺少默认SSH公钥")

        subnet_id = _ensure_subnet_in_profile(alias, vnet_client, tenancy_ocid)
        ad_name = details.get('availabilityDomain') or identity_client.list_availability_domains(tenancy_ocid).data[0].name
        os_name, os_version = details['os_name_version'].split('-')
        shape = details['shape']
        images = oci.pagination.list_call_get_all_results(compute_client.list_images, tenancy_ocid, operating_system=os_name, operating_system_version=os_version, shape=shape, sort_by="TIMECREATED", sort_order="DESC").data
        if not images: raise Exception(f"未找到兼容的镜像 for {os_name} {os_version}")
        
        root_password = generate_oci_password()
        user_data_encoded = get_user_data(root_password)

        launch_details = oci.core.models.LaunchInstanceDetails(
            compartment_id=tenancy_ocid, availability_domain=ad_name, shape=shape,
            display_name=details.get('display_name_prefix', 'snatch-instance'),
            create_vnic_details=oci.core.models.CreateVnicDetails(subnet_id=subnet_id, assign_public_ip=True),
            metadata={"ssh_authorized_keys": ssh_key, "user_data": user_data_encoded},
            source_details=oci.core.models.InstanceSourceViaImageDetails(image_id=images[0].id, boot_volume_size_in_gbs=details['boot_volume_size']),
            shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=details.get('ocpus'), memory_in_gbs=details.get('memory_in_gbs')) if "Flex" in shape else None
        )
    except Exception as e:
        _db_execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', f"❌ 抢占任务准备阶段失败! \n- 原因: {e}", task_id))
        return

    count = 0
    while True:
        count += 1
        delay = random.randint(details.get('min_delay', 30), details.get('max_delay', 90))
        task = query_db('SELECT status FROM tasks WHERE id = ?', [task_id], one=True)
        if not task or task['status'] == 'failure': return "任务已被用户手动停止。"
        
        try:
            _db_execute('UPDATE tasks SET result = ? WHERE id = ?', (f"第 {count} 次尝试创建实例...", task_id))
            instance = compute_client.launch_instance(launch_details).data
            msg = f"🎉 抢占成功 (第 {count} 次尝试)!\n- 实例名: {instance.display_name}\n- Root 密码: {root_password}"
            _db_execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('success', msg, task_id))
            return
        except ServiceError as e:
            if e.status == 500 and ("OutOfCapacity" in e.code or "Out of host capacity" in e.message):
                msg = f"第 {count} 次尝试失败：资源不足。将在 {delay} 秒后重试..."
            else:
                msg = f"第 {count} 次尝试失败：API错误 ({e.code})。将在 {delay} 秒后重试..."
            _db_execute('UPDATE tasks SET result = ? WHERE id = ?', (msg, task_id))
            time.sleep(delay)
        except Exception as e:
            msg = f"第 {count} 次尝试失败：未知错误。将在 {delay} 秒后重试..."
            _db_execute('UPDATE tasks SET result = ? WHERE id = ?', (msg, task_id))
            time.sleep(delay)
