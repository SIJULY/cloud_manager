import os, json, threading, string, random, base64, time, logging, uuid, sqlite3, datetime
from flask import Blueprint, render_template, jsonify, request, session, g, redirect, url_for
from functools import wraps
import oci
from oci.core.models import (CreateVcnDetails, CreateSubnetDetails, CreateInternetGatewayDetails, 
                             UpdateRouteTableDetails, RouteRule, CreatePublicIpDetails, CreateIpv6Details,
                             LaunchInstanceDetails, CreateVnicDetails, InstanceSourceViaImageDetails,
                             LaunchInstanceShapeConfigDetails)
from oci.exceptions import ServiceError
from celery import Celery

# --- Blueprint Setup ---
oci_bp = Blueprint('oci', __name__, template_folder='../templates', static_folder='../static')

# --- Celery Setup ---
celery = Celery(oci_bp.import_name)

# --- Configuration ---
KEYS_FILE = "oci_profiles.json"
DATABASE = 'oci_tasks.db'

# --- 数据库核心辅助函数 (已为并发优化) ---
def get_db_connection():
    """创建一个启用WAL模式并设置超时的数据库连接"""
    conn = sqlite3.connect(DATABASE, timeout=10) # 10秒超时
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;") # 启用WAL模式以提高并发性
    return conn

def get_db():
    """获取与Flask请求上下文绑定的数据库连接"""
    db = getattr(g, '_oci_database', None)
    if db is None:
        db = g._oci_database = get_db_connection()
    return db

@oci_bp.teardown_request
def close_connection(exception):
    db = getattr(g, '_oci_database', None)
    if db is not None:
        db.close()

def init_db():
    if not os.path.exists(DATABASE):
        db = get_db_connection()
        db.cursor().executescript("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY, type TEXT, name TEXT, status TEXT NOT NULL, 
            result TEXT, created_at TEXT, account_alias TEXT
        );
        """)
        db.commit()
        db.close()
        logging.info("OCI database has been initialized with WAL mode.")

def query_db(query, args=(), one=False):
    db = get_db_connection()
    cur = db.execute(query, args)
    rv = cur.fetchall()
    cur.close()
    db.close()
    return (rv[0] if rv else None) if one else rv

# --- 核心辅助函数 ---
def load_profiles():
    if not os.path.exists(KEYS_FILE): return {}
    try:
        with open(KEYS_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            return json.loads(content) if content else {}
    except (IOError, json.JSONDecodeError): return {}

def save_profiles(profiles):
    with open(KEYS_FILE, 'w', encoding='utf-8') as f: json.dump(profiles, f, indent=4, ensure_ascii=False)

def generate_oci_password(length=16):
    """生成一个不含特殊字符的纯字母数字随机密码。"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def get_oci_clients(profile_config):
    key_file_path = None
    try:
        config_for_sdk = profile_config.copy()
        if 'key_content' in profile_config:
            key_file_path = f"/tmp/{uuid.uuid4()}.pem"
            with open(key_file_path, 'w') as key_file: key_file.write(profile_config['key_content'])
            os.chmod(key_file_path, 0o600)
            config_for_sdk['key_file'] = key_file_path
        oci.config.validate_config(config_for_sdk)
        return { "identity": oci.identity.IdentityClient(config_for_sdk), "compute": oci.core.ComputeClient(config_for_sdk), "vnet": oci.core.VirtualNetworkClient(config_for_sdk), "bs": oci.core.BlockstorageClient(config_for_sdk) }, None
    except Exception as e:
        return None, f"创建OCI客户端失败: {e}"
    finally:
        if key_file_path and os.path.exists(key_file_path): os.remove(key_file_path)

