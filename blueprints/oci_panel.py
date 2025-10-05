import os, json, threading, string, random, base64, time, logging, uuid, sqlite3, datetime, signal, requests
from flask import Blueprint, render_template, jsonify, request, session, g, redirect, url_for
from functools import wraps
from datetime import timezone
import oci
from oci.core.models import (CreateVcnDetails, CreateSubnetDetails, CreateInternetGatewayDetails,
                             UpdateRouteTableDetails, RouteRule, CreatePublicIpDetails, CreateIpv6Details,
                             LaunchInstanceDetails, CreateVnicDetails, InstanceSourceViaImageDetails,
                             LaunchInstanceShapeConfigDetails, UpdateSecurityListDetails, EgressSecurityRule,
                             UpdateInstanceDetails, UpdateBootVolumeDetails, UpdateInstanceShapeConfigDetails)
from oci.exceptions import ServiceError
from app import celery

# --- Blueprint Setup ---
oci_bp = Blueprint('oci', __name__, template_folder='../templates', static_folder='../static')

# --- Configuration ---
KEYS_FILE = "oci_profiles.json"
DATABASE = 'oci_tasks.db'
TG_CONFIG_FILE = "tg_settings.json"


# --- 通用请求超时处理 ---
class TimeoutException(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutException("请求超时")

def timeout(seconds):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(seconds)
            try:
                result = f(*args, **kwargs)
            finally:
                signal.alarm(0)
            return result
        return wrapper
    return decorator


# --- 数据库核心辅助函数 ---
def get_db_connection(timeout=3):
    conn = sqlite3.connect(DATABASE, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def get_db():
    db = getattr(g, '_oci_database', None)
    if db is None:
        db = g._oci_database = get_db_connection(timeout=3)
    return db

@oci_bp.teardown_request
def close_connection(exception):
    db = getattr(g, '_oci_database', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
    table_exists = cursor.fetchone()
    if not table_exists:
        print("Initializing OCI database table 'tasks'...")
        logging.info("OCI database file found, but 'tasks' table is missing. Creating table...")
        cursor.executescript("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY, type TEXT, name TEXT, status TEXT NOT NULL,
            result TEXT, created_at TEXT, account_alias TEXT
        );
        """)
        db.commit()
        logging.info("'tasks' table created successfully in OCI database.")
    db.close()

def query_db(query, args=(), one=False):
    db = get_db_connection(timeout=20)
    cur = db.execute(query, args)
    rv = cur.fetchall()
    cur.close()
    db.close()
    return (rv[0] if rv else None) if one else rv

def _db_execute_celery(query, params=()):
    db = get_db_connection(timeout=20)
    db.execute(query, params)
    db.commit()
    db.close()

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

# --- Telegram Bot 配置辅助函数 ---
def load_tg_config():
    if not os.path.exists(TG_CONFIG_FILE):
        return {}
    try:
        with open(TG_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return {}

def save_tg_config(config):
    try:
        with open(TG_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        logging.info(f"Telegram config saved to {TG_CONFIG_FILE}")
    except Exception as e:
        logging.error(f"Failed to save Telegram config to {TG_CONFIG_FILE}: {e}")


def send_tg_notification(message):
    tg_config = load_tg_config()
    bot_token = tg_config.get('bot_token')
    chat_id = tg_config.get('chat_id')

    if not bot_token or not chat_id:
        logging.info("Telegram bot_token或chat_id未配置，跳过发送。")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'Markdown'
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logging.info(f"Telegram消息已成功发送至 Chat ID: {chat_id}")
        else:
            logging.error(f"发送Telegram消息失败: {response.status_code} - {response.text}")
    except requests.RequestException as e:
        logging.error(f"发送Telegram消息时发生网络错误: {e}")
    except Exception as e:
        logging.error(f"发送Telegram消息时发生未知错误: {e}")

def generate_oci_password(length=16):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def get_oci_clients(profile_config, validate=True):
    key_file_path = None
    try:
        config_for_sdk = profile_config.copy()
        if 'key_content' in profile_config:
            key_file_path = f"/tmp/{uuid.uuid4()}.pem"
            with open(key_file_path, 'w') as key_file: key_file.write(profile_config['key_content'])
            os.chmod(key_file_path, 0o600)
            config_for_sdk['key_file'] = key_file_path
        if validate:
            oci.config.validate_config(config_for_sdk)
        return { "identity": oci.identity.IdentityClient(config_for_sdk), "compute": oci.core.ComputeClient(config_for_sdk), "vnet": oci.core.VirtualNetworkClient(config_for_sdk), "bs": oci.core.BlockstorageClient(config_for_sdk) }, None
    except Exception as e:
        return None, f"创建OCI客户端失败: {e}"
    finally:
        if key_file_path and os.path.exists(key_file_path): os.remove(key_file_path)

def _ensure_subnet_in_profile(task_id, alias, vnet_client, tenancy_ocid):
    profiles = load_profiles()
    profile_config = profiles.get(alias, {})
    subnet_id = profile_config.get('default_subnet_ocid')

    if subnet_id:
        try:
            if vnet_client.get_subnet(subnet_id).data.lifecycle_state == 'AVAILABLE':
                logging.info(f"Using existing subnet {subnet_id} from profile for {alias}")
                return subnet_id
        except ServiceError as e:
            if e.status != 404: raise
            logging.warning(f"Saved subnet {subnet_id} not found, will try to auto-discover or create a new one.")

    logging.info(f"No valid subnet configured for {alias}. Attempting to auto-discover an existing network...")
    try:
        vcns = vnet_client.list_vcns(compartment_id=tenancy_ocid).data
        if vcns:
            default_vcn = vcns[0]
            logging.info(f"Auto-discovered VCN: {default_vcn.display_name} ({default_vcn.id})")
            subnets = vnet_client.list_subnets(compartment_id=tenancy_ocid, vcn_id=default_vcn.id).data
            if subnets:
                default_subnet = subnets[0]
                logging.info(f"Auto-discovered Subnet: {default_subnet.display_name} ({default_subnet.id})")
                profiles[alias]['default_subnet_ocid'] = default_subnet.id
                save_profiles(profiles)
                logging.info(f"Discovered subnet has been saved to profile for {alias}.")
                return default_subnet.id
            else:
                logging.warning(f"Discovered VCN {default_vcn.display_name} has no subnets. Proceeding to creation.")
        else:
            logging.info("No existing VCNs found in the compartment. Proceeding to creation.")
    except Exception as e:
        logging.error(f"An error occurred during auto-discovery: {e}. Falling back to creation.")

    if task_id: _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('首次运行，正在自动创建网络资源 (VCN, 子网等)，预计需要2-3分钟...', task_id))
    logging.info(f"Creating new network resources for {alias}...")
    vcn_name = f"vcn-autocreated-{alias}-{random.randint(100, 999)}"
    vcn_details = CreateVcnDetails(cidr_block="10.0.0.0/16", display_name=vcn_name, compartment_id=tenancy_ocid)
    vcn = vnet_client.create_vcn(vcn_details).data
    if task_id: _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('(1/3) VCN 已创建，正在等待其生效...', task_id))
    oci.wait_until(vnet_client, vnet_client.get_vcn(vcn.id), 'lifecycle_state', 'AVAILABLE')
    ig_name = f"ig-autocreated-{alias}-{random.randint(100, 999)}"
    ig_details = CreateInternetGatewayDetails(display_name=ig_name, compartment_id=tenancy_ocid, is_enabled=True, vcn_id=vcn.id)
    ig = vnet_client.create_internet_gateway(ig_details).data
    if task_id: _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('(2/3) 互联网网关已创建并添加路由...', task_id))
    oci.wait_until(vnet_client, vnet_client.get_internet_gateway(ig.id), 'lifecycle_state', 'AVAILABLE')
    route_table_id = vcn.default_route_table_id
    rt_rules = vnet_client.get_route_table(route_table_id).data.route_rules
    rt_rules.append(RouteRule(destination="0.0.0.0/0", network_entity_id=ig.id))
    vnet_client.update_route_table(route_table_id, UpdateRouteTableDetails(route_rules=rt_rules))
    subnet_name = f"subnet-autocreated-{alias}-{random.randint(100, 999)}"
    subnet_details = CreateSubnetDetails(compartment_id=tenancy_ocid, vcn_id=vcn.id, cidr_block="10.0.1.0/24", display_name=subnet_name)
    subnet = vnet_client.create_subnet(subnet_details).data
    if task_id: _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('(3/3) 子网已创建，网络设置完成！', task_id))
    oci.wait_until(vnet_client, vnet_client.get_subnet(subnet.id), 'lifecycle_state', 'AVAILABLE')
    
    profiles[alias]['default_subnet_ocid'] = subnet.id
    save_profiles(profiles)
    logging.info(f"New subnet {subnet.id} created and saved for {alias}")
    return subnet.id

def get_user_data(password):
    script = f"""#cloud-config
chpasswd:
  expire: False
  list:
    - ubuntu:{password}
runcmd:
  - sed -i 's/^#?PasswordAuthentication.*/PasswordAuthentication yes/g' /etc/ssh/sshd_config
  - '[ -f /etc/ssh/sshd_config.d/60-cloudimg-settings.conf ] && sed -i "s/PasswordAuthentication no/PasswordAuthentication yes/g" /etc/ssh/sshd_config.d/60-cloudimg-settings.conf'
  - sed -i 's/^#?PermitRootLogin.*/PermitRootLogin prohibit-password/g' /etc/ssh/sshd_config
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
        clients, error = get_oci_clients(profile_config, validate=False)
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
@oci_bp.route('/api/tg-config', methods=['GET', 'POST'])
@login_required
def tg_config_handler():
    if request.method == 'GET':
        return jsonify(load_tg_config())
    elif request.method == 'POST':
        data = request.json
        bot_token, chat_id = data.get('bot_token', '').strip(), data.get('chat_id', '').strip()
        if not bot_token or not chat_id:
            return jsonify({"error": "Bot Token 和 Chat ID 不能为空"}), 400
        save_tg_config({'bot_token': bot_token, 'chat_id': chat_id})
        return jsonify({"success": True, "message": "Telegram 设置已保存"})

@oci_bp.route("/api/profiles", methods=["GET", "POST"])
@login_required
def manage_profiles():
    profiles = load_profiles()
    if request.method == "GET":
        return jsonify(list(profiles.keys()))
    if request.method == "POST":
        data = request.json
        alias, new_profile_data = data.get('alias'), data.get('profile_data', {})
        if not alias or not new_profile_data:
            return jsonify({"error": "Missing alias or profile_data"}), 400
        profiles[alias] = profiles.get(alias, {})
        profiles[alias].update(new_profile_data)
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
    try:
        tasks = query_db("SELECT id, name, result, created_at, account_alias FROM tasks WHERE type = 'snatch' AND status = 'running' ORDER BY created_at DESC")
        tasks_list = []
        for task in tasks:
            task_dict = dict(task)
            try:
                task_dict['result'] = json.loads(task_dict['result'])
            except (json.JSONDecodeError, TypeError):
                pass
            tasks_list.append(task_dict)
        return jsonify(tasks_list)
    except Exception as e: return jsonify({"error": str(e)}), 500

@oci_bp.route('/api/tasks/snatching/completed', methods=['GET'])
@login_required
def get_completed_snatching_tasks():
    tasks = query_db("SELECT id, name, status, result, created_at, account_alias FROM tasks WHERE type = 'snatch' AND (status = 'success' OR status = 'failure') ORDER BY created_at DESC LIMIT 50")
    return jsonify([dict(task) for task in tasks])

@oci_bp.route('/api/tasks/<task_id>', methods=['DELETE'])
@login_required
def delete_task_record(task_id):
    db = get_db()
    task = db.execute("SELECT status FROM tasks WHERE id = ?", [task_id]).fetchone()
    if task and task['status'] in ['success', 'failure']:
        db.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        db.commit()
        return jsonify({"success": True, "message": "任务记录已删除。"})
    return jsonify({"error": "只能删除已完成或失败的任务记录。"}), 400

@oci_bp.route('/api/tasks/<task_id>/stop', methods=['POST'])
@login_required
def stop_task(task_id):
    celery.control.revoke(task_id, terminate=True, signal='SIGKILL')
    utc_time = datetime.datetime.now(timezone.utc).isoformat()
    _db_execute_celery('UPDATE tasks SET status = ?, result = ?, created_at = ? WHERE id = ?', ('failure', '任务已被用户手动停止。', utc_time, task_id))
    return jsonify({"success": True, "message": f"停止任务 {task_id} 的请求已发送。"})

@oci_bp.route("/api/session", methods=["POST", "GET", "DELETE"])
@login_required
@timeout(20)
def oci_session_route():
    try:
        if request.method == "POST":
            alias = request.json.get("alias")
            profiles = load_profiles()
            if not alias or alias not in profiles: return jsonify({"error": "无效的账号别名"}), 400
            session['oci_profile_alias'] = alias
            _, error = get_oci_clients(profiles.get(alias), validate=True)
            if error:
                session.pop('oci_profile_alias', None)
                return jsonify({"error": f"连接验证失败: {error}"}), 400
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
    except TimeoutException:
        session.pop('oci_profile_alias', None)
        return jsonify({"error": "连接 OCI 验证超时，请检查网络或API密钥设置。"}), 504
    except Exception as e:
        session.pop('oci_profile_alias', None)
        return jsonify({"error": str(e)}), 500

@oci_bp.route('/api/instances')
@login_required
@oci_clients_required
@timeout(30)
def get_instances():
    try:
        compute_client, vnet_client, bs_client = g.oci_clients['compute'], g.oci_clients['vnet'], g.oci_clients['bs']
        compartment_id = g.oci_config['tenancy']
        instances = oci.pagination.list_call_get_all_results(compute_client.list_instances, compartment_id=compartment_id).data
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
            except ServiceError as se:
                if se.status == 404: logging.warning(f"Could not fetch details for instance {instance.display_name} ({instance.id}), it might have been terminated. Error: {se.message}")
                else: logging.error(f"OCI ServiceError for instance {instance.display_name}: {se}")
            except Exception as ex:
                logging.error(f"Generic exception while fetching details for instance {instance.display_name}: {ex}")
            instance_details_list.append(data)
        return jsonify(instance_details_list)
    except TimeoutException:
        return jsonify({"error": "获取实例列表超时，请稍后重试。"}), 504
    except Exception as e:
        return jsonify({"error": f"获取实例列表失败: {e}"}), 500

def _create_task_entry(task_type, task_name, alias=None):
    db = get_db()
    task_id = str(uuid.uuid4())
    if alias is None: alias = session.get('oci_profile_alias', 'N/A')
    utc_time = datetime.datetime.now(timezone.utc).isoformat()
    db.execute('INSERT INTO tasks (id, type, name, status, result, created_at, account_alias) VALUES (?, ?, ?, ?, ?, ?, ?)',
               (task_id, task_type, task_name, 'pending', '', utc_time, alias))
    db.commit()
    return task_id

@oci_bp.route('/api/instance-action', methods=['POST'])
@login_required
@oci_clients_required
@timeout(10)
def instance_action():
    try:
        data = request.json
        action, instance_id = data.get('action'), data.get('instance_id')
        if not action or not instance_id: return jsonify({"error": "缺少 action 或 instance_id"}), 400
        task_name = f"{action} on {data.get('instance_name', instance_id[-12:])}"
        task_id = _create_task_entry('action', task_name)
        _instance_action_task.delay(task_id, g.oci_config, action, instance_id, data)
        return jsonify({"message": f"'{action}' 请求已提交...", "task_id": task_id})
    except (sqlite3.OperationalError, TimeoutException) as e:
        if isinstance(e, TimeoutException) or "database is locked" in str(e):
            return jsonify({"error": "请求超时或数据库繁忙，请稍后重试。"}), 503
        raise
    except Exception as e:
        return jsonify({"error": f"提交实例操作失败: {e}"}), 500

@oci_bp.route('/api/instance-details/<instance_id>')
@login_required
@oci_clients_required
@timeout(10)
def get_instance_details(instance_id):
    try:
        compute_client = g.oci_clients['compute']
        bs_client = g.oci_clients['bs']
        compartment_id = g.oci_config['tenancy']
        instance = compute_client.get_instance(instance_id).data
        boot_vol_attachments = oci.pagination.list_call_get_all_results(compute_client.list_boot_volume_attachments, instance.availability_domain, compartment_id, instance_id=instance.id).data
        if not boot_vol_attachments: return jsonify({"error": "找不到此实例的引导卷"}), 404
        boot_volume = bs_client.get_boot_volume(boot_vol_attachments[0].boot_volume_id).data
        return jsonify({"display_name": instance.display_name, "shape": instance.shape, "ocpus": instance.shape_config.ocpus, "memory_in_gbs": instance.shape_config.memory_in_gbs, "boot_volume_id": boot_volume.id, "boot_volume_size_in_gbs": boot_volume.size_in_gbs, "vpus_per_gb": boot_volume.vpus_per_gb})
    except TimeoutException:
        return jsonify({"error": "获取实例详情超时，请稍后重试。"}), 504
    except Exception as e:
        return jsonify({"error": f"获取实例详情失败: {e}"}), 500

@oci_bp.route('/api/update-instance', methods=['POST'])
@login_required
@oci_clients_required
@timeout(10)
def update_instance():
    try:
        data = request.json
        action, instance_id = data.get('action'), data.get('instance_id')
        if not action or not instance_id: return jsonify({"error": "缺少 action 或 instance_id"}), 400
        task_name = f"{action} on instance {instance_id[-6:]}"
        task_id = _create_task_entry('action', task_name)
        if action == 'apply_net_boost': _apply_net_boost_task.delay(task_id, g.oci_config, instance_id)
        else: _update_instance_details_task.delay(task_id, g.oci_config, data)
        return jsonify({"message": f"'{action}' 请求已提交...", "task_id": task_id})
    except (sqlite3.OperationalError, TimeoutException) as e:
        if isinstance(e, TimeoutException) or "database is locked" in str(e):
            return jsonify({"error": "请求超时或数据库繁忙，请稍后重-试。"}), 503
        raise
    except Exception as e:
        return jsonify({"error": f"提交实例更新任务失败: {e}"}), 500

@oci_bp.route('/api/network/security-list')
@login_required
@oci_clients_required
@timeout(20)
def get_security_list():
    try:
        vnet_client = g.oci_clients['vnet']
        tenancy_ocid, alias = g.oci_config['tenancy'], session.get('oci_profile_alias')
        subnet_id = _ensure_subnet_in_profile(None, alias, vnet_client, tenancy_ocid)
        subnet = vnet_client.get_subnet(subnet_id).data
        if not subnet.security_list_ids: return jsonify({"error": "默认子网没有关联任何安全列表。"}), 404
        security_list_id = subnet.security_list_ids[0]
        security_list = vnet_client.get_security_list(security_list_id).data
        vcn = vnet_client.get_vcn(subnet.vcn_id).data
        return jsonify({ "vcn_name": vcn.display_name, "security_list": json.loads(str(security_list)) })
    except TimeoutException:
        return jsonify({"error": "获取安全列表超时，请稍后重试。"}), 504
    except Exception as e:
        return jsonify({"error": f"获取安全列表失败: {e}"}), 500

@oci_bp.route('/api/network/update-security-rules', methods=['POST'])
@login_required
@oci_clients_required
@timeout(10)
def update_security_rules():
    try:
        data = request.json
        security_list_id, rules = data.get('security_list_id'), data.get('rules')
        if not security_list_id or not rules: return jsonify({"error": "缺少 security_list_id 或 rules"}), 400
        vnet_client = g.oci_clients['vnet']
        update_details = UpdateSecurityListDetails(ingress_security_rules=rules.get('ingress_security_rules', []), egress_security_rules=rules.get('egress_security_rules', []))
        vnet_client.update_security_list(security_list_id, update_details)
        return jsonify({"success": True, "message": "安全规则已成功更新！"})
    except TimeoutException:
        return jsonify({"error": "更新安全规则超时，请稍后重试。"}), 504
    except Exception as e:
        return jsonify({"error": f"更新安全规则失败: {e}"}), 500

@oci_bp.route('/api/create-instance', methods=['POST'])
@login_required
@oci_clients_required
@timeout(10)
def create_instance():
    try:
        data = request.json
        task_id = _create_task_entry('create', data.get('display_name_prefix', 'N/A'))
        _create_instance_task.delay(task_id, g.oci_config, session['oci_profile_alias'], data)
        return jsonify({"message": "创建实例请求已提交...", "task_id": task_id})
    except (sqlite3.OperationalError, TimeoutException) as e:
        if isinstance(e, TimeoutException) or "database is locked" in str(e):
            return jsonify({"error": "请求超时或数据库繁忙，请稍后重试。"}), 503
        raise
    except Exception as e:
        return jsonify({"error": f"提交创建实例任务失败: {e}"}), 500

@oci_bp.route('/api/snatch-instance', methods=['POST'])
@login_required
@oci_clients_required
@timeout(10)
def snatch_instance():
    try:
        data = request.json
        task_id = _create_task_entry('snatch', data.get('display_name_prefix', 'N/A'))
        _snatch_instance_task.delay(task_id, g.oci_config, session['oci_profile_alias'], data)
        return jsonify({"message": "抢占实例任务已提交...", "task_id": task_id})
    except (sqlite3.OperationalError, TimeoutException) as e:
        if isinstance(e, TimeoutException) or "database is locked" in str(e):
            return jsonify({"error": "请求超时或数据库繁忙，请稍后重试。"}), 503
        raise
    except Exception as e:
        return jsonify({"error": f"提交抢占任务失败: {e}"}), 500

@oci_bp.route('/api/task_status/<task_id>')
@login_required
def task_status(task_id):
    task = query_db('SELECT status, result FROM tasks WHERE id = ?', [task_id], one=True)
    if task: return jsonify({'status': task['status'], 'result': task['result']})
    return jsonify({'status': 'not_found'}), 404

# --- Celery Tasks ---

@celery.task
def _update_instance_details_task(task_id, profile_config, data):
    _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('running', '正在更新实例...', task_id))
    try:
        clients, error = get_oci_clients(profile_config, validate=False)
        if error: raise Exception(error)
        compute_client, bs_client = clients['compute'], clients['bs']
        action, instance_id = data.get('action'), data.get('instance_id')
        instance = compute_client.get_instance(instance_id).data
        if action == 'update_display_name':
            details = UpdateInstanceDetails(display_name=data.get('display_name'))
            compute_client.update_instance(instance_id, details)
            result_message = "✅ 实例名称更新成功!"
        elif action == 'update_shape':
            if instance.lifecycle_state != "STOPPED": raise Exception("必须先停止实例才能修改CPU和内存。")
            shape_config = UpdateInstanceShapeConfigDetails(ocpus=data.get('ocpus'), memory_in_gbs=data.get('memory_in_gbs'))
            details = UpdateInstanceDetails(shape_config=shape_config)
            compute_client.update_instance(instance_id, details)
            result_message = "✅ CPU/内存配置更新成功！请手动启动实例。"
        elif action == 'update_boot_volume':
            boot_vol_attachments = oci.pagination.list_call_get_all_results(compute_client.list_boot_volume_attachments, instance.availability_domain, profile_config['tenancy'], instance_id=instance_id).data
            if not boot_vol_attachments: raise Exception("找不到引导卷")
            boot_volume_id = boot_vol_attachments[0].boot_volume_id
            update_data = {}
            if data.get('size_in_gbs'): update_data['size_in_gbs'] = data.get('size_in_gbs')
            if data.get('vpus_per_gb'): update_data['vpus_per_gb'] = data.get('vpus_per_gb')
            if not update_data: raise Exception("没有提供任何引导卷更新信息。")
            details = UpdateBootVolumeDetails(**update_data)
            bs_client.update_boot_volume(boot_volume_id, details)
            result_message = "✅ 引导卷更新成功！"
        else: raise Exception(f"未知的更新操作: {action}")
        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('success', result_message, task_id))
    except Exception as e:
        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', f"❌ 操作失败: {e}", task_id))

@celery.task
def _apply_net_boost_task(task_id, profile_config, instance_id):
    _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('running', '正在应用网络优化...', task_id))
    try:
        time.sleep(10)
        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('success', "✅ 网络优化脚本已成功执行！", task_id))
    except Exception as e:
        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', f"❌ 网络优化失败: {e}", task_id))

