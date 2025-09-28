# -*- coding: utf-8 -*-
import boto3, os, threading, time, queue, json, logging, math
from botocore.exceptions import ClientError
from botocore.config import Config
from flask import Blueprint, render_template, jsonify, request, session, g, redirect, url_for, current_app
from functools import wraps

# --- Blueprint Setup ---
aws_bp = Blueprint('aws', __name__, template_folder='../templates', static_folder='../static')

# --- Constants ---
KEY_FILE = "key.txt"
DATABASE = "aws_tasks.db" # 数据库文件名
QUOTA_CODE = 'L-1216C47A'
QUOTA_REGION = 'us-east-1'
REGION_MAPPING = {
    "af-south-1": "af-south-1 (非洲（开普敦）)", "ap-east-1": "ap-east-1 (亚太地区（香港）)", "ap-northeast-1": "ap-northeast-1 (亚太地区（东京）)",
    "ap-northeast-2": "ap-northeast-2 (亚太地区（首尔）)", "ap-northeast-3": "ap-northeast-3 (亚太地区（大阪）)", "ap-south-1": "ap-south-1 (亚太地区（孟买）)",
    "ap-southeast-1": "ap-southeast-1 (亚太地区（新加坡）)", "ap-southeast-2": "ap-southeast-2 (亚太地区（悉尼）)", "ca-central-1": "ca-central-1 (加拿大（中部）)",
    "eu-central-1": "eu-central-1 (欧洲地区（法兰克福）)", "eu-central-2": "eu-central-2 (欧洲（苏黎世）)", "eu-north-1": "eu-north-1 (欧洲地区（斯德哥尔摩）)",
    "eu-south-1": "eu-south-1 (欧洲地区（米兰）)", "eu-west-1": "eu-west-1 (欧洲地区（爱尔兰）)", "eu-west-2": "eu-west-2 (欧洲地区（伦敦）)",
    "eu-west-3": "eu-west-3 (欧洲地区（巴黎）)", "sa-east-1": "sa-east-1 (南美洲（圣保罗）)", "us-east-1": "us-east-1 (美国东部（弗吉尼亚州北部）)",
    "us-east-2": "us-east-2 (美国东部（俄亥俄州）)", "us-west-1": "us-west-1 (美国西部（加利福尼亚北部）)", "us-west-2": "us-west-2 (美国西部（俄勒冈州）)"
}
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(name)s:%(message)s')
task_logs = {}

# --- DB and Helpers ---
def init_db():
    db = sqlite3.connect(DATABASE)
    # 数据库结构可以保持简单，因为AWS面板不使用它来存储任务
    db.cursor().executescript("CREATE TABLE dummy (id INTEGER PRIMARY KEY);")
    db.commit()
    db.close()
    logging.info("AWS dummy database initialized.")

def get_boto_config(): return Config(connect_timeout=15, retries={'max_attempts': 2})
def load_keys(keyfile):
    if not os.path.exists(keyfile): return []
    with open(keyfile, "r", encoding="utf-8") as f:
        return [{"name": p[0], "access_key": p[1], "secret_key": p[2]} for line in f if len(p := line.strip().split("----")) == 3]
def save_keys(keyfile, keys):
    with open(keyfile, "w", encoding="utf-8") as f:
        for key in keys: f.write(f"{key['name']}----{key['access_key']}----{key['secret_key']}\n")
def log_task(task_id, message):
    if task_id not in task_logs: task_logs[task_id] = queue.Queue()
    task_logs[task_id].put(message)
def handle_aws_error(e, task_id=None):
    error_message = f"AWS API 错误: {e}"
    if isinstance(e, ClientError):
        error_code = e.response.get("Error", {}).get("Code")
        error_message = f"AWS API 错误: {error_code} - {e.response.get('Error', {}).get('Message')}"
    logging.error(f"Task({task_id}): {error_message}")
    if task_id: log_task(task_id, f"--- 任务失败: {error_message} ---")
    return error_message

# --- Decorators ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_logged_in" not in session: return jsonify({"error": "用户未登录"}), 401
        return f(*args, **kwargs)
    return decorated_function
def aws_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'aws_access_key_id' not in session: return jsonify({"error": "请先选择一个AWS账户"}), 403
        g.aws_access_key_id, g.aws_secret_access_key = session['aws_access_key_id'], session['aws_secret_access_key']
        return f(*args, **kwargs)
    return decorated_function

