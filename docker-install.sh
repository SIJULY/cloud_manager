#!/bin/bash

# ==============================================================================
# Cloud Manager Docker版一键安装脚本 (作者: 小龙女她爸)
# 版本: 经过Gemini修改
# ==============================================================================

# --- 配置 ---
INSTALL_DIR="/opt/cloud_manager"
REPO_URL="https://github.com/SIJULY/cloud_manager.git"

# --- 辅助函数 ---
print_info() { echo -e "\e[34m[信息]\e[0m $1"; }
print_success() { echo -e "\e[32m[成功]\e[0m $1"; }
print_warning() { echo -e "\e[33m[警告]\e[0m $1"; }
print_error() { echo -e "\e[31m[错误]\e[0m $1"; exit 1; }

# --- 核心功能函数 ---

# 清理环境
uninstall_panel() {
    print_warning "您确定要彻底卸载 Cloud Manager Docker 版吗？"
    read -p "此操作将停止并删除所有相关的容器、网络、存储卷以及项目文件。此过程不可逆！请输入 'yes' 确认: " confirmation
    if [ "$confirmation" != "yes" ]; then print_info "卸载操作已取消。"; exit 0; fi
    
    print_info "开始卸载流程..."
    if [ -d "${INSTALL_DIR}" ]; then
        cd "${INSTALL_DIR}"
        docker compose down -v --remove-orphans
        cd ~
        rm -rf "${INSTALL_DIR}"
        print_success "项目文件和Docker资源已清理。"
    else
        print_warning "未找到安装目录，无需清理。"
    fi
    print_success "Cloud Manager Docker 版已彻底卸载！"
}

# 准备文件和环境
prepare_files() {
    print_info "步骤 1: 检查并安装 Docker 环境..."
    if ! command -v docker &> /dev/null; then print_warning "未检测到 Docker..."; curl -fsSL https://get.docker.com | bash; systemctl start docker; systemctl enable docker; fi
    if ! docker compose version &> /dev/null; then print_warning "未检测到 Docker Compose 插件..."; apt-get update -y && apt-get install -y docker-compose-plugin; fi
    print_success "Docker 环境检查通过。"

    print_info "步骤 2: 下载项目文件..."
    if [ -d "${INSTALL_DIR}" ]; then
        print_error "检测到已存在安装目录 ${INSTALL_DIR}。如果您想重新安装，请先选择卸载。"
    fi
    git clone ${REPO_URL} ${INSTALL_DIR}
    cd ${INSTALL_DIR}

    print_info "步骤 3: 初始化文件并修正目录权限..."
    touch azure_keys.json oci_profiles.json tg_settings.json key.txt azure_tasks.db oci_tasks.db
    chmod -R 777 .
    print_success "权限和文件初始化完成。"

    print_info "步骤 4: 检查并应用兼容性修复..."
    if grep -q "version: " docker-compose.yml; then sed -i "/version: /d" docker-compose.yml; fi
    if [ -f "Dockerfile" ]; then sed -i 's/python:3.8-buster/python:3.8-bullseye/g' Dockerfile; fi
    print_success "兼容性修复完成。"
}

# 启动容器
launch_docker() {
    print_info "步骤 6: 启动所有服务 (可能需要构建镜像，请耐心等待)..."
    if ! docker compose up -d --build; then
        print_error "Docker Compose 启动失败！请检查上面的日志输出。安装已终止。"
    fi
    echo ""
    print_success "Cloud Manager Docker 版已成功部署！"
}

