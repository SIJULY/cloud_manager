#!/bin/bash

# ==============================================================================
# Cloud Manager 三合一面板 一键安装脚本 (最终修正版)
# 该脚本适用于一个全新的、基于 Debian/Ubuntu 的系统。
# 它会自动安装所有依赖、配置并启动服务。
# 作者: 小龙女她爸
# ==============================================================================

# --- 配置 ---
INSTALL_DIR="/opt/cloud_manager"
REPO_URL="https://github.com/SIJULY/cloud_manager.git"
SERVICE_NAME="cloud_manager"
CELERY_SERVICE_NAME="cloud_manager_celery"
CADDY_CONFIG_START="# Cloud Manager Panel Configuration Start"
CADDY_CONFIG_END="# Cloud Manager Panel Configuration End"

# --- 脚本设置 ---
set -e

# --- 辅助函数 ---
print_info() { echo -e "\e[34m[信息]\e[0m $1"; }
print_success() { echo -e "\e[32m[成功]\e[0m $1"; }
print_warning() { echo -e "\e[33m[警告]\e[0m $1"; }
print_error() { echo -e "\e[31m[错误]\e[0m $1"; exit 1; }

# --- 功能函数 ---

uninstall_panel() {
    print_warning "您确定要彻底卸载 Cloud Manager 面板吗？"
    read -p "此操作将删除所有相关服务、项目文件以及已保存的密钥。此过程不可逆！请输入 'yes' 确认: " confirmation
    
    if [ "$confirmation" != "yes" ]; then
        print_info "卸载操作已取消。"
        exit 0
    fi

    print_info "开始卸载流程..."

    print_info "1. 停止并禁用后台服务..."
    systemctl stop ${SERVICE_NAME}.service || true
    systemctl stop ${CELERY_SERVICE_NAME}.service || true
    systemctl disable ${SERVICE_NAME}.service || true
    systemctl disable ${CELERY_SERVICE_NAME}.service || true
    print_success "服务已停止并禁用。"

    print_info "2. 移除 systemd 服务文件..."
    rm -f /etc/systemd/system/${SERVICE_NAME}.service
    rm -f /etc/systemd/system/${CELERY_SERVICE_NAME}.service
    systemctl daemon-reload
    print_success "服务文件已移除。"

    print_info "3. 移除项目目录 ${INSTALL_DIR}..."
    rm -rf "${INSTALL_DIR}"
    print_success "项目目录已删除。"

    print_info "4. 从 Caddyfile 中移除面板配置..."
    if [ -f "/etc/caddy/Caddyfile" ]; then
        sed -i "/${CADDY_CONFIG_START}/,/${CADDY_CONFIG_END}/d" /etc/caddy/Caddyfile
        systemctl reload caddy
        print_success "Caddy 配置已移除并重载。"
    else
        print_warning "未找到 Caddyfile，跳过配置移除。"
    fi

    echo ""
    print_success "Cloud Manager 面板已彻底卸载！"
}

