#!/bin/bash

# ==============================================================================
# Cloud Manager 三合一面板 一键安装脚本 (增强版)
#
# 该脚本适用于一个全新的、基于 Debian/Ubuntu 的系统。
# 它会自动安装所有依赖、配置并启动服务。
#
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

print_info "步骤 1/12: 更新系统并安装基础依赖..."
apt-get update
apt-get install -y git python3-venv python3-pip redis-server curl gpg

print_info "步骤 2/12: 安装 Caddy Web 服务器..."
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy

print_info "步骤 3/12: 从 GitHub 克隆项目..."
if [ -d "${INSTALL_DIR}" ]; then
    print_warning "目录 ${INSTALL_DIR} 已存在，将进行备份。"
    mv "${INSTALL_DIR}" "${INSTALL_DIR}_backup_$(date +%s)"
fi
git clone "${REPO_URL}" "${INSTALL_DIR}"

print_info "步骤 4/12: 设置 Python 虚拟环境并安装依赖..."
cd "${INSTALL_DIR}"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

print_info "步骤 5/12: 创建空的数据库和密钥文件..."
touch azure_keys.json oci_profiles.json key.txt azure_tasks.db oci_tasks.db

print_info "步骤 6/12: 为 caddy 用户设置文件权限..."
chown -R caddy:caddy "${INSTALL_DIR}"

print_info "步骤 7/12: 创建 Gunicorn systemd 服务..."
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

print_info "步骤 8/12: 创建 Celery systemd 服务 (已修正)..."
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

print_info "步骤 9/12: 设置登录密码..."
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

print_info "步骤 10/12: 配置 Caddy..."
read -p "请输入您的域名 (留空则自动使用服务器公网IP): " domain_name

if [ -z "$domain_name" ]; then
    print_info "未输入域名，正在获取公网IP..."
    ACCESS_ADDRESS=$(curl -s http://ipv4.icanhazip.com || curl -s http://ipinfo.io/ip)
    if [ -z "$ACCESS_ADDRESS" ]; then
        print_error "无法自动获取公网IP。"
    fi
    print_success "成功获取到公网IP: ${ACCESS_ADDRESS}"
else
    ACCESS_ADDRESS=$domain_name
fi

print_info "正在写入 Caddyfile..."
cat > /etc/caddy/Caddyfile << EOF
$ACCESS_ADDRESS {
    reverse_proxy unix//run/gunicorn/cloud_manager.sock
}
EOF

print_info "步骤 11/12: 启动所有服务..."
systemctl daemon-reload
systemctl enable redis-server
systemctl enable cloud_manager.service
systemctl enable cloud_manager_celery.service
systemctl restart redis-server
systemctl restart cloud_manager.service
systemctl restart cloud_manager_celery.service
systemctl reload caddy

print_info "步骤 12/12: 安装完成！"
echo ""
print_success "Cloud Manager 三合一面板已成功部署！"
echo "------------------------------------------------------------"
if [ -z "$domain_name" ]; then
    print_info "访问地址: http://${ACCESS_ADDRESS}"
else
    print_info "访问地址: https://${ACCESS_ADDRESS}"
fi
print_info "登录密码: 您刚刚设置的密码"
echo "------------------------------------------------------------"