# --- Background Task Functions ---
def create_open_security_group(ec2_client, task_id):
    try:
        vpcs = ec2_client.describe_vpcs(Filters=[{'Name': 'isDefault', 'Values': ['true']}])
        if not vpcs['Vpcs']: raise Exception("未找到默认VPC。")
        default_vpc_id = vpcs['Vpcs'][0]['VpcId']
        group_name = 'OpenAllPorts'
        log_task(task_id, f"正在创建名为 {group_name} 的安全组...")
        response = ec2_client.create_security_group(GroupName=group_name, Description='Security group to allow all traffic', VpcId=default_vpc_id)
        security_group_id = response['GroupId']
        log_task(task_id, f"安全组 {security_group_id} 创建成功。正在配置入站规则...")
        ec2_client.authorize_security_group_ingress(GroupId=security_group_id, IpPermissions=[{'IpProtocol': '-1', 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}])
        log_task(task_id, f"安全组规则配置完成，允许所有端口访问。")
        return security_group_id
    except ClientError as e:
        if "already exists" in str(e):
            log_task(task_id, f"安全组 {group_name} 已存在，正在获取其ID...")
            groups = ec2_client.describe_security_groups(GroupNames=[group_name])
            security_group_id = groups['SecurityGroups'][0]['GroupId']
            log_task(task_id, f"已获取存在的安全组ID: {security_group_id}")
            return security_group_id
        else: raise e
def configure_lightsail_firewall(lightsail_client, instance_name, task_id):
    try:
        log_task(task_id, f"等待实例 {instance_name} 进入可操作状态...")
        waiter = lightsail_client.get_waiter('instance_running')
        waiter.wait(instanceName=instance_name, WaiterConfig={'Delay': 15, 'MaxAttempts': 20})
        log_task(task_id, f"实例 {instance_name} 已运行，正在配置防火墙...")
        lightsail_client.put_instance_public_ports(instanceName=instance_name, portInfos=[{'fromPort': 0, 'toPort': 65535, 'protocol': 'all'}])
        log_task(task_id, f"成功为实例 {instance_name} 配置防火墙，开放所有端口。")
    except Exception as e:
        log_task(task_id, f"为实例 {instance_name} 配置防火墙失败: {str(e)}")
def create_instance_task(service, task_id, access_key, secret_key, region, instance_type, user_data, disk_size=None):
    log_task(task_id, f"{service.upper()} 任务启动: 区域 {region}, 类型/套餐 {instance_type}")
    try:
        if service == 'ec2':
            client = boto3.client('ec2', region_name=region, aws_access_key_id=access_key, aws_secret_access_key=secret_key, config=get_boto_config())
            images = client.describe_images(Owners=['136693071363'], Filters=[{'Name': 'name', 'Values': ['debian-12-amd64-*']}, {'Name': 'state', 'Values': ['available']}])
            if not images['Images']: raise Exception("未找到Debian 12的AMI")
            ami_id = sorted(images['Images'], key=lambda x: x['CreationDate'], reverse=True)[0]['ImageId']
            log_task(task_id, f"使用AMI: {ami_id}")
            security_group_id = create_open_security_group(client, task_id)
            run_args = {'ImageId': ami_id, 'InstanceType': instance_type, 'MinCount': 1, 'MaxCount': 1, 'UserData': user_data, 'SecurityGroupIds': [security_group_id]}
            if disk_size:
                try:
                    disk_size_int = int(disk_size)
                    ami_details = client.describe_images(ImageIds=[ami_id])['Images'][0]
                    root_device_name = ami_details['RootDeviceName']
                    run_args['BlockDeviceMappings'] = [{'DeviceName': root_device_name, 'Ebs': {'VolumeSize': disk_size_int, 'VolumeType': 'gp3', 'DeleteOnTermination': True}}]
                except (ValueError, KeyError, IndexError) as e:
                    log_task(task_id, f"警告: 硬盘大小({disk_size})无效或无法获取AMI信息({e})。将使用默认大小。")
            instance = client.run_instances(**run_args)
            instance_id = instance['Instances'][0]['InstanceId']
            log_task(task_id, f"实例请求已发送, ID: {instance_id}")
            waiter = client.get_waiter('instance_running')
            waiter.wait(InstanceIds=[instance_id])
            desc = client.describe_instances(InstanceIds=[instance_id])
            ip = desc['Reservations'][0]['Instances'][0].get('PublicIpAddress', 'N/A')
            log_task(task_id, f"实例 {instance_id} 已运行, 公网 IP: {ip}")
        elif service == 'lightsail':
            client = boto3.client('lightsail', region_name=region, aws_access_key_id=access_key, aws_secret_access_key=secret_key, config=get_boto_config())
            blueprints = client.get_blueprints()
            debian_blueprints = sorted([bp for bp in blueprints['blueprints'] if 'debian' in bp['id'] and bp['isActive']], key=lambda x: x['version'], reverse=True)
            if not debian_blueprints: raise Exception("未找到可用的Debian蓝图")
            blueprint_id = debian_blueprints[0]['blueprintId']
            log_task(task_id, f"使用蓝图: {blueprint_id}")
            instance_name = f"lightsail-{region}-{int(time.time())}"
            client.create_instances(instanceNames=[instance_name], availabilityZone=f"{region}a", blueprintId=blueprint_id, bundleId=instance_type, userData=user_data)
            log_task(task_id, f"实例 {instance_name} 创建请求已发送。")
            configure_lightsail_firewall(client, instance_name, task_id)
        log_task(task_id, "--- 任务完成 ---")
    except Exception as e: handle_aws_error(e, task_id)