install_or_update_panel() {
    print_info "步骤 1: 安装通用依赖及编译环境..."
    apt-get update
    apt-get install -y git python3-venv python3-pip redis-server curl gpg python3-dev gcc

    print_info "步骤 2: 安装/更新 Caddy..."
    apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
    apt-get update
    apt-get install -y caddy

    if [ -d "${INSTALL_DIR}" ]; then
        # --- 更新流程 ---
        print_info "步骤 3: 检测到现有安装，执行安全更新..."
        systemctl stop ${SERVICE_NAME}.service || true
        systemctl stop ${CELERY_SERVICE_NAME}.service || true
        cd "${INSTALL_DIR}"
        
        print_info "备份当前密钥和数据库文件..."
        TEMP_BACKUP_DIR=$(mktemp -d)
        find . -maxdepth 1 \( -name "*.json" -o -name "*.txt" -o -name "*.db" \) -exec cp {} "${TEMP_BACKUP_DIR}/" \;
        
        print_info "正在从 Git 拉取最新代码..."
        git config --global --add safe.directory ${INSTALL_DIR}
        git fetch origin
        git reset --hard origin/main

        print_info "恢复密钥和数据库文件..."
        if [ -n "$(ls -A ${TEMP_BACKUP_DIR})" ]; then
            cp -f "${TEMP_BACKUP_DIR}"/* .
        fi
        rm -rf "${TEMP_BACKUP_DIR}"
    else
        # --- 全新安装流程 ---
        print_info "步骤 3: 未检测到安装，执行全新安装..."
        git clone "${REPO_URL}" "${INSTALL_DIR}"
        cd "${INSTALL_DIR}"
        
        # 创建必要的空配置文件，数据库文件由程序在首次启动时自动初始化。
        print_info "初始化配置文件..."
        touch azure_keys.json oci_profiles.json key.txt tg_settings.json
        print_success "文件初始化完成。"

        print_info "设置登录密码..."
        while true; do
            read -s -p "请输入新密码: " new_password; echo
            read -s -p "请再次输入新密码以确认: " new_password_confirm; echo
            if [ "$new_password" = "$new_password_confirm" ] && [ -n "$new_password" ]; then
                break
            else
                print_warning "两次输入的密码不匹配或密码为空，请重试。"
            fi
        done
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
        
        print_info "正在向 Caddyfile 追加配置..."
        # 移除旧配置（如果有的话），避免重复添加
        if [ -f "/etc/caddy/Caddyfile" ]; then
            sed -i "/${CADDY_CONFIG_START}/,/${CADDY_CONFIG_END}/d" /etc/caddy/Caddyfile
        fi
        
        cat << EOF | tee -a /etc/caddy/Caddyfile

${CADDY_CONFIG_START}
$ACCESS_ADDRESS {
    reverse_proxy unix//run/gunicorn/cloud_manager.sock
}
${CADDY_CONFIG_END}
EOF
    fi

    print_info "步骤 4: 更新 Python 依赖并设置权限..."
    cd "${INSTALL_DIR}"
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    
    # 【核心】直接使用项目自带的、已经修正过的 requirements.txt 文件安装所有依赖
    pip install -r requirements.txt
    
    # 强制安装已知可用的 gevent 稳定版本，避免在 ARM 服务器上编译错误
    # 这一步必须在 install -r ... 之后，以确保正确覆盖 Celery 的默认依赖
    pip install "gevent==21.12.0"

    deactivate
    chown -R caddy:caddy "${INSTALL_DIR}"

    print_info "步骤 5: 创建/更新 systemd 服务..."
    cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
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

    cat > /etc/systemd/system/${CELERY_SERVICE_NAME}.service << EOF
[Unit]
Description=Celery Worker for the Cloud Manager Panel
After=network.target redis-server.service

[Service]
User=caddy
Group=caddy
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/celery -A app.celery worker --loglevel=info --concurrency=5
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    print_info "步骤 6: 启动所有服务..."
    systemctl daemon-reload
    systemctl enable redis-server ${SERVICE_NAME}.service ${CELERY_SERVICE_NAME}.service
    systemctl restart redis-server ${SERVICE_NAME}.service ${CELERY_SERVICE_NAME}.service
    systemctl reload caddy

    echo ""
    print_success "Cloud Manager 面板已成功部署！"
    echo "------------------------------------------------------------"
    
    if [ -z "$ACCESS_ADDRESS" ] && [ -f "/etc/caddy/Caddyfile" ]; then
        ACCESS_ADDRESS=$(grep -B 1 "reverse_proxy unix//run/gunicorn/cloud_manager.sock" /etc/caddy/Caddyfile | head -n 1 | awk '{print $1}')
    fi

    if [[ "$ACCESS_ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        print_info "访问地址: http://${ACCESS_ADDRESS}"
    else
        print_info "访问地址: https://${ACCESS_ADDRESS}"
    fi
    print_info "请使用您之前设置(或刚刚设置)的密码登录。"
    echo "------------------------------------------------------------"
}

# --- 脚本主入口 ---
if [ "$(id -u)" -ne 0 ]; then
   print_error "此脚本必须以root用户身份运行。"
fi

if command -v docker &> /dev/null && docker ps --format '{{.Names}}' | grep -q "cloud_manager"; then
    print_error "检测到正在运行的 Docker 版 Cloud Manager。两种安装模式不能混用。"
    print_error "请先运行 'docker-compose down -v' 彻底卸载 Docker 版，或选择使用 Docker 方式进行管理。"
    exit 1
fi

clear
print_info "欢迎使用 Cloud Manager 三合一面板管理脚本"
echo "==============================================="
echo "请选择要执行的操作:"
echo "  1) 安装 或 更新 面板 (默认选项)"
echo "  2) 彻底卸载 面板"
echo "  3) 退出脚本"
echo "==============================================="
read -p "请输入选项数字 [1]: " choice

choice=${choice:-1}

case $choice in
    1)
        install_or_update_panel
        ;;
    2)
        uninstall_panel
        ;;
    3)
        print_info "操作已取消，退出脚本。"
        exit 0
        ;;
    *)
        print_error "无效的选项，请输入 1, 2 或 3。"
        ;;
esac