def _ensure_subnet_in_profile(alias, vnet_client, tenancy_ocid):
    profiles = load_profiles()
    profile_config = profiles.get(alias, {})
    subnet_id = profile_config.get('default_subnet_ocid')
    if subnet_id:
        try:
            if vnet_client.get_subnet(subnet_id).data.lifecycle_state == 'AVAILABLE':
                logging.info(f"Using existing subnet {subnet_id} for {alias}")
                return subnet_id
        except ServiceError as e:
            if e.status != 404: raise
            logging.warning(f"Subnet {subnet_id} not found, creating a new one.")
    
    logging.info(f"Creating network resources for {alias}...")
    vcn_name = f"vcn-autocreated-{alias}-{random.randint(100, 999)}"
    vcn_details = CreateVcnDetails(cidr_block="10.0.0.0/16", display_name=vcn_name, compartment_id=tenancy_ocid)
    vcn = vnet_client.create_vcn(vcn_details).data
    oci.wait_until(vnet_client, vnet_client.get_vcn(vcn.id), 'lifecycle_state', 'AVAILABLE')
    
    ig_name = f"ig-autocreated-{alias}-{random.randint(100, 999)}"
    ig_details = CreateInternetGatewayDetails(display_name=ig_name, compartment_id=tenancy_ocid, is_enabled=True, vcn_id=vcn.id)
    ig = vnet_client.create_internet_gateway(ig_details).data
    oci.wait_until(vnet_client, vnet_client.get_internet_gateway(ig.id), 'lifecycle_state', 'AVAILABLE')
    
    route_table_id = vcn.default_route_table_id
    rt_rules = vnet_client.get_route_table(route_table_id).data.route_rules
    rt_rules.append(RouteRule(destination="0.0.0.0/0", network_entity_id=ig.id))
    vnet_client.update_route_table(route_table_id, UpdateRouteTableDetails(route_rules=rt_rules))
    
    subnet_name = f"subnet-autocreated-{alias}-{random.randint(100, 999)}"
    subnet_details = CreateSubnetDetails(compartment_id=tenancy_ocid, vcn_id=vcn.id, cidr_block="10.0.1.0/24", display_name=subnet_name)
    subnet = vnet_client.create_subnet(subnet_details).data
    oci.wait_until(vnet_client, vnet_client.get_subnet(subnet.id), 'lifecycle_state', 'AVAILABLE')
    
    profiles[alias]['default_subnet_ocid'] = subnet.id
    save_profiles(profiles)
    logging.info(f"New subnet {subnet.id} created and saved for {alias}")
    return subnet.id

def get_user_data(password):
    """为 cloud-init 生成用户数据，用于设置 ubuntu 用户的密码，并确保密码登录可用。"""
    script = f"""#cloud-config
chpasswd:
  expire: False
  list:
    - ubuntu:{password}
runcmd:
  # 1. 修改主配置文件，确保密码登录为 yes (作为备用)
  - sed -i 's/^#?PasswordAuthentication.*/PasswordAuthentication yes/g' /etc/ssh/sshd_config
  # 2. (关键) 检查并修改云镜像的默认配置文件，将 no 改为 yes，这是解决问题的核心
  - '[ -f /etc/ssh/sshd_config.d/60-cloudimg-settings.conf ] && sed -i "s/PasswordAuthentication no/PasswordAuthentication yes/g" /etc/ssh/sshd_config.d/60-cloudimg-settings.conf'
  # 3. 禁用 root 密码登录 (安全设置)
  - sed -i 's/^#?PermitRootLogin.*/PermitRootLogin prohibit-password/g' /etc/ssh/sshd_config
  # 4. 重启 sshd 服务使所有配置生效
  - systemctl restart sshd || service sshd restart || service ssh restart
"""
    return base64.b64encode(script.encode('utf-8')).decode('utf-8')

# --- Decorators ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_logged_in" not in session:
            if request.path.startswith('/oci/api/'):
                return jsonify({"error": "用户未登录"}), 401
            return redirect(url_for('login'))
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

