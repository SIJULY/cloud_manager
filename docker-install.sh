#!/bin/bash

# ==============================================================================
# Cloud Manager Docker版一键安装脚本 (V6 - 用户选择模式版)
# 根据用户选择的服务器类型（全新/已有服务）执行不同的安装策略。
# ==============================================================================

# --- 配置 ---
INSTALL_DIR="/opt/cloud_manager"
REPO_URL="https://github.com/SIJULY/cloud_manager.git"

# --- 辅助函数 ---
print_info() { echo -e "\e[34m[信息]\e[0m $1"; }
print_success() { echo -e "\e[32m[成功]\e[0m $1"; }
print_warning() { echo -e "\e[33m[警告]\e[0m $1"; }
print_error() { echo -e "\e[31m[错误]\e[0m $1"; exit 1; }

# --- 功能函数 ---
uninstall_docker_panel() {
    print_warning "您确定要彻底卸载 Cloud Manager Docker 版吗？"
    read -p "此操作将停止并删除所有相关的容器、网络、存储卷以及项目文件。此过程不可逆！请输入 'yes' 确认: " confirmation
    if [ "$confirmation" != "yes" ]; then print_info "卸载操作已取消。"; exit 0; fi
    print_info "开始卸载流程..."
    if [ -d "${INSTALL_DIR}" ]; then
        cd "${INSTALL_DIR}"; docker compose down -v --remove-orphans; cd ~; rm -rf "${INSTALL_DIR}"; print_success "项目文件和Docker资源已清理。"
    else
        print_warning "未找到安装目录，无需清理。"
    fi
    print_success "Cloud Manager Docker 版已彻底卸载！"
}

ensure_files_and_fixes() {
    print_info "检查并应用兼容性修复..."
    touch azure_keys.json oci_profiles.json key.txt azure_tasks.db oci_tasks.db; chmod 666 azure_keys.json oci_profiles.json key.txt azure_tasks.db oci_tasks.db
    if grep -q "version: " docker-compose.yml; then sed -i "/version: /d" docker-compose.yml; fi
    print_success "修复1: 所有必需的配置文件和数据库文件已确保存在。"
    if [ -f "Dockerfile" ]; then sed -i 's/python:3.8-buster/python:3.8-bullseye/g' Dockerfile; print_success "修复2: Dockerfile 已更新为 Bullseye 基础镜像。"; fi
}