def activate_region_task(task_id, access_key, secret_key, region):
    log_task(task_id, f"开始激活区域 {region}...")
    try:
        client = boto3.client('account', region_name='us-east-1', aws_access_key_id=access_key, aws_secret_access_key=secret_key, config=get_boto_config())
        client.enable_region(RegionName=region)
        log_task(task_id, f"区域 {region} 激活请求已成功提交。"); log_task(task_id, "--- 任务完成 ---")
    except Exception as e: handle_aws_error(e, task_id)
def query_all_instances_task(task_id, access_key, secret_key):
    log_task(task_id, "开始查询所有已激活区域的实例...")
    try:
        ec2_client_main = boto3.client('ec2', region_name='us-east-1', aws_access_key_id=access_key, aws_secret_access_key=secret_key, config=get_boto_config())
        response = ec2_client_main.describe_regions(Filters=[{'Name': 'opt-in-status', 'Values': ['opt-in-not-required', 'opted-in']}])
        enabled_regions = [r['RegionName'] for r in response['Regions']]
        lightsail_regions_client = boto3.client('lightsail', region_name='us-east-1', aws_access_key_id=access_key, aws_secret_access_key=secret_key, config=get_boto_config())
        lightsail_regions = {r['name'] for r in lightsail_regions_client.get_regions()['regions']}
        total_found = 0
        for region in enabled_regions:
            log_task(task_id, f"正在查询区域: {region}...")
            try:
                ec2_client = boto3.client('ec2', region_name=region, aws_access_key_id=access_key, aws_secret_access_key=secret_key, config=get_boto_config())
                for r in ec2_client.describe_instances(Filters=[{'Name':'instance-state-name','Values':['pending','running','stopped']}])['Reservations']:
                    for i in r['Instances']:
                        instance_data = {"type": "EC2", "region": region, "id": i['InstanceId'], "name": next((t['Value'] for t in i.get('Tags',[]) if t['Key'] == 'Name'), i['InstanceId']), "state": i['State']['Name'], "ip": i.get('PublicIpAddress', 'N/A'), "launch_time": i.get('LaunchTime').isoformat() if i.get('LaunchTime') else None}
                        log_task(task_id, "FOUND_INSTANCE::" + json.dumps(instance_data)); total_found += 1
            except Exception as e:
                log_task(task_id, f"查询EC2实例失败({region}): {handle_aws_error(e)}")
            if region in lightsail_regions:
                try:
                    lightsail_client = boto3.client('lightsail', region_name=region, aws_access_key_id=access_key, aws_secret_access_key=secret_key, config=get_boto_config())
                    for i in lightsail_client.get_instances()['instances']:
                        instance_data = {"type": "Lightsail", "region": region, "id": i['name'], "name": i['name'], "state": i['state']['name'], "ip": i.get('publicIpAddress', 'N/A'), "launch_time": i.get('createdAt').isoformat() if i.get('createdAt') else None}
                        log_task(task_id, "FOUND_INSTANCE::" + json.dumps(instance_data)); total_found += 1
                except Exception as e:
                    log_task(task_id, f"查询Lightsail实例失败({region}): {handle_aws_error(e)}")
        log_task(task_id, f"所有区域查询完毕，共找到 {total_found} 个实例。"); log_task(task_id, "--- 任务完成 ---")
    except Exception as e: handle_aws_error(e, task_id)