# --- API Routes ---
@oci_bp.route("/api/profiles", methods=["GET", "POST"])
@login_required
def manage_profiles():
    try:
        profiles = load_profiles()
        if request.method == "GET": 
            return jsonify(list(profiles.keys()))
        
        if request.method == "POST":
            data = request.json
            alias = data.get('alias')
            new_profile_data = data.get('profile_data', {})

            if not alias or not new_profile_data:
                return jsonify({"error": "Missing alias or profile_data"}), 400

            # 检查是更新还是新建
            if alias in profiles:
                # 更新：将新数据合并到现有数据中
                profiles[alias].update(new_profile_data)
            else:
                # 新建：直接赋值
                profiles[alias] = new_profile_data
            
            save_profiles(profiles)
            return jsonify({"success": True, "alias": alias})

    except Exception as e: 
        return jsonify({"error": str(e)}), 500

@oci_bp.route("/api/profiles/<alias>", methods=["GET", "DELETE"])
@login_required
def handle_single_profile(alias):
    try:
        profiles = load_profiles()
        if alias not in profiles: return jsonify({"error": "账号未找到"}), 404
        if request.method == "GET": return jsonify(profiles[alias])
        if request.method == "DELETE":
            del profiles[alias]
            save_profiles(profiles)
            if session.get('oci_profile_alias') == alias: session.pop('oci_profile_alias', None)
            return jsonify({"success": True})
    except Exception as e: return jsonify({"error": str(e)}), 500

@oci_bp.route('/api/tasks/snatching/running', methods=['GET'])
@login_required
def get_running_snatching_tasks():
    try:
        tasks = query_db("SELECT id, name, result, created_at, account_alias FROM tasks WHERE type = 'snatch' AND status = 'running' ORDER BY created_at DESC")
        return jsonify([dict(task) for task in tasks])
    except Exception as e: return jsonify({"error": str(e)}), 500

@oci_bp.route('/api/tasks/snatching/completed', methods=['GET'])
@login_required
def get_completed_snatching_tasks():
    try:
        tasks = query_db("SELECT id, name, status, result, created_at, account_alias FROM tasks WHERE type = 'snatch' AND (status = 'success' OR status = 'failure') ORDER BY created_at DESC LIMIT 50")
        return jsonify([dict(task) for task in tasks])
    except Exception as e: return jsonify({"error": str(e)}), 500

@oci_bp.route('/api/tasks/<task_id>', methods=['DELETE'])
@login_required
def delete_task_record(task_id):
    try:
        db = get_db()
        task = db.execute("SELECT status FROM tasks WHERE id = ?", [task_id]).fetchone()
        if task and task['status'] in ['success', 'failure']:
            db.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
            db.commit()
            return jsonify({"success": True, "message": "任务记录已删除。"})
        return jsonify({"error": "只能删除已完成或失败的任务记录。"}), 400
    except Exception as e: return jsonify({"error": str(e)}), 500

@oci_bp.route('/api/tasks/<task_id>/stop', methods=['POST'])
@login_required
def stop_task(task_id):
    try:
        celery.control.revoke(task_id, terminate=True, signal='SIGKILL')
        db = get_db()
        db.execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', '任务已被用户手动停止。', task_id))
        db.commit()
        return jsonify({"success": True, "message": f"停止任务 {task_id} 的请求已发送。"})
    except Exception as e: return jsonify({"error": str(e)}), 500

@oci_bp.route("/api/session", methods=["POST", "GET", "DELETE"])
@login_required
def oci_session_route():
    try:
        if request.method == "POST":
            alias = request.json.get("alias")
            profiles = load_profiles()
            if not alias or alias not in profiles: return jsonify({"error": "无效的账号别名"}), 400
            session['oci_profile_alias'] = alias
            _, error = get_oci_clients(profiles.get(alias))
            if error: return jsonify({"error": f"连接验证失败: {error}"}), 400
            can_create = bool(profiles.get(alias, {}).get('default_ssh_public_key'))
            return jsonify({"success": True, "alias": alias, "can_create": can_create, "can_snatch": can_create})
        if request.method == "GET":
            alias = session.get('oci_profile_alias')
            if alias:
                can_create = bool(load_profiles().get(alias, {}).get('default_ssh_public_key'))
                return jsonify({"logged_in": True, "alias": alias, "can_create": can_create, "can_snatch": can_create})
            return jsonify({"logged_in": False})
        if request.method == "DELETE":
            session.pop('oci_profile_alias', None)
            return jsonify({"success": True})
    except Exception as e: return jsonify({"error": str(e)}), 500

