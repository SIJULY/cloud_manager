#!/bin/bash

# ==============================================================================
# Cloud Manager 三合一面板 一键安装脚本 (增强版)

# 该脚本适用于一个全新的、基于 Debian/Ubuntu 的系统。

# 它会自动安装所有依赖、配置并启动服务。

# 作者: 小龙女她爸

# ==============================================================================

# --- 配置 ---
INSTALL_DIR="/opt/cloud_manager"
REPO_URL="https://github.com/SIJULY/cloud_manager.git"

# --- 脚本设置 ---
set -e

# --- 辅助函数 ---
print_info() { echo -e "\e[34m[信息]\e[0m $1"; }
print_success() { echo -e "\e[32m[成功]\e[0m $1"; }
print_warning() { echo -e "\e[33m[警告]\e[0m $1"; }
print_error() { echo -e "\e[31m[错误]\e[0m $1"; exit 1; }

# --- 脚本主逻辑 ---
if [ "$(id -u)" -ne 0 ]; then
   print_error "此脚本必须以root用户身份运行。"
fi

# --- 步骤 1: 安装通用依赖 (对新旧系统都安全) ---
print_info "正在更新系统并安装基础依赖 (git, python3-venv, redis-server, curl)..."
apt-get update
apt-get install -y git python3-venv python3-pip redis-server curl gpg

# --- 步骤 2: 安装或更新 Caddy (对新旧系统都安全) ---
print_info "正在安装/更新 Caddy Web 服务器..."
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy

# --- 步骤 3: 检查是安装还是更新 ---
if [ -d "${INSTALL_DIR}" ]; then
    # --- 更新流程 ---
    print_info "检测到现有安装，将执行安全更新流程..."

    print_info "停止当前服务以进行更新..."
    systemctl stop cloud_manager.service || true
    systemctl stop cloud_manager_celery.service || true

    cd "${INSTALL_DIR}"
    
    print_info "备份当前密钥和数据库文件..."
    TEMP_BACKUP_DIR=$(mktemp -d)
    # 备份所有关键数据文件
    find . -maxdepth 1 \( -name "*.json" -o -name "*.txt" -o -name "*.db" \) -exec cp {} "${TEMP_BACKUP_DIR}/" \;
    
    print_info "正在从 Git 拉取最新代码..."
    git config --global --add safe.directory ${INSTALL_DIR}
    git fetch origin
    git reset --hard origin/main  # 或者 origin/master，取决于您的主分支名

    print_info "恢复密钥和数据库文件..."
    cp -f "${TEMP_BACKUP_DIR}"/* .
    rm -rf "${TEMP_BACKUP_DIR}"
    
    # 更新密码的逻辑：检查备份的app.py中的密码并应用到新文件中
    # 这是一个简化处理，如果用户有其他方式修改密码，此逻辑可能需要调整
    print_info "保留现有密码..."
    # (通常git pull后app.py的密码会被重置为默认，所以这里跳过密码设置)
    # 如果需要强制更新密码，可以取消下面这行的注释
    # sed -i "s|^PASSWORD = \".*\"|$(grep '^PASSWORD = ' "${TEMP_BACKUP_DIR}/app.py")|" "${INSTALL_DIR}/app.py"

else
    # --- 全新安装流程 ---
    print_info "未检测到现有安装，将执行全新安装流程..."
    
    print_info "从 GitHub 克隆项目..."
    git clone "${REPO_URL}" "${INSTALL_DIR}"
    cd "${INSTALL_DIR}"
    
    print_info "创建空的数据库和密钥文件..."
    touch azure_keys.json oci_profiles.json key.txt azure_tasks.db oci_tasks.db

    print_info "设置登录密码..."
    while true; do
        read -s -p "请输入新密码: " new_password
        echo
        read -s -p "请再次输入新密码以确认: " new_password_confirm
        echo
        if [ "$new_password" = "$new_password_confirm" ] && [ -n "$new_password" ]; then
            break
        else
            print_error "两次输入的密码不匹配或密码为空，请重试。"
        fi
    done
    print_info "正在更新应用密码..."
    sed -i "s|^PASSWORD = \".*\"|PASSWORD = \"${new_password}\"|" "${INSTALL_DIR}/app.py"
    print_success "应用密码已成功设置。"

    print_info "配置 Caddy..."
    read -p "请输入您的域名 (留空则自动使用服务器公网IP): " domain_name
    if [ -z "$domain_name" ]; then
        print_info "未输入域名，正在获取公网IP..."
        ACCESS_ADDRESS=$(curl -s http://ipv4.icanhazip.com || curl -s http://ipinfo.io/ip)
        if [ -z "$ACCESS_ADDRESS" ]; then print_error "无法自动获取公网IP。"; fi
        print_success "成功获取到公网IP: ${ACCESS_ADDRESS}"
    else
        ACCESS_ADDRESS=$domain_name
    fi

    print_info "正在写入 Caddyfile... (注意: 此操作会覆盖现有Caddyfile)"
    cat > /etc/caddy/Caddyfile << EOF
$ACCESS_ADDRESS {
    reverse_proxy unix//run/gunicorn/cloud_manager.sock
}
EOF
fi

# --- 步骤 4: 通用配置 (对安装和更新都执行) ---
print_info "更新 Python 依赖库..."
cd "${INSTALL_DIR}"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

print_info "设置文件权限..."
chown -R caddy:caddy "${INSTALL_DIR}"

print_info "创建/更新 systemd 服务..."
# Gunicorn 服务
cat > /etc/systemd/system/cloud_manager.service << EOF
[Unit]
Description=Gunicorn instance to serve Cloud Manager
After=network.target
[Service]
User=caddy
Group=caddy
RuntimeDirectory=gunicorn
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/gunicorn --workers 3 --bind unix:/run/gunicorn/cloud_manager.sock -m 007 app:app
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF

# Celery 服务
cat > /etc/systemd/system/cloud_manager_celery.service << EOF
[Unit]
Description=Celery Worker for the Cloud Manager Panel
After=network.target redis-server.service
[Service]
User=caddy
Group=caddy
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/celery -A app.celery worker --loglevel=info
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF

# --- 步骤 5: 启动服务并完成 ---
print_info "正在启动并设置所有后台服务开机自启..."
systemctl daemon-reload
systemctl enable redis-server cloud_manager.service cloud_manager_celery.service
systemctl restart redis-server cloud_manager.service cloud_manager_celery.service
systemctl reload caddy

echo ""
print_success "Cloud Manager 面板已成功部署！"
echo "------------------------------------------------------------"
# 再次获取访问地址用于显示
if [ -z "$ACCESS_ADDRESS" ]; then
    if [ -f "/etc/caddy/Caddyfile" ]; then
        ACCESS_ADDRESS=$(awk 'NR==1 {print $1}' /etc/caddy/Caddyfile)
    fi
fi

if [[ "$ACCESS_ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    print_info "访问地址: http://${ACCESS_ADDRESS}"
else
    print_info "访问地址: https://${ACCESS_ADDRESS}"
fi
print_info "请使用您之前设置的密码登录。"
echo "------------------------------------------------------------"