# --- API Routes ---
@aws_bp.route("/")
@login_required
def aws_index():
    return render_template("aws.html")

@aws_bp.route("/api/accounts", methods=["GET", "POST"])
@login_required
def manage_accounts():
    if request.method == "GET":
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 5, type=int)
        all_keys = load_keys(KEY_FILE)
        all_keys.sort(key=lambda x: x['name'])
        total_accounts = len(all_keys)
        total_pages = math.ceil(total_accounts / limit)
        start = (page - 1) * limit
        end = start + limit
        paginated_keys = all_keys[start:end]
        return jsonify({
            "accounts": [{"name": k["name"]} for k in paginated_keys],
            "total_accounts": total_accounts,
            "total_pages": total_pages,
            "current_page": page
        })
    data = request.json; keys = load_keys(KEY_FILE)
    if any(k['name'] == data['name'] for k in keys): return jsonify({"error": "账户名称已存在"}), 400
    keys.append(data); save_keys(KEY_FILE, keys)
    return jsonify({"success": True, "name": data['name']}), 201

@aws_bp.route("/api/accounts/<name>", methods=["DELETE"])
@login_required
def delete_account(name):
    keys = load_keys(KEY_FILE); keys_to_keep = [k for k in keys if k['name'] != name]
    if len(keys) == len(keys_to_keep): return jsonify({"error": "账户未找到"}), 404
    save_keys(KEY_FILE, keys_to_keep)
    if session.get('account_name') == name:
        session.pop('account_name', None); session.pop('aws_access_key_id', None); session.pop('aws_secret_access_key', None)
    return jsonify({"success": True})

@aws_bp.route("/api/session", methods=["POST", "DELETE", "GET"])
@login_required
def aws_session():
    if request.method == "POST":
        name = request.json.get("name")
        account = next((k for k in load_keys(KEY_FILE) if k['name'] == name), None)
        if not account: return jsonify({"error": "账户未找到"}), 404
        session['account_name'], session['aws_access_key_id'], session['aws_secret_access_key'] = account['name'], account['access_key'], account['secret_key']
        return jsonify({"success": True, "name": account['name']})
    if request.method == "DELETE":
        session.pop('account_name', None); session.pop('aws_access_key_id', None); session.pop('aws_secret_access_key', None)
        return jsonify({"success": True})
    if 'account_name' in session: return jsonify({"logged_in": True, "name": session['account_name']})
    return jsonify({"logged_in": False})

@aws_bp.route("/api/regions")
@login_required
@aws_login_required
def get_regions():
    try:
        lightsail_client = boto3.client('lightsail', region_name='us-east-1', aws_access_key_id=g.aws_access_key_id, aws_secret_access_key=g.aws_secret_access_key, config=get_boto_config())
        lightsail_supported_regions = {r['name'] for r in lightsail_client.get_regions()['regions']}
        ec2_client = boto3.client('ec2', region_name='us-east-1', aws_access_key_id=g.aws_access_key_id, aws_secret_access_key=g.aws_secret_access_key, config=get_boto_config())
        ec2_regions_response = ec2_client.describe_regions(AllRegions=True)
        regions = []
        for r in ec2_regions_response['Regions']:
            region_code = r['RegionName']
            regions.append({
                "code": region_code, "name": REGION_MAPPING.get(region_code, region_code),
                "enabled": r['OptInStatus'] in ['opt-in-not-required', 'opted-in'], "supports_lightsail": region_code in lightsail_supported_regions
            })
        priority_regions = ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2']
        sorted_regions = sorted(regions, key=lambda r: (0 if r['code'] in priority_regions else 1, r['name']))
        return jsonify(sorted_regions)
    except Exception as e: return jsonify({"error": handle_aws_error(e)}), 500