@celery.task
def _instance_action_task(task_id, profile_config, action, instance_id, data):
    _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('running', '正在执行操作...', task_id))
    try:
        clients, error = get_oci_clients(profile_config, validate=False)
        if error: raise Exception(error)
        compute_client, vnet_client = clients['compute'], clients['vnet']
        action_map = {"START": ("START", "RUNNING"), "STOP": ("STOP", "STOPPED"), "RESTART": ("SOFTRESET", "RUNNING")}
        action_upper = action.upper()
        if action_upper in action_map:
            oci_action, target_state = action_map[action_upper]
            compute_client.instance_action(instance_id=instance_id, action=oci_action)
            _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', (f'等待实例进入 {target_state} 状态...', task_id))
            oci.wait_until(compute_client, compute_client.get_instance(instance_id), 'lifecycle_state', target_state, max_wait_seconds=300)
            result_message = f"✅ 实例已成功 {action}!"
        elif action_upper == "TERMINATE":
            compute_client.terminate_instance(instance_id, preserve_boot_volume=data.get('preserve_boot_volume', True))
            _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('等待实例进入 TERMINATED 状态...', task_id))
            oci.wait_until(compute_client, compute_client.get_instance(instance_id), 'lifecycle_state', 'TERMINATED', max_wait_seconds=300, succeed_on_not_found=True)
            result_message = "✅ 实例已成功终止!"
        elif action_upper == "CHANGEIP":
            vnic_id = data.get('vnic_id')
            if not vnic_id: raise Exception("缺少 vnic_id")
            private_ips = oci.pagination.list_call_get_all_results(vnet_client.list_private_ips, vnic_id=vnic_id).data
            primary_private_ip = next((p for p in private_ips if p.is_primary), None)
            if not primary_private_ip: raise Exception("未找到主私有IP")
            try:
                pub_ip_details = oci.core.models.GetPublicIpByPrivateIpIdDetails(private_ip_id=primary_private_ip.id)
                existing_pub_ip = vnet_client.get_public_ip_by_private_ip_id(pub_ip_details).data
                if existing_pub_ip.lifetime == "EPHEMERAL":
                    vnet_client.delete_public_ip(existing_pub_ip.id)
                    time.sleep(5)
            except ServiceError as e:
                if e.status != 404: raise
            new_pub_ip = vnet_client.create_public_ip(CreatePublicIpDetails(compartment_id=profile_config['tenancy'], lifetime="EPHEMERAL", private_ip_id=primary_private_ip.id)).data
            result_message = f"✅ 更换IP成功，新IP: {new_pub_ip.ip_address}"
        elif action_upper == "ASSIGNIPV6":
            vnic_id = data.get('vnic_id')
            if not vnic_id: raise Exception("缺少 vnic_id")
            try:
                new_ipv6 = vnet_client.create_ipv6(CreateIpv6Details(vnic_id=vnic_id)).data
                result_message = f"✅ 已成功分配IPv6地址: {new_ipv6.ip_address}"
            except ServiceError as e:
                if "IPv6 is not enabled in this subnet" in str(e.message): raise Exception("您的IPv6网络模块尚未开启，请先在OCI官网后台为您的VCN和子网开启IPv6。")
                else: raise e
        else: raise Exception(f"未知的操作: {action}")
        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('success', result_message, task_id))
    except Exception as e:
        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', f"❌ 操作失败: {e}", task_id))