@oci_bp.route('/api/instances')
@login_required
@oci_clients_required
def get_instances():
    try:
        compute_client, vnet_client, bs_client = g.oci_clients['compute'], g.oci_clients['vnet'], g.oci_clients['bs']
        compartment_id = g.oci_config['tenancy']
        
        instances = oci.pagination.list_call_get_all_results(compute_client.list_instances, compartment_id=compartment_id).data
        
        instance_details_list = []
        for instance in instances:
            data = {
                "display_name": instance.display_name, 
                "id": instance.id, 
                "lifecycle_state": instance.lifecycle_state, 
                "shape": instance.shape, 
                "time_created": instance.time_created.isoformat() if instance.time_created else None,
                "ocpus": getattr(instance.shape_config, 'ocpus', 'N/A'), 
                "memory_in_gbs": getattr(instance.shape_config, 'memory_in_gbs', 'N/A'),
                "public_ip": "无", 
                "ipv6_address": "无", 
                "boot_volume_size_gb": "N/A", 
                "vnic_id": None, 
                "subnet_id": None
            }

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

            except ServiceError as se:
                if se.status == 404:
                    logging.warning(f"Could not fetch details for instance {instance.display_name} ({instance.id}), it might have been terminated. Error: {se.message}")
                    data['public_ip'] = "资源已删除"
                else:
                    logging.error(f"OCI ServiceError for instance {instance.display_name}: {se}")
            except Exception as ex:
                logging.error(f"Generic exception while fetching details for instance {instance.display_name}: {ex}")

            instance_details_list.append(data)
            
        return jsonify(instance_details_list)
    except Exception as e:
        return jsonify({"error": f"获取实例列表失败: {e}"}), 500

def _create_task_entry(task_type, task_name):
    db = get_db()
    task_id = str(uuid.uuid4())
    alias = session.get('oci_profile_alias', 'N/A')
    db.execute('INSERT INTO tasks (id, type, name, status, result, created_at, account_alias) VALUES (?, ?, ?, ?, ?, ?, ?)',
               (task_id, task_type, task_name, 'pending', '', datetime.datetime.utcnow().isoformat(), alias))
    db.commit()
    return task_id

@oci_bp.route('/api/instance-action', methods=['POST'])
@login_required
@oci_clients_required
def instance_action():
    try:
        data = request.json
        action, instance_id = data.get('action'), data.get('instance_id')
        if not action or not instance_id: return jsonify({"error": "缺少 action 或 instance_id"}), 400
        task_name = f"{action} on {data.get('instance_name', instance_id[-12:])}"
        task_id = _create_task_entry('action', task_name)
        _instance_action_task.delay(task_id, g.oci_config, action, instance_id, data)
        return jsonify({"message": f"'{action}' 请求已提交...", "task_id": task_id})
    except Exception as e: return jsonify({"error": f"提交实例操作失败: {e}"}), 500

@oci_bp.route('/api/create-instance', methods=['POST'])
@login_required
@oci_clients_required
def create_instance():
    try:
        data = request.json
        task_id = _create_task_entry('create', data.get('display_name_prefix', 'N/A'))
        _create_instance_task.delay(task_id, g.oci_config, session['oci_profile_alias'], data)
        return jsonify({"message": "创建实例请求已提交...", "task_id": task_id})
    except Exception as e: return jsonify({"error": f"提交创建实例任务失败: {e}"}), 500

@oci_bp.route('/api/snatch-instance', methods=['POST'])
@login_required
@oci_clients_required
def snatch_instance():
    try:
        data = request.json
        task_id = _create_task_entry('snatch', data.get('display_name_prefix', 'N/A'))
        _snatch_instance_task.delay(task_id, g.oci_config, session['oci_profile_alias'], data)
        return jsonify({"message": "抢占实例任务已提交...", "task_id": task_id})
    except Exception as e: return jsonify({"error": f"提交抢占任务失败: {e}"}), 500

