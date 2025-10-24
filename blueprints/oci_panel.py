import os, json, threading, string, random, base64, time, logging, uuid, sqlite3, datetime, signal, requests
from flask import Blueprint, render_template, jsonify, request, session, g, redirect, url_for, current_app
from functools import wraps
from pypinyin import lazy_pinyin
from datetime import timezone, timedelta
import oci
from oci.core.models import (CreateVcnDetails, CreateSubnetDetails, CreateInternetGatewayDetails,
                             UpdateRouteTableDetails, RouteRule, CreatePublicIpDetails, CreateIpv6Details,
                             LaunchInstanceDetails, CreateVnicDetails, InstanceSourceViaImageDetails,
                             LaunchInstanceShapeConfigDetails, UpdateSecurityListDetails, EgressSecurityRule, IngressSecurityRule,
                             UpdateInstanceDetails, UpdateBootVolumeDetails, UpdateInstanceShapeConfigDetails,
                             AddVcnIpv6CidrDetails, UpdateSubnetDetails,
                             # --- ✨ MODIFICATION START ✨ ---
                             LaunchInstanceAgentConfigDetails, InstanceAgentPluginConfigDetails
                             # --- ✨ MODIFICATION END ✨ ---
                             )
from oci.exceptions import ServiceError
from app import celery

# --- Blueprint Setup ---
oci_bp = Blueprint('oci', __name__, template_folder='../../templates', static_folder='../../static')

# --- Configuration ---
KEYS_FILE = "oci_profiles.json"
DATABASE = 'oci_tasks.db'
TG_CONFIG_FILE = "tg_settings.json"
CLOUDFLARE_CONFIG_FILE = "cloudflare_settings.json"
# --- ✨ MODIFICATION START ✨ ---
# 新增一个文件来存储可动态修改的默认SSH公钥
DEFAULT_KEY_FILE = "default_key.json" 
# --- ✨ MODIFICATION END ✨ ---


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

def update_db_schema():
    try:
        db = get_db_connection()
        cursor = db.cursor()
        
        cursor.execute("PRAGMA table_info(tasks)")
        columns = [info['name'] for info in cursor.fetchall()]
        
        if 'completed_at' not in columns:
            logging.info("Schema update: Adding 'completed_at' column to 'tasks' table.")
            cursor.execute("ALTER TABLE tasks ADD COLUMN completed_at TEXT")
            db.commit()
            logging.info("'completed_at' column added successfully.")

        db.close()
    except Exception as e:
        logging.error(f"Failed to update database schema: {e}")


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
            result TEXT, created_at TEXT, account_alias TEXT, completed_at TEXT
        );
        """)
        db.commit()
        logging.info("'tasks' table created successfully in OCI database.")
    else:
        update_db_schema()
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
def _format_timedelta(duration: timedelta) -> str:
    seconds = duration.total_seconds()
    if seconds < 60:
        return f"{int(seconds)}秒"
    
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    
    parts = []
    if days > 0:
        parts.append(f"{int(days)}天")
    if hours > 0:
        parts.append(f"{int(hours)}小时")
    if minutes > 0:
        parts.append(f"{int(minutes)}分钟")
        
    return "".join(parts) if parts else "不到1分钟"

def load_profiles():
    if not os.path.exists(KEYS_FILE): return {"profiles": {}, "profile_order": []}
    try:
        with open(KEYS_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            data = json.loads(content) if content else {"profiles": {}, "profile_order": []}
            if "profiles" not in data:
                data = {"profiles": data, "profile_order": list(data.keys())}
            if "profile_order" not in data:
                data["profile_order"] = list(data["profiles"].keys())
            return data
    except (IOError, json.JSONDecodeError): return {"profiles": {}, "profile_order": []}

def save_profiles(data):
    with open(KEYS_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)

def load_tg_config():
    if not os.path.exists(TG_CONFIG_FILE): return {}
    try:
        with open(TG_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError): return {}

def save_tg_config(config):
    try:
        with open(TG_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        logging.info(f"Telegram config saved to {TG_CONFIG_FILE}")
    except Exception as e:
        logging.error(f"Failed to save Telegram config to {TG_CONFIG_FILE}: {e}")

# --- Cloudflare 辅助函数 ---
def load_cloudflare_config():
    if not os.path.exists(CLOUDFLARE_CONFIG_FILE):
        return {}
    try:
        with open(CLOUDFLARE_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return {}

def save_cloudflare_config(config):
    try:
        with open(CLOUDFLARE_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        logging.info(f"Cloudflare config saved to {CLOUDFLARE_CONFIG_FILE}")
    except Exception as e:
        logging.error(f"Failed to save Cloudflare config: {e}")

def _update_cloudflare_dns(subdomain, ip_address, record_type='A'):
    cf_config = load_cloudflare_config()
    api_token = cf_config.get('api_token')
    zone_id = cf_config.get('zone_id')
    domain = cf_config.get('domain')

    if not all([api_token, zone_id, domain]):
        logging.warning("Cloudflare 未配置，跳过 DNS 更新。")
        return "Cloudflare 未配置，跳过 DNS 更新。"

    full_domain = f"{subdomain}.{domain}"
    api_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }

    try:
        search_params = {'type': record_type, 'name': full_domain}
        response = requests.get(api_url, headers=headers, params=search_params, timeout=15)
        response.raise_for_status()
        search_result = response.json()

        dns_payload = {
            'type': record_type,
            'name': full_domain,
            'content': ip_address,
            'ttl': 60,
            'proxied': False
        }

        if search_result['result']:
            record_id = search_result['result'][0]['id']
            update_url = f"{api_url}/{record_id}"
            response = requests.put(update_url, headers=headers, json=dns_payload, timeout=15)
            action_log = "更新"
        else:
            response = requests.post(api_url, headers=headers, json=dns_payload, timeout=15)
            action_log = "创建"

        response.raise_for_status()
        result_data = response.json()

        if result_data['success']:
            msg = f"✅ Cloudflare DNS 记录: {full_domain} -> {ip_address}"
            logging.info(f"成功 {action_log} Cloudflare DNS 记录: {full_domain} -> {ip_address}")
            return msg
        else:
            errors = result_data.get('errors', [{'message': '未知错误'}])
            error_msg = ', '.join([e['message'] for e in errors])
            msg = f"❌ {action_log} Cloudflare DNS 记录失败: {error_msg}"
            logging.error(msg)
            return msg

    except requests.RequestException as e:
        msg = f"❌ 更新 Cloudflare DNS 时发生网络错误: {e}"
        logging.error(msg)
        return msg
    except Exception as e:
        msg = f"❌ 更新 Cloudflare DNS 时发生未知错误: {e}"
        logging.error(msg)
        return msg

def send_tg_notification(message):
    tg_config = load_tg_config()
    bot_token = tg_config.get('bot_token')
    chat_id = tg_config.get('chat_id')
    if not bot_token or not chat_id:
        logging.info("Telegram bot_token或chat_id未配置，跳过发送。")
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown'}
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
        
        if 'proxy' in profile_config and profile_config['proxy']:
            config_for_sdk['proxy'] = profile_config['proxy']
            logging.info(f"Using proxy: {profile_config['proxy']} for OCI client.")

        if 'key_content' in profile_config:
            key_file_path = f"/tmp/{uuid.uuid4()}.pem"
            with open(key_file_path, 'w') as key_file:
                key_file.write(profile_config['key_content'])
            os.chmod(key_file_path, 0o600)
            config_for_sdk['key_file'] = key_file_path
        
        if validate:
            oci.config.validate_config(config_for_sdk)
            
        return {
            "identity": oci.identity.IdentityClient(config_for_sdk),
            "compute": oci.core.ComputeClient(config_for_sdk),
            "vnet": oci.core.VirtualNetworkClient(config_for_sdk),
            "bs": oci.core.BlockstorageClient(config_for_sdk)
        }, None
    except Exception as e:
        return None, f"创建OCI客户端失败: {e}"
    finally:
        if key_file_path and os.path.exists(key_file_path):
            os.remove(key_file_path)

def _ensure_subnet_in_profile(task_id, alias, vnet_client, tenancy_ocid):
    all_data = load_profiles()
    profiles = all_data.get("profiles", {})
    profile_config = profiles.get(alias, {})
    subnet_id = profile_config.get('default_subnet_ocid')
    if subnet_id:
        try:
            if vnet_client.get_subnet(subnet_id).data.lifecycle_state == 'AVAILABLE':
                return subnet_id
        except ServiceError as e:
            if e.status != 404: raise
            logging.warning(f"Saved subnet {subnet_id} not found, will auto-discover or create a new one.")
    try:
        vcns = vnet_client.list_vcns(compartment_id=tenancy_ocid).data
        if vcns:
            default_vcn = vcns[0]
            subnets = vnet_client.list_subnets(compartment_id=tenancy_ocid, vcn_id=default_vcn.id).data
            if subnets:
                default_subnet = subnets[0]
                all_data["profiles"][alias]['default_subnet_ocid'] = default_subnet.id
                save_profiles(all_data)
                return default_subnet.id
    except Exception as e:
        logging.error(f"An error occurred during auto-discovery: {e}. Falling back to creation.")
    if task_id: _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('首次运行，正在自动创建网络资源 (VCN, 子网等)，预计需要2-3分钟...', task_id))
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
    all_data["profiles"][alias]['default_subnet_ocid'] = subnet.id
    save_profiles(all_data)
    return subnet.id

def get_user_data(password, startup_script=None):
    default_script = """