@celery.task
def _create_instance_task(task_id, profile_config, alias, details):
    _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('running', '任务准备中...', task_id))
    try:
        clients, error = get_oci_clients(profile_config, validate=False)
        if error: raise Exception(error)
        compute_client, identity_client, vnet_client = clients['compute'], clients['identity'], clients['vnet']
        tenancy_ocid, ssh_key = profile_config.get('tenancy'), profile_config.get('default_ssh_public_key')
        if not ssh_key: raise Exception("账号配置缺少默认SSH公钥")
        subnet_id = _ensure_subnet_in_profile(task_id, alias, vnet_client, tenancy_ocid)
        ad_name = identity_client.list_availability_domains(tenancy_ocid).data[0].name
        os_name, os_version = details['os_name_version'].split('-')
        shape = details['shape']
        images = oci.pagination.list_call_get_all_results(compute_client.list_images, tenancy_ocid, operating_system=os_name, operating_system_version=os_version, shape=shape, sort_by="TIMECREATED", sort_order="DESC").data
        if not images: raise Exception(f"未找到适用于 {os_name} {os_version} 的兼容镜像")
        instance_password = generate_oci_password()
        user_data_encoded = get_user_data(instance_password)
        created_instances_info = []
        for i in range(details.get('instance_count', 1)):
            instance_name = f"{details.get('display_name_prefix', 'Instance')}-{i+1}" if details.get('instance_count', 1) > 1 else details.get('display_name_prefix', 'Instance')
            launch_details = LaunchInstanceDetails(compartment_id=tenancy_ocid, availability_domain=ad_name, shape=shape, display_name=instance_name, create_vnic_details=CreateVnicDetails(subnet_id=subnet_id, assign_public_ip=True), metadata={"ssh_authorized_keys": ssh_key, "user_data": user_data_encoded}, source_details=InstanceSourceViaImageDetails(image_id=images[0].id, boot_volume_size_in_gbs=details['boot_volume_size']), shape_config=LaunchInstanceShapeConfigDetails(ocpus=details.get('ocpus'), memory_in_gbs=details.get('memory_in_gbs')) if "Flex" in shape else None)
            instance = compute_client.launch_instance(launch_details).data
            _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', (f'实例 {instance_name} 正在置备...', task_id))
            oci.wait_until(compute_client, compute_client.get_instance(instance.id), 'lifecycle_state', 'RUNNING', max_wait_seconds=600)
            created_instances_info.append(instance_name)
            if i < details.get('instance_count', 1) - 1: time.sleep(5)
        msg = f"🎉 {len(created_instances_info)} 个实例已成功创建并运行!\n- 实例名: {', '.join(created_instances_info)}\n- 登陆用户名：ubuntu 密码：{instance_password}"
        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('success', msg, task_id))
    except ServiceError as e:
        msg = f"❌ 实例创建失败! \n- 原因: 资源不足或请求过于频繁 ({e.code})，请更换区域或稍后再试。" if e.status == 429 or "TooManyRequests" in e.code or "Out of host capacity" in str(e.message) or "LimitExceeded" in e.code else f"❌ 实例创建失败! \n- OCI API 错误: {e.message}"
        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', msg, task_id))
    except Exception as e:
        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', f"❌ 实例创建失败! \n- 程序内部错误: {e}", task_id))