@oci_bp.route('/api/task_status/<task_id>')
@login_required
def task_status(task_id):
    try:
        task = query_db('SELECT status, result FROM tasks WHERE id = ?', [task_id], one=True)
        if task: return jsonify({'status': task['status'], 'result': task['result']})
        return jsonify({'status': 'not_found'}), 404
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- Celery Tasks ---
def _db_execute_celery(query, params=()):
    db = get_db_connection()
    db.execute(query, params)
    db.commit()
    db.close()

@celery.task
def _instance_action_task(task_id, profile_config, action, instance_id, data):
    _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('running', '正在执行操作...', task_id))
    try:
        clients, error = get_oci_clients(profile_config)
        if error: raise Exception(error)
        compute_client, vnet_client = clients['compute'], clients['vnet']
        
        action_map = {
            "START": ("START", "RUNNING"),
            "STOP": ("STOP", "STOPPED"),
            "RESTART": ("SOFTRESET", "RUNNING")
        }
        
        action_upper = action.upper()
        result_message = ""

        if action_upper in action_map:
            oci_action, target_state = action_map[action_upper]
            _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', (f'正在发送 {action_upper} 命令...', task_id))
            compute_client.instance_action(instance_id=instance_id, action=oci_action)
            
            _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', (f'等待实例进入 {target_state} 状态...', task_id))
            oci.wait_until(
                compute_client,
                compute_client.get_instance(instance_id),
                'lifecycle_state',
                target_state,
                max_wait_seconds=300
            )
            result_message = f"✅ 实例已成功 {action}!"

        elif action_upper == "TERMINATE":
            _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('正在发送终止命令...', task_id))
            compute_client.terminate_instance(instance_id, preserve_boot_volume=data.get('preserve_boot_volume', False))
            _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('等待实例进入 TERMINATED 状态...', task_id))
            oci.wait_until(
                compute_client,
                compute_client.get_instance(instance_id),
                'lifecycle_state',
                'TERMINATED',
                max_wait_seconds=300
            )
            result_message = "✅ 实例已成功终止!"

        elif action_upper == "CHANGEIP":
            vnic_id = data.get('vnic_id')
            if not vnic_id: raise Exception("缺少 vnic_id")
            
            private_ips = oci.pagination.list_call_get_all_results(vnet_client.list_private_ips, vnic_id=vnic_id).data
            primary_private_ip = next((p for p in private_ips if p.is_primary), None)
            if not primary_private_ip: raise Exception("未找到主私有IP")

            try:
                _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('正在删除旧的公共IP...', task_id))
                pub_ip_details = oci.core.models.GetPublicIpByPrivateIpIdDetails(private_ip_id=primary_private_ip.id)
                existing_pub_ip = vnet_client.get_public_ip_by_private_ip_id(pub_ip_details).data
                if existing_pub_ip.lifetime == "EPHEMERAL":
                    vnet_client.delete_public_ip(existing_pub_ip.id)
                    time.sleep(5)
            except ServiceError as e:
                if e.status != 404: raise
            
            _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('正在创建新的公共IP...', task_id))
            new_pub_ip = vnet_client.create_public_ip(CreatePublicIpDetails(compartment_id=profile_config['tenancy'], lifetime="EPHEMERAL", private_ip_id=primary_private_ip.id)).data
            result_message = f"✅ 更换IP成功，新IP: {new_pub_ip.ip_address}"

        elif action_upper == "ASSIGNIPV6":
            vnic_id = data.get('vnic_id')
            if not vnic_id: raise Exception("缺少 vnic_id")
            _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('正在请求IPv6地址...', task_id))
            new_ipv6 = vnet_client.create_ipv6(CreateIpv6Details(vnic_id=vnic_id)).data
            result_message = f"✅ 已成功分配IPv6地址: {new_ipv6.ip_address}"
        
        else:
             raise Exception(f"未知的操作: {action}")

        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('success', result_message, task_id))

    except Exception as e:
        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', f"❌ 操作失败: {e}", task_id))