# 安装逻辑 - 全新服务器
install_clean_server() {
    prepare_files
    print_info "步骤 5: 配置面板 (全新服务器模式)..."
    cp .env.example .env
    read -p "请输入您的域名 (留空则自动使用服务器公网IP): " domain_name
    if [ -z "$domain_name" ]; then ACCESS_ADDRESS=$(curl -s http://ipv4.icanhazip.com || curl -s http://ipinfo.io/ip); if [ -z "$ACCESS_ADDRESS" ]; then print_error "无法自动获取公网IP地址。"; fi
    else ACCESS_ADDRESS=$domain_name; fi
    
    read -p "请输入新的面板登录密码: " new_password
    
    CADDY_ADDRESS=$([[ "$ACCESS_ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && echo "http://${ACCESS_ADDRESS}" || echo "$ACCESS_ADDRESS")
    sed -i "s|^DOMAIN_OR_IP=.*|DOMAIN_OR_IP=${CADDY_ADDRESS}|" .env
    sed -i "s|^PANEL_PASSWORD=.*|PANEL_PASSWORD=${new_password}|" .env
    print_success "配置已保存。"
    
    launch_docker
    
    echo "------------------------------------------------------------"
    source .env
    print_info "访问地址: ${DOMAIN_OR_IP}"
    print_info "登录密码: 您设置的密码"
    echo "------------------------------------------------------------"
}

# 安装逻辑 - 已有服务
install_existing_server() {
    prepare_files
    print_info "步骤 5: 配置面板 (已有服务模式)..."
    print_info "将禁用内置Caddy并暴露指定端口。"
    
    # 修改 docker-compose.yml 来禁用 caddy
    START_LINE=$(grep -n '^  caddy:' docker-compose.yml | cut -d: -f1); END_LINE=$(grep -n '^volumes:' docker-compose.yml | cut -d: -f1)
    if [ -n "$START_LINE" ] && [ -n "$END_LINE" ]; then
        COMMENT_END_LINE=$((END_LINE - 1)); sed -i "${START_LINE},${COMMENT_END_LINE}s/^/#/" docker-compose.yml
        sed -i -e '/^  caddy_data:/s/^/#/' -e '/^  caddy_config:/s/^/#/' docker-compose.yml
    else
        print_error "无法在 docker-compose.yml 中定位 Caddy 服务块，自动化修改失败。"
    fi
    
    read -p "请输入新的面板登录密码: " new_password
    
    read -p "请输入要映射到主机的端口 [默认: 8000]: " host_port
    host_port=${host_port:-8000}

    # 修改 docker-compose.yml 来暴露用户指定的端口
    sed -i "/^  web:/,/^  worker:/s/    restart: always/    restart: always\n    ports:\n      - \"${host_port}:5000\"/" docker-compose.yml
    
    cp .env.example .env
    sed -i "s|^PANEL_PASSWORD=.*|PANEL_PASSWORD=${new_password}|" .env
    print_success "配置已保存。"

    launch_docker

    SERVER_IP=$(curl -s http://ipv4.icanhazip.com || curl -s http://ipinfo.io/ip)
    echo "------------------------------------------------------------"
    print_info "核心服务已启动！"
    print_info "您现在可以通过IP地址访问: http://${SERVER_IP}:${host_port}"
    print_info "登陆密码为安装过程中您设置的密码"
    
    print_warning "如果您想使用域名访问，请手动将您的域名解析到此服务器IP，然后在您现有的Web服务器（Nginx, Caddy等）中添加以下反向代理配置："
    echo "--- Caddy 配置示例 (请将 your_domain.com 和 ${host_port} 替换为您的配置) ---"
    echo "your_domain.com {"
    echo "    reverse_proxy localhost:${host_port}"
    echo "}"
    echo "------------------------------------------------------------"
}

# 更新逻辑
update_panel() {
    if [ ! -d "${INSTALL_DIR}" ]; then
        print_error "未检测到安装目录，无法执行更新。请先安装。"
    fi
    cd "${INSTALL_DIR}"

    print_info "步骤 1: 检查当前安装模式..."
    is_existing_server_mode=false
    # 通过检查 caddy 服务是否被注释来判断模式
    if grep -q '^#  caddy:' docker-compose.yml; then
        is_existing_server_mode=true
        # 获取用户设置的端口
        host_port=$(grep -A 2 'ports:' docker-compose.yml | tail -n 1 | awk -F'"' '{print $2}' | cut -d: -f1)
        print_info "检测到“已有服务模式”，将保留端口 ${host_port} 并禁用 Caddy。"
    else
        print_info "检测到“全新服务器模式”，将更新 Caddy。"
    fi

    print_info "步骤 2: 强制重置本地代码以同步远程仓库..."
    git fetch origin
    git reset --hard origin/main
    
    print_info "步骤 3: 正在从 Git 拉取最新代码..."
    if ! git pull origin main; then
        print_error "Git 拉取失败。可能是网络问题。"
        exit 1
    fi
    print_success "代码更新完毕。"

    # 如果是“已有服务模式”，则在更新后的文件上重新应用修改
    if [ "$is_existing_server_mode" = true ]; then
        print_info "步骤 4: 正在为“已有服务模式”重新应用配置..."
        START_LINE=$(grep -n '^  caddy:' docker-compose.yml | cut -d: -f1); END_LINE=$(grep -n '^volumes:' docker-compose.yml | cut -d: -f1)
        if [ -n "$START_LINE" ] && [ -n "$END_LINE" ]; then
            COMMENT_END_LINE=$((END_LINE - 1)); sed -i "${START_LINE},${COMMENT_END_LINE}s/^/#/" docker-compose.yml
            sed -i -e '/^  caddy_data:/s/^/#/' -e '/^  caddy_config:/s/^/#/' docker-compose.yml
        else
            print_warning "无法在新的 docker-compose.yml 中定位 Caddy，跳过禁用步骤。"
        fi
        
        # 确保端口号有效
        if [ -z "$host_port" ]; then 
            host_port=8000
            print_warning "无法检测到旧端口，将使用默认端口 8000。"
        fi
        sed -i "/^  web:/,/^  worker:/s/    restart: always/    restart: always\n    ports:\n      - \"${host_port}:5000\"/" docker-compose.yml
        print_success "配置重新应用完成。"
    fi

    print_info "步骤 5: 正在重新构建并启动服务..."
    if ! docker compose up -d --build; then
        print_error "Docker Compose 更新失败！请检查日志。"
    fi
    print_success "面板已成功更新！"
}


# --- 脚本主入口 ---
if [ "$(id -u)" -ne 0 ]; then print_error "此脚本必须以root用户身份运行。"; fi
clear
print_info "欢迎使用 Cloud Manager Docker 版管理脚本 (作者: 小龙女她爸)"
echo "=========================================================="
echo "请选择要执行的操作:"
echo "  1) 在【已有服务】的服务器上安装 (IP:端口登陆) [默认]"
echo "  2) 在【全新服务器】上域名模式安装 (将占用80/443端口)"
echo "  3) 更新现有面板"
echo "  4) 彻底卸载面板"
echo "  5) 退出脚本"
echo "=========================================================="
read -p "请输入选项数字 [1]: " choice
choice=${choice:-1}

case $choice in
    1)
        install_existing_server
        ;;
    2)
        install_clean_server
        ;;
    3)
        update_panel
        ;;
    4)
        uninstall_panel
        ;;
    5)
        print_info "操作已取消，退出脚本。"
        exit 0
        ;;
    *)
        print_error "无效的选项。"
        ;;
esac

