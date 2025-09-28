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
# 项目将安装在此目录
INSTALL_DIR="/opt/cloud_manager"
# GitHub 仓库地址
REPO_URL="https://github.com/SIJULY/cloud_manager.git"


# --- 脚本设置 ---
# 如果任何命令失败，则立即退出
set -e

# --- 辅助函数，用于彩色输出 ---
print_info() {
    echo -e "\e[34m[信息]\e[0m $1"
}

print_success() {
    echo -e "\e[32m[成功]\e[0m $1"
}

print_warning() {
    echo -e "\e[33m[警告]\e[0m $1"
}

print_error() {
    echo -e "\e[31m[错误]\e[0m $1"
    exit 1
}

# --- 脚本主逻辑 ---

# 1. 检查是否以root用户身份运行
if [ "$(id -u)" -ne 0 ]; then
   print_error "此脚本必须以root用户身份运行。请尝试使用 'sudo bash install.sh'。"
fi

# 2. 更新系统并安装必要的软件包
print_info "开始系统更新并安装基础依赖 (git, python3-venv, redis, curl)..."
apt-get update
apt-get install -y git python3-venv python3-pip redis-server curl gpg

# 3. 安装 Caddy Web 服务器
print_info "正在添加 Caddy 官方源并安装 Caddy..."
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy

# 4. 从 GitHub 克隆项目代码
print_info "正在从 GitHub 克隆项目到 ${INSTALL_DIR}..."
if [ -d "${INSTALL_DIR}" ]; then
    print_warning "目录 ${INSTALL_DIR} 已存在。将备份为 ${INSTALL_DIR}_backup_$(date +%s) 并重新克隆。"
    mv "${INSTALL_DIR}" "${INSTALL_DIR}_backup_$(date +%s)"
fi
git clone "${REPO_URL}" "${INSTALL_DIR}"

# 5. 设置 Python 虚拟环境并安装项目依赖
print_info "正在设置 Python 虚拟环境并安装依赖库..."
cd "${INSTALL_DIR}"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate # 暂时退出虚拟环境, systemd服务会使用完整路径

# 6. 创建应用所需的数据和配置文件
print_info "正在创建空的数据库和密钥文件..."
touch azure_keys.json oci_profiles.json key.txt azure_tasks.db oci_tasks.db

# 7. 为 caddy 用户设置正确的文件权限
print_info "正在为 caddy 用户设置项目文件权限..."
chown -R caddy:caddy "${INSTALL_DIR}"

# 8. 创建 Gunicorn 的 systemd 服务
print_info "正在创建 Gunicorn 后台服务 (cloud_manager.service)..."
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

# 9. 创建 Celery 的 systemd 服务
print_info "正在创建 Celery 后台服务 (cloud_manager_celery.service)..."
cat > /etc/systemd/system/cloud_manager_celery.service << EOF
[Unit]
Description=Celery Worker for the Cloud Manager Panel
After=network.target

[Service]
User=caddy
Group=caddy
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/celery -A blueprints.oci_panel.celery worker --loglevel=info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 10. 设置登录密码
print_info "现在请为您的管理面板设置一个新的登录密码。"
while true; do
    read -s -p "请输入新密码: " new_password
    echo
    read -s -p "请再次输入新密码以确认: " new_password_confirm
    echo
    if [ "$new_password" = "$new_password_confirm" ]; then
        if [ -z "$new_password" ]; then
            print_warning "密码不能为空，请重新输入。"
        else
            break
        fi
    else
        print_error "两次输入的密码不匹配，请重试。"
    fi
done

print_info "正在更新应用密码..."
# 使用sed安全地替换app.py中的密码行
sed -i "s|^PASSWORD = \".*\"|PASSWORD = \"${new_password}\"|" "${INSTALL_DIR}/app.py"
print_success "应用密码已成功设置为您提供的值。"

# 11. 获取用户域名/IP并配置 Caddy
print_info "现在需要您提供用于访问面板的域名或IP地址。"
print_warning "如果您已有其他网站在使用Caddy，此脚本会将新配置【追加】到现有Caddyfile末尾。"
print_warning "安装完成后，请检查 /etc/caddy/Caddyfile 以确保没有冲突的配置。"

read -p "请输入您的域名 (留空则自动使用服务器公网IP): " domain_name

ACCESS_ADDRESS=""
# 如果用户输入为空
if [ -z "$domain_name" ]; then
    print_info "未输入域名，正在尝试获取服务器公网IP..."
    # 使用多个源尝试获取IP，增加成功率
    PUBLIC_IP=$(curl -s http://ipv4.icanhazip.com || curl -s http://ipinfo.io/ip || curl -s http://checkip.amazonaws.com)
    if [ -z "$PUBLIC_IP" ]; then
        print_error "无法自动获取公网IP地址。请检查网络连接或手动提供一个域名。"
    fi
    ACCESS_ADDRESS=$PUBLIC_IP
    print_success "成功获取到公网IP: ${PUBLIC_IP}"
    print_warning "使用IP地址访问将是HTTP协议，浏览器可能会提示不安全。"
else
    ACCESS_ADDRESS=$domain_name
fi

print_info "正在向 Caddy 添加配置..."
# 使用 cat << EOF | tee -a 追加配置，而不是覆盖
cat << EOF | tee -a /etc/caddy/Caddyfile

# Cloud Manager Panel Configuration
$ACCESS_ADDRESS {
    reverse_proxy unix//run/gunicorn/cloud_manager.sock
}
EOF

# 12. 启动并启用所有服务
print_info "正在启动并设置所有后台服务开机自启..."
systemctl daemon-reload
systemctl enable cloud_manager.service
systemctl enable cloud_manager_celery.service
systemctl restart cloud_manager.service
systemctl restart cloud_manager_celery.service
systemctl reload caddy

# --- 安装完成 ---
echo ""
print_success "Cloud Manager 三合一面板已成功安装！"
echo ""
print_info "------------------------- 安装详情 -------------------------"
print_info "项目路径: ${INSTALL_DIR}"
if [ -z "$domain_name" ]; then
    print_info "访问地址: http://${ACCESS_ADDRESS}"
else
    print_info "访问地址: https://${ACCESS_ADDRESS}"
fi
print_info "登录密码: 您刚刚设置的密码"
print_info "------------------------------------------------------------"
echo ""