@celery.task
def _create_instance_task(task_id, profile_config, alias, details):
    _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('running', '任务准备中...', task_id))
    clients, error = None, None
    try:
        clients, error = get_oci_clients(profile_config)
        if error: raise Exception(error)
        
        compute_client, identity_client, vnet_client = clients['compute'], clients['identity'], clients['vnet']
        tenancy_ocid, ssh_key = profile_config.get('tenancy'), profile_config.get('default_ssh_public_key')
        if not ssh_key: raise Exception("账号配置缺少默认SSH公钥")

        _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('正在检查网络资源...', task_id))
        subnet_id = _ensure_subnet_in_profile(alias, vnet_client, tenancy_ocid)
        
        ad_name = identity_client.list_availability_domains(tenancy_ocid).data[0].name
        os_name, os_version = details['os_name_version'].split('-')
        shape = details['shape']
        
        _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('正在查找兼容的系统镜像...', task_id))
        images = oci.pagination.list_call_get_all_results(compute_client.list_images, tenancy_ocid, operating_system=os_name, operating_system_version=os_version, shape=shape, sort_by="TIMECREATED", sort_order="DESC").data
        if not images: raise Exception(f"未找到适用于 {os_name} {os_version} 的兼容镜像")
        
        instance_password = generate_oci_password()
        user_data_encoded = get_user_data(instance_password)
        created_instances_info = []

        for i in range(details.get('instance_count', 1)):
            instance_name = f"{details.get('display_name_prefix', 'Instance')}-{i+1}" if details.get('instance_count', 1) > 1 else details.get('display_name_prefix', 'Instance')
            _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', (f'正在为 {instance_name} 发送创建请求...', task_id))
            
            launch_details = LaunchInstanceDetails(
                compartment_id=tenancy_ocid, 
                availability_domain=ad_name, 
                shape=shape, 
                display_name=instance_name,
                create_vnic_details=CreateVnicDetails(subnet_id=subnet_id, assign_public_ip=True), 
                metadata={"ssh_authorized_keys": ssh_key, "user_data": user_data_encoded}, 
                source_details=InstanceSourceViaImageDetails(image_id=images[0].id, boot_volume_size_in_gbs=details['boot_volume_size']),
                shape_config=LaunchInstanceShapeConfigDetails(ocpus=details.get('ocpus'), memory_in_gbs=details.get('memory_in_gbs')) if "Flex" in shape else None
            )
            
            instance = compute_client.launch_instance(launch_details).data
            _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', (f'实例 {instance_name} 正在置备 (PROVISIONING)... 请耐心等待...', task_id))

            oci.wait_until(
                compute_client,
                compute_client.get_instance(instance.id),
                'lifecycle_state',
                'RUNNING',
                max_wait_seconds=600
            )
            
            created_instances_info.append(instance_name)
            if i < details.get('instance_count', 1) - 1: time.sleep(5)

        msg = f"🎉 {len(created_instances_info)} 个实例已成功创建并运行!\n- 实例名: {', '.join(created_instances_info)}\n- 登陆用户名：ubuntu 密码：{instance_password}"
        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('success', msg, task_id))

    except ServiceError as e:
        if e.status == 429 or "TooManyRequests" in e.code or "Out of host capacity" in str(e.message) or "LimitExceeded" in e.code:
             msg = f"❌ 实例创建失败! \n- 原因: 资源不足或请求过于频繁 ({e.code})，请更换区域或稍后再试。"
        else:
            msg = f"❌ 实例创建失败! \n- OCI API 错误: {e.message}"
        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', msg, task_id))
    except Exception as e:
        msg = f"❌ 实例创建失败! \n- 程序内部错误: {e}"
        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', msg, task_id))