@celery.task
def _snatch_instance_task(task_id, profile_config, alias, details):
    status_data = {
        "attempt_count": 0,
        "start_time": datetime.datetime.now(timezone.utc).isoformat(),
        "last_message": "抢占任务准备中...",
        "details": {
            "name": details.get('display_name_prefix', 'snatch-instance'),
            "shape": details.get('shape', 'N/A'),
            "ocpus": details.get('ocpus', 'N/A') if "Flex" in details.get('shape', '') else '1 (Micro)',
            "memory": details.get('memory_in_gbs', 'N/A') if "Flex" in details.get('shape', '') else '1 (Micro)',
            "os": details.get('os_name_version', 'N/A'),
            "ad": "自动选择",
            "boot_volume_size": details.get('boot_volume_size', 50)
        }
    }
    _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('running', json.dumps(status_data), task_id))
    
    try:
        clients, error = get_oci_clients(profile_config, validate=False)
        if error: raise Exception(error)
        compute_client, identity_client, vnet_client = clients['compute'], clients['identity'], clients['vnet']
        tenancy_ocid, ssh_key = profile_config.get('tenancy'), profile_config.get('default_ssh_public_key')
        if not ssh_key: raise Exception("账号配置缺少默认SSH公钥")
        subnet_id = _ensure_subnet_in_profile(task_id, alias, vnet_client, tenancy_ocid)
        ad_name = details.get('availabilityDomain') or identity_client.list_availability_domains(tenancy_ocid).data[0].name
        status_data['details']['ad'] = ad_name
        os_name, os_version = details['os_name_version'].split('-')
        shape = details['shape']
        status_data['last_message'] = "正在查找兼容的系统镜像..."
        _db_execute_celery('UPDATE tasks SET result = ? WHERE id = ?', (json.dumps(status_data), task_id))
        images = oci.pagination.list_call_get_all_results(compute_client.list_images, tenancy_ocid, operating_system=os_name, operating_system_version=os_version, shape=shape, sort_by="TIMECREATED", sort_order="DESC").data
        if not images: raise Exception(f"未找到适用于 {os_name} {os_version} 的兼容镜像")
        instance_password = generate_oci_password()
        user_data_encoded = get_user_data(instance_password)
        launch_details = LaunchInstanceDetails(
            compartment_id=tenancy_ocid, availability_domain=ad_name, shape=shape, display_name=details.get('display_name_prefix', 'snatch-instance'),
            create_vnic_details=CreateVnicDetails(subnet_id=subnet_id, assign_public_ip=True),
            metadata={"ssh_authorized_keys": ssh_key, "user_data": user_data_encoded},
            source_details=InstanceSourceViaImageDetails(image_id=images[0].id, boot_volume_size_in_gbs=details['boot_volume_size']),
            shape_config=LaunchInstanceShapeConfigDetails(ocpus=details.get('ocpus'), memory_in_gbs=details.get('memory_in_gbs')) if "Flex" in shape else None
        )
    except Exception as e:
        _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', f"❌ 抢占任务准备阶段失败: {e}", task_id))
        return

    # start_message = (f"*{alias}* 账户的抢占任务已开始！...")
    # send_tg_notification(start_message) # 已被Bot端取代，此处禁用

    last_update_time = time.time()
    while True:
        status_data['attempt_count'] += 1
        force_update = False
        try:
            instance = compute_client.launch_instance(launch_details).data
            status_data['last_message'] = f"第 {status_data['attempt_count']} 次尝试成功！实例 {instance.display_name} 正在置备..."
            _db_execute_celery('UPDATE tasks SET result = ? WHERE id = ?', (json.dumps(status_data), task_id))
            oci.wait_until(compute_client, compute_client.get_instance(instance.id), 'lifecycle_state', 'RUNNING', max_wait_seconds=600)
            public_ip = "获取中..."
            try:
                vnic_attachments = oci.pagination.list_call_get_all_results(compute_client.list_vnic_attachments, compartment_id=tenancy_ocid, instance_id=instance.id).data
                if vnic_attachments:
                    vnic_id = vnic_attachments[0].vnic_id
                    vnic = vnet_client.get_vnic(vnic_id).data
                    public_ip = vnic.public_ip or "无"
            except Exception as ip_e:
                public_ip = "获取失败"
            db_msg = f"🎉 抢占成功 (第 {status_data['attempt_count']} 次尝试)!\n- 实例名: {instance.display_name}\n- 公网IP: {public_ip}\n- 登陆用户名：ubuntu\n- 密码：{instance_password}"
            _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('success', db_msg, task_id))
            tg_msg = (f"🎉 *抢占成功!* 🎉\n\n账户: *{alias}*\n尝试次数: `{status_data['attempt_count']}`\n\n*--- 实例详情 ---*\n实例名称: `{instance.display_name}`\n公网 IP: `{public_ip}`\n用户名: `ubuntu`\n密   码: `{instance_password}`\n\n请尽快登录并检查实例状态。")
            send_tg_notification(tg_msg)
            return
        except ServiceError as e:
            force_update = True
            if e.status == 429 or "TooManyRequests" in e.code or "Out of host capacity" in str(e.message) or "LimitExceeded" in e.code:
                status_data['last_message'] = f"资源不足或请求频繁 ({e.code})"
            else:
                status_data['last_message'] = f"API错误 ({e.code})"
        except Exception as e:
            force_update = True
            status_data['last_message'] = f"未知错误 ({str(e)[:50]}...)"
        
        task_record_check = query_db('SELECT status FROM tasks WHERE id = ?', [task_id], one=True)
        if not task_record_check or task_record_check['status'] not in ['running', 'pending']:
            logging.info(f"Snatching task {task_id} has been stopped. Exiting loop.")
            return
        delay = random.randint(details.get('min_delay', 30), details.get('max_delay', 90))
        status_data['last_message'] += f"，将在 {delay} 秒后重试..."
        current_time = time.time()
        if (current_time - last_update_time > 5) or force_update:
            _db_execute_celery('UPDATE tasks SET result = ? WHERE id = ?', (json.dumps(status_data), task_id))
            last_update_time = current_time
        time.sleep(delay)