@aws_bp.route("/api/instances")
@login_required
@aws_login_required
def get_instances():
    region = request.args.get("region")
    if not region: return jsonify({"error": "必须提供区域参数"}), 400
    instances = []
    try:
        ec2_client = boto3.client('ec2', region_name=region, aws_access_key_id=g.aws_access_key_id, aws_secret_access_key=g.aws_secret_access_key, config=get_boto_config())
        for r in ec2_client.describe_instances(Filters=[{'Name':'instance-state-name','Values':['pending','running','stopped']}])['Reservations']:
            for i in r['Instances']: instances.append({"type": "EC2", "region": region, "id": i['InstanceId'], "name": next((t['Value'] for t in i.get('Tags',[]) if t['Key'] == 'Name'), i['InstanceId']), "state": i['State']['Name'], "ip": i.get('PublicIpAddress', 'N/A'), "launch_time": i.get('LaunchTime').isoformat() if i.get('LaunchTime') else None})
        
        lightsail_regions_client = boto3.client('lightsail', region_name='us-east-1', aws_access_key_id=g.aws_access_key_id, aws_secret_access_key=g.aws_secret_access_key, config=get_boto_config())
        if region in {r['name'] for r in lightsail_regions_client.get_regions()['regions']}:
            lightsail_client = boto3.client('lightsail', region_name=region, aws_access_key_id=g.aws_access_key_id, aws_secret_access_key=g.aws_secret_access_key, config=get_boto_config())
            for i in lightsail_client.get_instances()['instances']: instances.append({"type": "Lightsail", "region": region, "id": i['name'], "name": i['name'], "state": i['state']['name'], "ip": i.get('publicIpAddress', 'N/A'), "launch_time": i.get('createdAt').isoformat() if i.get('createdAt') else None})
        return jsonify(instances)
    except Exception as e: return jsonify({"error": handle_aws_error(e)}), 500

@aws_bp.route("/api/instance-action", methods=["POST"])
@login_required
@aws_login_required
def instance_action():
    data = request.json
    action, region, instance_id, instance_type = data.get("action"), data.get("region"), data.get("instance_id"), data.get("instance_type")
    if not all([action, region, instance_id, instance_type]): return jsonify({"error": "缺少必要的操作参数"}), 400
    try:
        if instance_type == 'EC2':
            client = boto3.client('ec2', region_name=region, aws_access_key_id=g.aws_access_key_id, aws_secret_access_key=g.aws_secret_access_key, config=get_boto_config())
            if action == 'start': client.start_instances(InstanceIds=[instance_id])
            elif action == 'stop': client.stop_instances(InstanceIds=[instance_id])
            elif action == 'restart': client.reboot_instances(InstanceIds=[instance_id])
            elif action == 'delete': client.terminate_instances(InstanceIds=[instance_id])
            elif action == 'change-ip':
                addrs = client.describe_addresses(Filters=[{'Name': 'instance-id', 'Values': [instance_id]}])
                if addrs['Addresses']: client.release_address(AllocationId=addrs['Addresses'][0]['AllocationId'])
                new_eip = client.allocate_address(Domain='vpc')
                client.associate_address(InstanceId=instance_id, AllocationId=new_eip['AllocationId'])
                return jsonify({"success": True, "message": f"实例 {instance_id} 已成功更换 IP 为 {new_eip['PublicIp']}"})
        elif instance_type == 'Lightsail':
            client = boto3.client('lightsail', region_name=region, aws_access_key_id=g.aws_access_key_id, aws_secret_access_key=g.aws_secret_access_key, config=get_boto_config())
            if action == 'start': client.start_instance(instanceName=instance_id)
            elif action == 'stop': client.stop_instance(instanceName=instance_id)
            elif action == 'restart': client.reboot_instance(instanceName=instance_id)
            elif action == 'delete': client.delete_instance(instanceName=instance_id)
        return jsonify({"success": True, "message": f"实例 {instance_id} 的 {action} 请求已发送"})
    except Exception as e: return jsonify({"error": handle_aws_error(e)}), 500