@celery.task
def _snatch_instance_task(task_id, profile_config, alias, details):
    clients, error = None, None
    launch_details = None
    instance_password = None
    try:
        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('running', '抢占任务准备中...', task_id))
        clients, error = get_oci_clients(profile_config)
        if error: raise Exception(error)
        
        compute_client, identity_client, vnet_client = clients['compute'], clients['identity'], clients['vnet']
        tenancy_ocid, ssh_key = profile_config.get('tenancy'), profile_config.get('default_ssh_public_key')
        if not ssh_key: raise Exception("账号配置缺少默认SSH公钥")

        subnet_id = _ensure_subnet_in_profile(alias, vnet_client, tenancy_ocid)
        ad_name = details.get('availabilityDomain') or identity_client.list_availability_domains(tenancy_ocid).data[0].name
        os_name, os_version = details['os_name_version'].split('-')
        shape = details['shape']
        
        images = oci.pagination.list_call_get_all_results(compute_client.list_images, tenancy_ocid, operating_system=os_name, operating_system_version=os_version, shape=shape, sort_by="TIMECREATED", sort_order="DESC").data
        if not images: raise Exception(f"未找到适用于 {os_name} {os_version} 的兼容镜像")
        
        instance_password = generate_oci_password()
        user_data_encoded = get_user_data(instance_password)
        
        launch_details = LaunchInstanceDetails(
            compartment_id=tenancy_ocid, 
            availability_domain=ad_name, 
            shape=shape, 
            display_name=details.get('display_name_prefix', 'snatch-instance'),
            create_vnic_details=CreateVnicDetails(subnet_id=subnet_id, assign_public_ip=True), 
            metadata={"ssh_authorized_keys": ssh_key, "user_data": user_data_encoded}, 
            source_details=InstanceSourceViaImageDetails(image_id=images[0].id, boot_volume_size_in_gbs=details['boot_volume_size']),
            shape_config=LaunchInstanceShapeConfigDetails(ocpus=details.get('ocpus'), memory_in_gbs=details.get('memory_in_gbs')) if "Flex" in shape else None
        )
    except Exception as e:
        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', f"❌ 抢占任务准备阶段失败: {e}", task_id))
        return

    count = 0
    while True:
        count += 1
        delay = random.randint(details.get('min_delay', 30), details.get('max_delay', 90))
        
        task_record = query_db('SELECT status FROM tasks WHERE id = ?', [task_id], one=True)
        if not task_record or task_record['status'] == 'failure':
            logging.info(f"Snatching task {task_id} has been stopped or failed. Exiting loop.")
            return

        try:
            _db_execute_celery('UPDATE tasks SET result = ? WHERE id = ?', (f"第 {count} 次尝试创建实例...", task_id))
            instance = compute_client.launch_instance(launch_details).data
            
            _db_execute_celery('UPDATE tasks SET result = ? WHERE id = ?', (f"第 {count} 次尝试成功！实例 {instance.display_name} 正在置备 (PROVISIONING)...", task_id))
            
            oci.wait_until(
                compute_client,
                compute_client.get_instance(instance.id),
                'lifecycle_state',
                'RUNNING',
                max_wait_seconds=600
            )
            
            msg = f"🎉 抢占成功 (第 {count} 次尝试)!\n- 实例名: {instance.display_name}\n- 登陆用户名：ubuntu 密码：{instance_password}"
            _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('success', msg, task_id))
            return

        except ServiceError as e:
            if e.status == 429 or "TooManyRequests" in e.code or "Out of host capacity" in str(e.message) or "LimitExceeded" in e.code:
                msg = f"第 {count} 次尝试失败：资源不足或请求频繁。将在 {delay} 秒后重试..."
            else:
                msg = f"第 {count} 次尝试失败：API错误 ({e.code})。将在 {delay} 秒后重试..."
            _db_execute_celery('UPDATE tasks SET result = ? WHERE id = ?', (msg, task_id))
            time.sleep(delay)
        except Exception as e:
            msg = f"第 {count} 次尝试失败：未知错误({str(e)[:100]}...)。将在 {delay} 秒后重试..."
            _db_execute_celery('UPDATE tasks SET result = ? WHERE id = ?', (msg, task_id))
            time.sleep(delay)