echo "Waiting for apt lock to be released..."
while fuser /var/lib/apt/lists/lock >/dev/null 2>&1 || fuser /var/lib/dpkg/lock >/dev/null 2>&1 ; do
   echo "Another apt/dpkg process is running. Waiting 10 seconds..."
   sleep 10
done

echo "Starting package installation with retries..."
for i in 1 2 3; do
  apt-get update && apt-get install -y curl wget unzip git socat cron && break
  echo "APT commands failed (attempt $i/3), retrying in 15 seconds..."
  sleep 15
done
"""
    
    script_parts = [
        "#cloud-config",
        "chpasswd:",
        "  expire: False",
        "  list:",
        f"    - ubuntu:{password}",
        "runcmd:",
        "  - \"sed -i -e '/^#*PasswordAuthentication/s/^.*$/PasswordAuthentication yes/' /etc/ssh/sshd_config\"",
        "  - 'rm -f /etc/ssh/sshd_config.d/60-cloudimg-settings.conf'",
        "  - \"sed -i -e '/^#*PermitRootLogin/s/^.*$/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config\"",
        f"  - [ bash, -c, {json.dumps(default_script)} ]",
    ]

    if startup_script and startup_script.strip():
        script_parts.append(f"  - [ bash, -c, {json.dumps(startup_script.strip())} ]")

    script_parts.append("  - systemctl restart sshd || service sshd restart || service ssh restart")

    script = "\n".join(script_parts)
    return base64.b64encode(script.encode('utf-8')).decode('utf-8')

def _enable_ipv6_networking(task_id, vnet_client, vnic_id):
    _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('(1/5) 正在获取网络资源...', task_id))
    vnic = vnet_client.get_vnic(vnic_id).data
    subnet = vnet_client.get_subnet(vnic.subnet_id).data
    vcn = vnet_client.get_vcn(subnet.vcn_id).data
    if not vcn.ipv6_cidr_blocks:
        _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('(2/5) 正在为VCN开启IPv6...', task_id))
        details = AddVcnIpv6CidrDetails(is_oracle_gua_allocation_enabled=True)
        vnet_client.add_ipv6_vcn_cidr(vcn_id=vcn.id, add_vcn_ipv6_cidr_details=details)
        oci.wait_until(vnet_client, vnet_client.get_vcn(vcn.id), 'lifecycle_state', 'AVAILABLE', max_wait_seconds=300)
        vcn = vnet_client.get_vcn(vcn.id).data
        logging.info(f"VCN {vcn.id} 已成功开启IPv6，地址段: {vcn.ipv6_cidr_blocks}")
    if not subnet.ipv6_cidr_block:
        _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('(3/5) 正在为子网分配IPv6地址段...', task_id))
        vcn_ipv6_cidr = vcn.ipv6_cidr_blocks[0]
        subnet_ipv6_cidr = vcn_ipv6_cidr.replace('/56', '/64')
        details = UpdateSubnetDetails(ipv6_cidr_block=subnet_ipv6_cidr)
        vnet_client.update_subnet(subnet.id, details)
        oci.wait_until(vnet_client, vnet_client.get_subnet(subnet.id), 'lifecycle_state', 'AVAILABLE', max_wait_seconds=300)
        logging.info(f"Subnet {subnet.id} 已成功分配IPv6地址段: {subnet_ipv6_cidr}")
    _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('(4/5) 正在更新路由表以支持IPv6...', task_id))
    route_table = vnet_client.get_route_table(vcn.default_route_table_id).data
    igws = vnet_client.list_internet_gateways(compartment_id=vcn.compartment_id, vcn_id=vcn.id).data
    if not igws:
        raise Exception("未找到互联网网关，无法为IPv6添加路由规则。")
    igw_id = igws[0].id
    ipv6_rule_exists = any(rule.destination == '::/0' for rule in route_table.route_rules)
    if not ipv6_rule_exists:
        new_rules = list(route_table.route_rules)
        new_rules.append(RouteRule(destination='::/0', network_entity_id=igw_id))
        vnet_client.update_route_table(route_table.id, UpdateRouteTableDetails(route_rules=new_rules))
        logging.info(f"已为路由表 {route_table.id} 添加IPv6默认路由。")
    _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('(5/5) 正在更新安全规则以支持IPv6...', task_id))
    security_list = vnet_client.get_security_list(vcn.default_security_list_id).data
    egress_ipv6_rule_exists = any(rule.destination == '::/0' for rule in security_list.egress_security_rules)
    if not egress_ipv6_rule_exists:
        new_egress_rules = list(security_list.egress_security_rules)
        new_egress_rules.append(EgressSecurityRule(destination='::/0', protocol='all'))
        vnet_client.update_security_list(security_list.id, UpdateSecurityListDetails(egress_security_rules=new_egress_rules))
        logging.info(f"已为安全列表 {security_list.id} 添加出站IPv6规则。")

# --- 任务恢复功能 ---
def recover_snatching_tasks():
    logging.info("--- 检查并恢复被中断的抢占任务 ---")
    
    db = get_db_connection()
    try:
        orphaned_tasks = db.execute(
            "SELECT id, result, account_alias FROM tasks WHERE status = 'running' AND type = 'snatch'"
        ).fetchall()

        if not orphaned_tasks:
            logging.info("没有需要自动恢复的抢占任务。")
            return

        logging.info(f"发现 {len(orphaned_tasks)} 个需要自动恢复的抢占任务。")
        profiles = load_profiles().get("profiles", {})

        for task in orphaned_tasks:
            task_id = task['id']
            alias = task['account_alias']
            
            profile_config = profiles.get(alias)
            if not profile_config:
                logging.warning(f"任务 {task_id} 对应的账号 '{alias}' 配置已不存在，无法恢复。")
                db.execute(
                    "UPDATE tasks SET status = ?, result = ? WHERE id = ?",
                    ('failure', '任务因关联的账号配置被删除而恢复失败。', task_id)
                )
                db.commit()
                continue

            try:
                result_json = json.loads(task['result'])
                original_details = result_json.get('details')
                if not original_details:
                    raise ValueError("在任务 result 中未找到 'details' 字段。")
                
                result_json['last_message'] = "服务重启，任务已自动恢复并继续执行..."
                new_run_id = str(uuid.uuid4())
                result_json['run_id'] = new_run_id
                
                db.execute(
                    "UPDATE tasks SET result = ? WHERE id = ?",
                    (json.dumps(result_json), task_id)
                )
                db.commit()
                
                auto_bind_domain = original_details.get('auto_bind_domain', False)
                _snatch_instance_task.delay(task_id, profile_config, alias, original_details, new_run_id, auto_bind_domain)

                logging.info(f"已成功重新派发任务 {task_id} (账号: {alias})。")

            except (json.JSONDecodeError, ValueError, KeyError) as e:
                logging.error(f"解析或恢复任务 {task_id} 失败: {e}。")
                db.execute(
                    "UPDATE tasks SET status = ?, result = ? WHERE id = ?",
                    ('failure', f'任务恢复失败，原因: 无法解析任务参数 ({e})', task_id)
                )
                db.commit()

    except Exception as e:
        logging.error(f"在恢复抢占任务过程中发生未知错误: {e}")
    finally:
        db.close()
        logging.info("--- 抢占任务恢复检查完成 ---")

# --- Decorators ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_logged_in" in session:
            return f(*args, **kwargs)

        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            if token == current_app.config.get('PANEL_API_KEY'):
                return f(*args, **kwargs)
        
        if request.path.startswith('/oci/api/'):
            return jsonify({"error": "用户未登录或API密钥无效"}), 401
        return redirect(url_for('login'))
    return decorated_function

def oci_clients_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        alias = session.get('oci_profile_alias') or g.get('api_selected_alias')

        if not alias:
             return jsonify({"error": "请先选择一个OCI账号"}), 403

        profile_config = load_profiles().get("profiles", {}).get(alias)
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
@oci_bp.route('/api/default-ssh-key', methods=['GET', 'POST'])
@login_required
def default_ssh_key_handler():
    if request.method == 'GET':
        try:
            if os.path.exists(DEFAULT_KEY_FILE):
                with open(DEFAULT_KEY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return jsonify(data)
            return jsonify({'key': ''})
        except (IOError, json.JSONDecodeError):
            return jsonify({'key': ''})

    elif request.method == 'POST':
        data = request.json
        key = data.get('key', '').strip()
        if not key.startswith('ssh-rsa'):
            return jsonify({"error": "无效的 SSH 公钥格式。"}), 400
        try:
            with open(DEFAULT_KEY_FILE, 'w', encoding='utf-8') as f:
                json.dump({'key': key}, f, indent=4)
            return jsonify({"success": True, "message": "全局默认公钥已成功保存！"})
        except IOError as e:
            logging.error(f"保存默认公钥失败: {e}")
            return jsonify({"error": "保存默认公钥文件时出错。"}), 500

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

@oci_bp.route('/api/cloudflare-config', methods=['GET', 'POST'])
@login_required
def cloudflare_config_handler():
    if request.method == 'GET':
        return jsonify(load_cloudflare_config())
    elif request.method == 'POST':
        data = request.json
        api_token = data.get('api_token', '').strip()
        zone_id = data.get('zone_id', '').strip()
        domain = data.get('domain', '').strip()
        if not all([api_token, zone_id, domain]):
            return jsonify({"error": "API 令牌, Zone ID 和主域名均不能为空"}), 400
        
        config = {'api_token': api_token, 'zone_id': zone_id, 'domain': domain}
        save_cloudflare_config(config)
        return jsonify({"success": True, "message": "Cloudflare 设置已成功保存"})


@oci_bp.route("/api/profiles", methods=["GET", "POST"])
@login_required
def manage_profiles():
    all_data = load_profiles()
    profiles = all_data.get("profiles", {})
    
    if request.method == "GET":
        profile_order = all_data.get("profile_order", [])
        
        ordered_profiles = [p for p in profile_order if p in profiles]
        missing_profiles = sorted(
            [p for p in profiles if p not in profile_order],
            key=lambda name: "".join(lazy_pinyin(name)).lower()
        )
        
        final_order = ordered_profiles + missing_profiles
        
        if final_order != profile_order:
            all_data["profile_order"] = final_order
            save_profiles(all_data)
            
        return jsonify(final_order)

    if request.method == "POST":
        data = request.json
        alias, new_profile_data = data.get('alias'), data.get('profile_data', {})
        if not alias or not new_profile_data:
            return jsonify({"error": "Missing alias or profile_data"}), 400
        
        is_new_profile = alias not in profiles
        
        updated_profile = profiles.get(alias, {})
        updated_profile.update(new_profile_data)

        if not updated_profile.get('default_ssh_public_key'):
            try:
                if os.path.exists(DEFAULT_KEY_FILE):
                    with open(DEFAULT_KEY_FILE, 'r', encoding='utf-8') as f:
                        key_data = json.load(f)
                        updated_profile['default_ssh_public_key'] = key_data.get('key', "")
                else:
                    updated_profile['default_ssh_public_key'] = ""
            except (IOError, json.JSONDecodeError):
                updated_profile['default_ssh_public_key'] = ""
        
        all_data["profiles"][alias] = updated_profile
        
        if is_new_profile:
            if "profile_order" not in all_data:
                all_data["profile_order"] = []
            if alias not in all_data["profile_order"]:
                 all_data["profile_order"].append(alias)
                 
        save_profiles(all_data)
        return jsonify({"success": True, "alias": alias})

@oci_bp.route("/api/profiles/order", methods=["POST"])
@login_required
def save_profile_order():
    data = request.json
    new_order = data.get('order')
    if not isinstance(new_order, list):
        return jsonify({"error": "Invalid order data"}), 400
    
    all_data = load_profiles()
    all_data['profile_order'] = new_order
    save_profiles(all_data)
    
    return jsonify({"success": True, "message": "Account order saved."})

@oci_bp.route("/api/profiles/<alias>", methods=["GET", "DELETE"])
@login_required
def handle_single_profile(alias):
    all_data = load_profiles()
    profiles = all_data.get("profiles", {})
    
    if alias not in profiles: return jsonify({"error": "账号未找到"}), 404
    
    if request.method == "GET": return jsonify(profiles[alias])
    
    if request.method == "DELETE":
        del all_data["profiles"][alias]
        if "profile_order" in all_data and alias in all_data["profile_order"]:
            all_data["profile_order"].remove(alias)
            
        save_profiles(all_data)
        
        if session.get('oci_profile_alias') == alias: session.pop('oci_profile_alias', None)
        return jsonify({"success": True})

@oci_bp.route('/api/tasks/snatching/running', methods=['GET'])
@login_required
def get_running_snatching_tasks():
    try:
        tasks = query_db("SELECT id, name, result, created_at, account_alias, status FROM tasks WHERE type = 'snatch' AND status IN ('running', 'paused') ORDER BY created_at DESC")
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
    tasks = query_db("SELECT id, name, status, result, created_at, completed_at, account_alias FROM tasks WHERE type = 'snatch' AND (status = 'success' OR status = 'failure') ORDER BY created_at DESC LIMIT 50")
    return jsonify([dict(task) for task in tasks])

@oci_bp.route('/api/tasks/<task_id>', methods=['DELETE'])
@login_required
def delete_task_record(task_id):
    db = get_db()
    task = db.execute("SELECT status FROM tasks WHERE id = ?", [task_id]).fetchone()
    if task and task['status'] in ['success', 'failure', 'paused']:
        celery.control.revoke(task_id, terminate=True, signal='SIGKILL')
        db.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        db.commit()
        return jsonify({"success": True, "message": "任务记录已删除。"})
    return jsonify({"error": "只能删除已完成、失败或暂停的任务记录。"}), 400

@oci_bp.route('/api/tasks/<task_id>/stop', methods=['POST'])
@login_required
def stop_task(task_id):
    celery.control.revoke(task_id, terminate=True, signal='SIGKILL')
    
    task_data = query_db('SELECT result FROM tasks WHERE id = ?', [task_id], one=True)
    if task_data and task_data['result']:
        try:
            result_json = json.loads(task_data['result'])
            result_json['last_message'] = '任务已被用户手动暂停。'
            if 'run_id' in result_json:
                del result_json['run_id']
            new_result = json.dumps(result_json)
        except (json.JSONDecodeError, TypeError):
            new_result = '{"last_message": "任务已被用户手动暂停。"}'
    else:
        new_result = '{"last_message": "任务已被用户手动暂停。"}'
        
    _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('paused', new_result, task_id))
    return jsonify({"success": True, "message": f"任务 {task_id} 已被暂停。"})

@oci_bp.route('/api/tasks/resume', methods=['POST'])
@login_required
def resume_tasks():
    data = request.json
    task_ids = data.get('task_ids', [])
    if not task_ids:
        return jsonify({"error": "未提供任何任务ID"}), 400

    resumed_count = 0
    failed_tasks = []
    profiles = load_profiles().get("profiles", {})
    
    for task_id in task_ids:
        task = query_db('SELECT result, account_alias FROM tasks WHERE id = ? AND status = ?', [task_id, 'paused'], one=True)
        if not task:
            failed_tasks.append(task_id)
            continue
        
        alias = task['account_alias']
        profile_config = profiles.get(alias)

        if not profile_config:
            failed_tasks.append(task_id)
            _db_execute_celery("UPDATE tasks SET status = ?, result = ?, completed_at = ? WHERE id = ?", ('failure', '任务因关联的账号配置被删除而恢复失败。', datetime.datetime.now(timezone.utc).isoformat(), task_id))
            continue

        try:
            result_json = json.loads(task['result'])
            original_details = result_json.get('details')
            if not original_details:
                raise ValueError("任务数据中缺少 'details' 字段")
            
            result_json['last_message'] = "任务已手动恢复，继续执行..."
            new_run_id = str(uuid.uuid4())
            result_json['run_id'] = new_run_id

            _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('running', json.dumps(result_json), task_id))
            
            auto_bind_domain = original_details.get('auto_bind_domain', False)
            _snatch_instance_task.delay(task_id, profile_config, alias, original_details, new_run_id, auto_bind_domain)

            resumed_count += 1
        except Exception as e:
            logging.error(f"恢复任务 {task_id} 失败: {e}")
            failed_tasks.append(task_id)
            _db_execute_celery('UPDATE tasks SET status = ?, result = ?, completed_at = ? WHERE id = ?', ('failure', f'手动恢复任务失败: {e}', datetime.datetime.now(timezone.utc).isoformat(), task_id))

    message = f"成功恢复 {resumed_count} 个任务。"
    if failed_tasks:
        message += f" {len(failed_tasks)} 个任务恢复失败: {', '.join(failed_tasks)}"
    
    return jsonify({"success": True, "message": message})

@oci_bp.route("/api/session", methods=["POST", "GET", "DELETE"])
@login_required
@timeout(20)
def oci_session_route():
    try:
        if request.method == "POST":
            alias = request.json.get("alias")
            profiles = load_profiles().get("profiles", {})
            if not alias or alias not in profiles: return jsonify({"error": "无效的账号别名"}), 400
            
            profile_config = profiles.get(alias)
            session['oci_profile_alias'] = alias
            g.api_selected_alias = alias

            _, error = get_oci_clients(profile_config, validate=True)
            if error:
                session.pop('oci_profile_alias', None)
                g.pop('api_selected_alias', None)
                return jsonify({"error": f"连接验证失败: {error}"}), 400
            
            proxy_info = profile_config.get('proxy')
            if proxy_info:
                success_message = f"连接成功! 当前账号: {alias} (通过代理: {proxy_info})"
            else:
                success_message = f"连接成功! 当前账号: {alias} (未使用代理)"

            can_create = bool(profile_config.get('default_ssh_public_key'))
            return jsonify({
                "success": True, 
                "alias": alias, 
                "can_create": can_create,
                "message": success_message
            })

        if request.method == "GET":
            alias = session.get('oci_profile_alias')
            if alias:
                can_create = bool(load_profiles().get("profiles", {}).get(alias, {}).get('default_ssh_public_key'))
                return jsonify({"logged_in": True, "alias": alias, "can_create": can_create})
            return jsonify({"logged_in": False})
        if request.method == "DELETE":
            session.pop('oci_profile_alias', None)
            g.pop('api_selected_alias', None)
            return jsonify({"success": True})
    except TimeoutException:
        session.pop('oci_profile_alias', None)
        g.pop('api_selected_alias', None)
        return jsonify({"error": "连接 OCI 验证超时，请检查网络或API密钥设置。"}), 504
    except Exception as e:
        session.pop('oci_profile_alias', None)
        g.pop('api_selected_alias', None)
        return jsonify({"error": str(e)}), 500

@oci_bp.route('/api/instances', defaults={'alias': None})
@oci_bp.route('/api/<alias>/instances')
@login_required
@timeout(30)
def get_instances(alias):
    try:
        if alias is None:
            alias = session.get('oci_profile_alias')
            if not alias:
                return jsonify({"error": "请先选择一个OCI账号"}), 403

        profile_config = load_profiles().get("profiles", {}).get(alias)
        if not profile_config:
            return jsonify({"error": f"账号 '{alias}' 未找到"}), 404
        clients, error = get_oci_clients(profile_config, validate=False)
        if error:
            return jsonify({"error": error}), 500
        
        compute_client, vnet_client, bs_client = clients['compute'], clients['vnet'], clients['bs']
        compartment_id = profile_config['tenancy']

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
    if alias is None: alias = session.get('oci_profile_alias') or g.get('api_selected_alias', 'N/A')
    utc_time = datetime.datetime.now(timezone.utc).isoformat()
    db.execute('INSERT INTO tasks (id, type, name, status, result, created_at, account_alias) VALUES (?, ?, ?, ?, ?, ?, ?)',
               (task_id, task_type, task_name, 'pending', '', utc_time, alias))
    db.commit()
    return task_id

@oci_bp.route('/api/instance-action', methods=['POST'], defaults={'alias': None})
@oci_bp.route('/api/<alias>/instance-action', methods=['POST'])
@login_required
@timeout(10)
def instance_action(alias):
    try:
        if alias is None:
            alias = session.get('oci_profile_alias')
            if not alias:
                return jsonify({"error": "请先选择一个OCI账号"}), 403
        
        profile_config = load_profiles().get("profiles", {}).get(alias)
        if not profile_config:
            return jsonify({"error": f"账号 '{alias}' 未找到"}), 404

        data = request.json
        action, instance_id = data.get('action'), data.get('instance_id')
        if not action or not instance_id: return jsonify({"error": "缺少 action 或 instance_id"}), 400
        
        task_name = f"{action} on {data.get('instance_name', instance_id[-12:])}"
        task_id = _create_task_entry('action', task_name, alias)
        
        config_with_alias = profile_config.copy()
        config_with_alias['alias'] = alias

        data['_source'] = 'web'

        _instance_action_task.delay(task_id, config_with_alias, action, instance_id, data)
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

@oci_bp.route('/api/available-shapes')
@login_required
@oci_clients_required
@timeout(45)
def get_available_shapes():
    try:
        os_name_version = request.args.get('os_name_version')
        if not os_name_version:
            return jsonify({"error": "缺少 os_name_version 参数"}), 400

        os_name, os_version = os_name_version.split('-')
        compute_client = g.oci_clients['compute']
        tenancy_ocid = g.oci_config['tenancy']
        
        logging.info(f"Fetching all shapes for tenancy {tenancy_ocid}...")
        all_shapes = oci.pagination.list_call_get_all_results(
            compute_client.list_shapes,
            compartment_id=tenancy_ocid
        ).data
        logging.info(f"Found {len(all_shapes)} total shapes.")

        architecture_shapes = []
        for shape in all_shapes:
            if shape.shape.startswith('VM.') and hasattr(shape, 'processor_description') and shape.processor_description:
                proc_desc = shape.processor_description.lower()
                if 'ampere' in proc_desc or 'amd' in proc_desc:
                    architecture_shapes.append(shape.shape)
        
        logging.info(f"Found {len(architecture_shapes)} ARM/AMD Virtual Machine shapes: {architecture_shapes}")

        valid_shapes_for_os = []
        for shape_name in architecture_shapes:
            try:
                images = compute_client.list_images(
                    tenancy_ocid,
                    operating_system=os_name,
                    operating_system_version=os_version,
                    shape=shape_name,
                    limit=1
                ).data
                if images:
                    valid_shapes_for_os.append(shape_name)
            except ServiceError as se:
                logging.warning(f"ServiceError when checking image compatibility for shape {shape_name}: {se.message}")
                continue
        
        logging.info(f"Found {len(valid_shapes_for_os)} shapes compatible with {os_name_version}: {valid_shapes_for_os}")
        
        valid_shapes_for_os.sort(key=lambda s: ('E2.1.Micro' not in s and 'A1.Flex' not in s, s))

        return jsonify(valid_shapes_for_os)

    except TimeoutException:
        return jsonify({"error": "获取可用实例规格超时。"}), 504
    except Exception as e:
        logging.error(f"Failed to get available shapes: {e}", exc_info=True)
        return jsonify({"error": f"获取可用实例规格失败: {e}"}), 500

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
        _update_instance_details_task.delay(task_id, g.oci_config, data)
        return jsonify({"message": f"'{action}' 请求已提交...", "task_id": task_id})
    except (sqlite3.OperationalError, TimeoutException) as e:
        if isinstance(e, TimeoutException) or "database is locked" in str(e):
            return jsonify({"error": "请求超时或数据库繁忙，请稍后重-试。"}), 503
        raise
    except Exception as e:
        return jsonify({"error": f"提交实例更新任务失败: {e}"}), 500

# --- ✨ MODIFICATION START ✨ ---
# 1. 删除旧的 'get_security_list' 函数 (已删除)

# 2. 新增 'get_network_resources' 路由，用于获取VCN和安全列表
@oci_bp.route('/api/network/resources')
@login_required
@oci_clients_required
@timeout(45)
def get_network_resources():
    try:
        vnet_client = g.oci_clients['vnet']
        tenancy_ocid = g.oci_config['tenancy']
        
        vcns = oci.pagination.list_call_get_all_results(
            vnet_client.list_vcns,
            compartment_id=tenancy_ocid
        ).data
        
        network_data = []
        for vcn in vcns:
            if vcn.lifecycle_state != 'AVAILABLE':
                continue
            
            security_lists = oci.pagination.list_call_get_all_results(
                vnet_client.list_security_lists,
                compartment_id=tenancy_ocid,
                vcn_id=vcn.id
            ).data
            
            sl_list = [
                {"id": sl.id, "display_name": sl.display_name}
                for sl in security_lists
                if sl.lifecycle_state == 'AVAILABLE'
            ]
            
            if sl_list:
                network_data.append({
                    "vcn_id": vcn.id,
                    "vcn_name": vcn.display_name,
                    "security_lists": sorted(sl_list, key=lambda x: x['display_name'])
                })
                
        return jsonify(sorted(network_data, key=lambda x: x['vcn_name']))
    except TimeoutException:
        return jsonify({"error": "获取网络资源列表超时。"}), 504
    except Exception as e:
        return jsonify({"error": f"获取网络资源失败: {e}"}), 500

# 3. 新增 'get_security_list_details' 路由，用于获取特定列表的规则
@oci_bp.route('/api/network/security-list/<security_list_id>')
@login_required
@oci_clients_required
@timeout(20)
def get_security_list_details(security_list_id):
    try:
        vnet_client = g.oci_clients['vnet']
        security_list = vnet_client.get_security_list(security_list_id).data
        return jsonify(json.loads(str(security_list)))
    except TimeoutException:
        return jsonify({"error": "获取安全列表详情超时。"}), 504
    except Exception as e:
        return jsonify({"error": f"获取安全列表详情失败: {e}"}), 500
# --- ✨ MODIFICATION END ✨ ---

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

@oci_bp.route('/api/launch-instance', methods=['POST'], defaults={'alias': None, 'endpoint': 'launch-instance'})
@oci_bp.route('/api/<alias>/<endpoint>', methods=['POST'])
@login_required
@timeout(30)
def launch_instance(alias, endpoint):
    try:
        if endpoint not in ["create-instance", "snatch-instance", "launch-instance"]:
            return jsonify({"error": "无效的端点"}), 404
        
        if alias is None:
            alias = session.get('oci_profile_alias')
            if not alias:
                return jsonify({"error": "请先选择一个OCI账号"}), 403

        profile_config = load_profiles().get("profiles", {}).get(alias)
        if not profile_config:
            return jsonify({"error": f"账号 '{alias}' 未找到"}), 404
        clients, error = get_oci_clients(profile_config, validate=False)
        if error:
            return jsonify({"error": error}), 500

        data = request.json
        data.setdefault('os_name_version', 'Canonical Ubuntu-22.04')

        display_name = data.get('display_name_prefix', 'N/A')
        instance_count = data.get('instance_count', 1)
        shape = data.get('shape')
        auto_bind_domain = data.get('auto_bind_domain', False)
        
        compute_client = clients['compute']
        compartment_id = profile_config['tenancy']

        try:
            all_instances = oci.pagination.list_call_get_all_results(compute_client.list_instances, compartment_id=compartment_id).data
            active_instances = [
                inst for inst in all_instances 
                if inst.lifecycle_state not in ['TERMINATED', 'TERMINATING']
            ]
            
            if shape == 'VM.Standard.E2.1.Micro':
                existing_amd_count = sum(1 for inst in active_instances if inst.shape == shape)
                if (existing_amd_count + instance_count) > 2:
                    error_msg = f"免费账户最多只能创建2个AMD实例，您当前已有 {existing_amd_count} 个活动实例。"
                    return jsonify({"error": error_msg}), 400

        except Exception as e:
            logging.error(f"检查配额时发生严重错误: {e}")
            return jsonify({"error": f"检查配额时出错，请稍后重试: {e}"}), 500

        task_ids = []
        for i in range(instance_count):
            task_name = f"{display_name}-{i+1}" if instance_count > 1 else display_name
            task_id = _create_task_entry('snatch', task_name, alias)
            
            task_data = data.copy()
            task_data['display_name_prefix'] = task_name
            task_data['auto_bind_domain'] = auto_bind_domain
            
            run_id = str(uuid.uuid4())
            _snatch_instance_task.delay(task_id, profile_config, alias, task_data, run_id, auto_bind_domain)
            task_ids.append(task_id)
            
        return jsonify({"message": f"已提交 {instance_count} 个抢占实例任务...", "task_ids": task_ids})

    except (sqlite3.OperationalError, TimeoutException) as e:
        if isinstance(e, TimeoutException) or "database is locked" in str(e):
            return jsonify({"error": "请求超时或数据库繁忙，请稍后重试。"}), 503
        raise
    except Exception as e:
        logging.error(f"提交抢占任务失败: {e}")
        return jsonify({"error": f"提交抢占任务失败: {e}"}), 500

@oci_bp.route('/api/task_status/<task_id>')
@login_required
def task_status(task_id):
    task = query_db('SELECT status, result, type FROM tasks WHERE id = ?', [task_id], one=True)
    if task:
        return jsonify({'status': task['status'], 'result': task['result'], 'type': task['type']})
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
        
        _db_execute_celery('UPDATE tasks SET status = ?, result = ?, completed_at = ? WHERE id = ?', ('success', result_message, datetime.datetime.now(timezone.utc).isoformat(), task_id))
    except Exception as e:
        _db_execute_celery('UPDATE tasks SET status = ?, result = ?, completed_at = ? WHERE id = ?', ('failure', f"❌ 操作失败: {e}", datetime.datetime.now(timezone.utc).isoformat(), task_id))

@celery.task
def _instance_action_task(task_id, profile_config, action, instance_id, data):
    _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('running', '正在执行操作...', task_id))
    try:
        clients, error = get_oci_clients(profile_config, validate=False)
        if error: raise Exception(error)
        compute_client, vnet_client = clients['compute'], clients['vnet']
        
        instance = compute_client.get_instance(instance_id).data
        instance_name = instance.display_name
        
        alias = profile_config.get('alias', '未知账户')

        action_map = {"START": ("START", "RUNNING"), "STOP": ("STOP", "STOPPED"), "RESTART": ("SOFTRESET", "RUNNING")}
        action_upper = action.upper()
        result_message = ""
        task_title = f"{action_upper} on {instance_name}"

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
            
            dns_update_msg = _update_cloudflare_dns(instance_name, new_pub_ip.ip_address, 'A')
            result_message += f"\n{dns_update_msg}"

        elif action_upper == "ASSIGNIPV6":
            vnic_id = data.get('vnic_id')
            if not vnic_id: raise Exception("缺少 vnic_id")
            
            _enable_ipv6_networking(task_id, vnet_client, vnic_id)
            
            _db_execute_celery('UPDATE tasks SET result=? WHERE id=?', ('网络配置完成，正在为实例分配IPv6地址...', task_id))

            new_ipv6 = vnet_client.create_ipv6(CreateIpv6Details(vnic_id=vnic_id)).data
            result_message = f"✅ 已成功分配IPv6地址: {new_ipv6.ip_address}"

            dns_update_msg = _update_cloudflare_dns(instance_name, new_ipv6.ip_address, 'AAAA')
            result_message += f"\n{dns_update_msg}"

        else: raise Exception(f"未知的操作: {action}")
        
        _db_execute_celery('UPDATE tasks SET status = ?, result = ?, completed_at = ? WHERE id = ?', ('success', result_message, datetime.datetime.now(timezone.utc).isoformat(), task_id))
        
        if data.get('_source') != 'web':
            tg_msg = (f"🔔 *任务完成通知*\n\n"
                      f"*账户*: `{alias}`\n"
                      f"*任务*: `{task_title}`\n\n"
                      f"*结果*:\n{result_message}")
            send_tg_notification(tg_msg)

    except Exception as e:
        alias = profile_config.get('alias', '未知账户')
        task_title = f"{action.upper()} on instance"
        error_message = f"❌ 操作失败: {e}"
        _db_execute_celery('UPDATE tasks SET status = ?, result = ?, completed_at = ? WHERE id = ?', ('failure', error_message, datetime.datetime.now(timezone.utc).isoformat(), task_id))
        
        if data.get('_source') != 'web':
            tg_msg = (f"🔔 *任务失败通知*\n\n"
                      f"*账户*: `{alias}`\n"
                      f"*任务*: `{task_title}`\n\n"
                      f"*原因*:\n`{e}`")
            send_tg_notification(tg_msg)

@celery.task
def _snatch_instance_task(task_id, profile_config, alias, details, run_id, auto_bind_domain=False):
    
    task_data = query_db('SELECT result FROM tasks WHERE id = ?', [task_id], one=True)
    try:
        status_data = json.loads(task_data['result']) if task_data and task_data['result'] else {}
    except (json.JSONDecodeError, TypeError):
        status_data = {}

    if not status_data or 'details' not in status_data:
        status_data['details'] = details
        status_data['start_time'] = datetime.datetime.now(timezone.utc).isoformat()
        status_data['attempt_count'] = 0
        status_data['last_message'] = "抢占任务准备中..."

    task_details = status_data.get('details', {})
    task_details.setdefault('boot_volume_size', 50)
    if task_details.get('shape') == 'VM.Standard.E2.1.Micro':
        task_details['ocpus'] = 1
        task_details['memory_in_gbs'] = 1
    status_data['details'] = task_details

    status_data['details']['account_alias'] = alias
    status_data['run_id'] = run_id
    
    _db_execute_celery('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('running', json.dumps(status_data), task_id))
    
    try:
        clients, error = get_oci_clients(profile_config, validate=False)
        if error: raise Exception(error)
        compute_client, identity_client, vnet_client = clients['compute'], clients['identity'], clients['vnet']
        tenancy_ocid, ssh_key = profile_config.get('tenancy'), profile_config.get('default_ssh_public_key')
        if not ssh_key: raise Exception("账号配置缺少默认SSH公钥")

        ad_objects = identity_client.list_availability_domains(tenancy_ocid).data
        if not ad_objects:
            raise Exception("无法获取可用性域列表。")
        availability_domains = [ad.name for ad in ad_objects]
        
        subnet_id = _ensure_subnet_in_profile(task_id, alias, vnet_client, tenancy_ocid)
        
        os_name, os_version = details['os_name_version'].split('-')
        shape = details['shape']
        
        status_data['last_message'] = '正在查找兼容的系统镜像...'
        _db_execute_celery('UPDATE tasks SET result = ? WHERE id = ?', (json.dumps(status_data), task_id))
        
        images = oci.pagination.list_call_get_all_results(compute_client.list_images, tenancy_ocid, operating_system=os_name, operating_system_version=os_version, shape=shape, sort_by="TIMECREATED", sort_order="DESC").data
        if not images: raise Exception(f"未找到适用于 {os_name} {os_version} 的兼容镜像")
        
        user_provided_password = details.get('instance_password', '').strip()
        if user_provided_password:
            instance_password = user_provided_password
        else:
            instance_password = generate_oci_password()

        user_script = details.get('startup_script', '')
        user_data_encoded = get_user_data(instance_password, user_script)
        
        # --- ✨ MODIFICATION START ✨ ---
        # 根据请求，默认禁用 Oracle Cloud Agent 的两个插件
        # 1. "计算实例监控" (Compute Instance Monitoring)
        # 2. "自定义日志监控" (Custom Logs Monitoring)
        
        # 配置 "自定义日志监控" 插件
        plugins_config_list = [
            oci.core.models.InstanceAgentPluginConfigDetails(
                name="Custom Logs Monitoring",
                desired_state="DISABLED"
            )
        ]
        
        # 创建 Agent 配置
        # is_monitoring_disabled=True 对应于禁用 "计算实例监控"
        agent_config_details = oci.core.models.LaunchInstanceAgentConfigDetails(
            is_monitoring_disabled=True,  # 禁用 "计算实例监控"
            is_management_disabled=False, # 保持 "管理代理" (Management Agent) 为默认设置（图上未勾选）
            plugins_config=plugins_config_list # 传入 "自定义日志监控" 的禁用配置
        )
        # --- ✨ MODIFICATION END ✨ ---
        
        base_launch_details = {
            "compartment_id": tenancy_ocid,
            "shape": shape, 
            "display_name": details.get('display_name_prefix', 'snatch-instance'),
            "create_vnic_details": CreateVnicDetails(subnet_id=subnet_id, assign_public_ip=True),
            "metadata": {"ssh_authorized_keys": ssh_key, "user_data": user_data_encoded},
            "source_details": InstanceSourceViaImageDetails(image_id=images[0].id, boot_volume_size_in_gbs=details['boot_volume_size']),
            "shape_config": LaunchInstanceShapeConfigDetails(ocpus=details.get('ocpus'), memory_in_gbs=details.get('memory_in_gbs')) if "Flex" in shape else None,
            # --- ✨ MODIFICATION START ✨ ---
            "agent_config": agent_config_details
            # --- ✨ MODIFICATION END ✨ ---
        }

    except Exception as e:
        _db_execute_celery('UPDATE tasks SET status = ?, result = ?, completed_at = ? WHERE id = ?', ('failure', f"❌ 抢占任务准备阶段失败: {e}", datetime.datetime.now(timezone.utc).isoformat(), task_id))
        return

    last_update_time = time.time()
    attempt_count = status_data.get('attempt_count', 0)

    while True:
        current_task_data = query_db('SELECT result, status FROM tasks WHERE id = ?', [task_id], one=True)
        if not current_task_data:
            logging.warning(f"Task {task_id} not found in DB. Worker will exit.")
            return

        if current_task_data['status'] != 'running':
            logging.info(f"Task {task_id} status is '{current_task_data['status']}', not 'running'. Worker will exit.")
            return
            
        try:
            current_result_json = json.loads(current_task_data['result'])
            db_run_id = current_result_json.get('run_id')
            if db_run_id != run_id:
                logging.info(f"Task {task_id} has a new run_id ({db_run_id}). This worker ({run_id}) will exit.")
                return
        except (json.JSONDecodeError, TypeError, KeyError):
            logging.error(f"Could not verify run_id for task {task_id}. Data might be corrupt. Exiting.")
            _db_execute_celery('UPDATE tasks SET status = ?, result = ?, completed_at = ? WHERE id = ?', ('failure', "任务数据损坏，无法继续执行。", datetime.datetime.now(timezone.utc).isoformat(), task_id))
            return

        attempt_count += 1
        status_data['attempt_count'] = attempt_count
        force_update = False
        
        current_ad_index = (attempt_count - 1) % len(availability_domains)
        current_ad_name = availability_domains[current_ad_index]
        
        if 'details' not in status_data: status_data['details'] = {}
        status_data['details']['ad'] = current_ad_name
        
        try:
            launch_details_dict = base_launch_details.copy()
            launch_details_dict['availability_domain'] = current_ad_name
            launch_details = LaunchInstanceDetails(**launch_details_dict)
            
            status_data['last_message'] = f"正在 {current_ad_name} 中尝试..."
            _db_execute_celery('UPDATE tasks SET result = ? WHERE id = ?', (json.dumps(status_data), task_id))
            force_update = True 
            
            instance = compute_client.launch_instance(launch_details).data
            
            status_data['last_message'] = f"第 {status_data['attempt_count']} 次尝试成功！实例 {instance.display_name} 正在置备..."
            _db_execute_celery('UPDATE tasks SET result = ? WHERE id = ?', (json.dumps(status_data), task_id))
            oci.wait_until(compute_client, compute_client.get_instance(instance.id), 'lifecycle_state', 'RUNNING', max_wait_seconds=600)
            
            public_ip = "获取中..."
            try:
                vnic_attachments = oci.pagination.list_call_get_all_results(compute_client.list_vnic_attachments, compartment_id=tenancy_ocid, instance_id=instance.id).data
                if vnic_attachments:
                    vnic = vnet_client.get_vnic(vnic_attachments[0].vnic_id).data
                    public_ip = vnic.public_ip or "无"
            except Exception as ip_e:
                public_ip = "获取失败"
            
            db_msg = f"🎉 抢占成功 (第 {status_data['attempt_count']} 次尝试)!\n- 实例名: {instance.display_name}\n- 可用区: {current_ad_name}\n- 公网IP: {public_ip}\n- 登陆用户名：ubuntu\n- 密码：{instance_password}"
            
            dns_update_msg = ""
            if auto_bind_domain and public_ip != "无" and public_ip != "获取失败":
                dns_update_msg = _update_cloudflare_dns(instance.display_name, public_ip, 'A')
                db_msg += f"\n{dns_update_msg}"

            _db_execute_celery('UPDATE tasks SET status = ?, result = ?, completed_at = ? WHERE id = ?', ('success', db_msg, datetime.datetime.now(timezone.utc).isoformat(), task_id))
            
            duration_str = "未知"
            try:
                start_time = datetime.datetime.fromisoformat(status_data['start_time'])
                end_time = datetime.datetime.now(timezone.utc)
                duration = end_time - start_time
                duration_str = _format_timedelta(duration)
            except (KeyError, TypeError):
                logging.warning(f"无法为任务 {task_id} 计算总用时。")

            result_for_tg = (f"🎉 抢占成功 (第 {status_data['attempt_count']} 次尝试)!\n"
                             f"- 总用时: {duration_str}\n"
                             f"- 实例名: {instance.display_name}\n"
                             f"- 可用区: {current_ad_name}\n"
                             f"- 公网IP: {public_ip}\n"
                             f"- 登陆用户名: ubuntu\n"
                             f"- 密码: {instance_password}")
            
            if dns_update_msg:
                result_for_tg += f"\n{dns_update_msg}"

            tg_msg = (f"🔔 *任务完成通知*\n\n"
                      f"*账户*: `{alias}`\n"
                      f"*任务名称*: `{details.get('display_name_prefix', 'snatch-instance')}`\n\n"
                      f"*结果*:\n{result_for_tg}")
            
            send_tg_notification(tg_msg)
            
            return
        except ServiceError as e:
            force_update = True
            if e.status == 429 or "TooManyRequests" in e.code or "Out of host capacity" in str(e.message) or "LimitExceeded" in e.code:
                status_data['last_message'] = f"在 {current_ad_name} 中资源不足 ({e.code})"
            else:
                status_data['last_message'] = f"在 {current_ad_name} 中遇到API错误 ({e.code})"
        except Exception as e:
            force_update = True
            status_data['last_message'] = f"在 {current_ad_name} 中遇到未知错误 ({str(e)[:50]}...)"
        
        task_record_check = query_db('SELECT status FROM tasks WHERE id = ?', [task_id], one=True)
        if not task_record_check or task_record_check['status'] not in ['running', 'pending']:
            logging.info(f"Snatching task {task_id} has been stopped or paused. Exiting loop.")
            return

        delay = random.randint(details.get('min_delay', 30), details.get('max_delay', 90))
        status_data['last_message'] += f"，将在 {delay} 秒后重试..."
        current_time = time.time()
        if (current_time - last_update_time > 5) or force_update:
            _db_execute_celery('UPDATE tasks SET result = ? WHERE id = ?', (json.dumps(status_data), task_id))
            last_update_time = current_time
        time.sleep(delay)