@aws_bp.route("/api/ec2-instance-types")
@login_required
@aws_login_required
def get_ec2_instance_types():
    region = request.args.get("region")
    if not region: return jsonify({"error": "必须提供区域参数"}), 400
    try:
        client = boto3.client('ec2', region_name=region, aws_access_key_id=g.aws_access_key_id, aws_secret_access_key=g.aws_secret_access_key, config=get_boto_config())
        paginator_offerings = client.get_paginator('describe_instance_type_offerings')
        available_types = set()
        for page in paginator_offerings.paginate(LocationType='region', Filters=[{'Name': 'location', 'Values': [region]}]):
            for offering in page['InstanceTypeOfferings']: available_types.add(offering['InstanceType'])
        if not available_types: return jsonify([])
        paginator_types = client.get_paginator('describe_instance_types')
        detailed_types = []
        for i in range(0, len(list(available_types)), 100):
            chunk = list(available_types)[i:i + 100]
            for page in paginator_types.paginate(InstanceTypes=chunk):
                for inst_type in page['InstanceTypes']:
                    vcpus = inst_type.get('VCpuInfo', {}).get('DefaultVCpus', '?')
                    memory_mib = inst_type.get('MemoryInfo', {}).get('SizeInMiB', 0)
                    detailed_types.append({"value": inst_type['InstanceType'], "text": f"{inst_type['InstanceType']} ({vcpus}C / {round(memory_mib / 1024, 1)}G RAM)"})
        sorted_types = sorted(detailed_types, key=lambda x: x['value'])
        for t_name in ['t3.micro', 't2.micro']:
            if match := next((item for item in sorted_types if item['value'] == t_name), None): sorted_types.insert(0, sorted_types.pop(sorted_types.index(match)))
        return jsonify(sorted_types)
    except Exception as e: return jsonify({"error": handle_aws_error(e)}), 500

@aws_bp.route("/api/lightsail-bundles")
@login_required
@aws_login_required
def get_lightsail_bundles():
    region = request.args.get("region")
    if not region: return jsonify({"error": "必须提供区域参数"}), 400
    try:
        client = boto3.client('lightsail', region_name=region, aws_access_key_id=g.aws_access_key_id, aws_secret_access_key=g.aws_secret_access_key, config=get_boto_config())
        bundles = client.get_bundles()['bundles']
        return jsonify([{"id": b['bundleId'], "name": f"{b['name']} ({b['ramSizeInGb']}GB RAM, {b['diskSizeInGb']}GB 磁盘, ${b['price']}/月)"} for b in bundles if b['isActive']])
    except Exception as e: return jsonify({"error": handle_aws_error(e)}), 500

@aws_bp.route("/api/query-quota", methods=["POST"])
@login_required
def query_quota():
    data = request.json
    account = next((k for k in load_keys(KEY_FILE) if k['name'] == data.get("account_name")), None)
    if not account: return jsonify({"error": "账户未找到"}), 404
    try:
        client = boto3.client('service-quotas', region_name=data.get("region", QUOTA_REGION), aws_access_key_id=account['access_key'], aws_secret_access_key=account['secret_key'], config=get_boto_config())
        quota = client.get_service_quota(ServiceCode='ec2', QuotaCode=QUOTA_CODE)
        return jsonify({"quota": int(quota['Quota']['Value'])})
    except Exception as e: return jsonify({"error": handle_aws_error(e)})

@aws_bp.route("/api/instances/<service>", methods=["POST"])
@login_required
@aws_login_required
def start_create_instance(service):
    data = request.json
    instance_type = data.get("instance_type") if service == 'ec2' else data.get("bundle_id")
    task_id = f"{service}-{int(time.time())}"
    threading.Thread(target=create_instance_task, args=(service, task_id, g.aws_access_key_id, g.aws_secret_access_key, data["region"], instance_type, data["user_data"], data.get("disk_size"))).start()
    return jsonify({"success": True, "task_id": task_id})

@aws_bp.route("/api/activate-region", methods=["POST"])
@login_required
@aws_login_required
def start_activate_region():
    data = request.json
    region = data.get("region")
    task_id = f"activate-{region}-{int(time.time())}"
    threading.Thread(target=activate_region_task, args=(task_id, g.aws_access_key_id, g.aws_secret_access_key, region)).start()
    return jsonify({"success": True, "task_id": task_id})

@aws_bp.route("/api/query-all-instances", methods=["POST"])
@login_required
@aws_login_required
def start_query_all():
    task_id = f"query-all-{int(time.time())}"
    threading.Thread(target=query_all_instances_task, args=(task_id, g.aws_access_key_id, g.aws_secret_access_key)).start()
    return jsonify({"success": True, "task_id": task_id})

@aws_bp.route("/api/task/<task_id>/logs")
@login_required
def get_task_logs(task_id):
    logs = []
    if task_id in task_logs:
        while not task_logs[task_id].empty(): logs.append(task_logs[task_id].get())
    return jsonify({"logs": logs})