install_or_update_docker_panel() {
    print_info "步骤 1: 检查并安装 Docker 环境..."
    if ! command -v docker &> /dev/null; then print_warning "未检测到 Docker，正在尝试自动安装..."; curl -fsSL https://get.docker.com | bash; systemctl start docker; systemctl enable docker; fi
    if ! docker compose version &> /dev/null; then print_warning "未检测到 Docker Compose 插件，正在尝试自动安装..."; apt-get update -y && apt-get install -y docker-compose-plugin; fi
    print_success "Docker 环境检查通过。"

    if [ -d "${INSTALL_DIR}" ]; then
        print_info "步骤 2: 检测到现有安装，执行更新流程..."; cd "${INSTALL_DIR}"; print_info "正在从 Git 拉取最新代码..."; git restore docker-compose.yml; git config --global --add safe.directory ${INSTALL_DIR}; git pull origin main
    else
        print_info "步骤 2: 未检测到安装，执行全新安装..."; git clone ${REPO_URL} ${INSTALL_DIR}; cd ${INSTALL_DIR}
    fi

    ensure_files_and_fixes

    if [ ! -f ".env" ]; then
        print_info "步骤 4: 首次安装，请选择您的服务器环境类型:"
        echo "    1) 全新服务器 (脚本将全自动安装并配置HTTPS)"
        echo "    2) 已有网站或服务 (脚本仅暴露端口，您需手动配置反向代理)"
        read -p "请输入选项数字 [1]: " server_type
        server_type=${server_type:-1}

        if [ "$server_type" = "1" ]; then
            # --- 全新服务器安装路径 ---
            print_info "您已选择[全新服务器]模式，将使用内置Caddy进行安装。"
            cp .env.example .env
            read -p "请输入您的域名 (留空则自动使用服务器公网IP): " domain_name
            if [ -z "$domain_name" ]; then ACCESS_ADDRESS=$(curl -s http://ipv4.icanhazip.com || curl -s http://ipinfo.io/ip); if [ -z "$ACCESS_ADDRESS" ]; then print_error "无法自动获取公网IP地址。"; fi
            else ACCESS_ADDRESS=$domain_name; fi
            read -s -p "请输入新的面板登录密码: " new_password; echo
            CADDY_ADDRESS=$([[ "$ACCESS_ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && echo "http://${ACCESS_ADDRESS}" || echo "$ACCESS_ADDRESS")
            sed -i "s|^DOMAIN_OR_IP=.*|DOMAIN_OR_IP=${CADDY_ADDRESS}|" .env
            sed -i "s|^PANEL_PASSWORD=.*|PANEL_PASSWORD=${new_password}|" .env
            export INSTALL_MODE="internal_caddy"
        else
            # --- 已有服务安装路径 ---
            print_info "您已选择[已有服务]模式，将禁用内置Caddy并暴露8000端口。"
            START_LINE=$(grep -n '^  caddy:' docker-compose.yml | cut -d: -f1); END_LINE=$(grep -n '^volumes:' docker-compose.yml | cut -d: -f1)
            if [ -n "$START_LINE" ] && [ -n "$END_LINE" ]; then
                COMMENT_END_LINE=$((END_LINE - 1)); sed -i "${START_LINE},${COMMENT_END_LINE}s/^/#/" docker-compose.yml
                sed -i -e '/^  caddy_data:/s/^/#/' -e '/^  caddy_config:/s/^/#/' docker-compose.yml
            else
                print_error "无法在 docker-compose.yml 中定位 Caddy 服务块，自动化修改失败。"
            fi
            sed -i -e '/^  web:/,/^  worker:/s/    restart: always/    restart: always\n    ports:\n      - "8000:5000"/' docker-compose.yml
            cp .env.example .env
            read -s -p "请输入新的面板登录密码: " new_password; echo
            sed -i "s|^PANEL_PASSWORD=.*|PANEL_PASSWORD=${new_password}|" .env
            export INSTALL_MODE="external_proxy"
        fi
        print_success "配置已保存到 .env 文件。"
    else
        print_info "步骤 4: .env 文件已存在，跳过配置。"
    fi

    print_info "步骤 5: 启动所有服务 (可能需要构建镜像，请耐心等待)..."
    if ! docker compose up -d --build; then
        print_error "Docker Compose 启动失败！请检查上面的日志输出。安装已终止。"
    fi
    
    echo ""; print_success "Cloud Manager Docker 版已成功部署/更新！"; echo "------------------------------------------------------------"

    if [ "$INSTALL_MODE" = "internal_caddy" ]; then
        source .env; print_info "访问地址: ${DOMAIN_OR_IP}"; print_info "登录密码: 您设置的密码"
    elif [ "$INSTALL_MODE" = "external_proxy" ]; then
        SERVER_IP=$(curl -s http://ipv4.icanhazip.com || curl -s http://ipinfo.io/ip)
        print_info "核心服务已启动！"
        print_info "您现在可以通过IP地址访问: http://${SERVER_IP}:8000"
        print_warning "如果您想使用域名访问，请手动将您的域名解析到此服务器IP，然后在您现有的Web服务器（Nginx, Caddy等）中添加以下反向代理配置："
        echo "----------------- Caddy 配置示例 -----------------"
        echo "your_domain.com {"
        echo "    reverse_proxy localhost:8000"
        echo "}"
        echo "--------------------------------------------------"
    fi
    echo "------------------------------------------------------------"
}

# --- 脚本主入口 ---
if [ "$(id -u)" -ne 0 ]; then print_error "此脚本必须以root用户身份运行。"; fi
clear
print_info "欢迎使用 Cloud Manager Docker 版管理脚本 (V6-用户选择模式版)"
echo "================================================================="
echo "请选择要执行的操作:"; echo "  1) 安装 或 更新 面板 (默认选项)"; echo "  2) 彻底卸载 面板"; echo "  3) 退出脚本"; echo "================================================================="
read -p "请输入选项数字 [1]: " choice
choice=${choice:-1}
case $choice in 1) install_or_update_docker_panel ;; 2) uninstall_docker_panel ;; 3) print_info "操作已取消，退出脚本。"; exit 0 ;; *) print_error "无效的选项。";; esac
