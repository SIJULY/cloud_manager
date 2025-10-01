#!/bin/bash

# ==============================================================================
# Cloud Manager 三合一面板 一键安装脚本 (Docker版) - 最终完整修正版
# 修正了备用端口模式的BUG并增加了严格的错误检查
# ==============================================================================

# --- 配置 ---
INSTALL_DIR="/opt/cloud_manager"
REPO_URL="https://github.com/SIJULY/cloud_manager.git"
CUSTOM_PORT="5005" # 定义备用端口

# --- 辅助函数 ---
print_info() { echo -e "\e[34m[信息]\e[0m $1"; }
print_success() { echo -e "\e[32m[成功]\e[0m $1"; }
print_warning() { echo -e "\e[33m[警告]\e[0m $1"; }
print_error() { echo -e "\e[31m[错误]\e[0m $1"; exit 1; }

# --- 端口检测函数 ---
check_port() {
    local port_to_check=$1
    if ss -lnt | awk '{print $4}' | grep -q ":${port_to_check}$"; then
        return 1 # 端口被占用
    else
        return 0 # 端口未被占用
    fi
}

# --- 功能函数 ---

uninstall_docker_panel() {
    print_warning "您确定要彻底卸载 Cloud Manager Docker 版吗？"
    read -p "此操作将停止并删除所有相关的容器、网络、存储卷以及项目文件。此过程不可逆！请输入 'yes' 确认: " confirmation

    if [ "$confirmation" != "yes" ]; then
        print_info "卸载操作已取消。"
        exit 0
    fi

    print_info "开始卸载流程..."

    if [ -d "${INSTALL_DIR}" ] && [ -f "${INSTALL_DIR}/docker-compose.yml" ]; then
        print_info "1. 进入项目目录并停止、移除所有相关容器和数据卷..."
        cd "${INSTALL_DIR}"
        docker compose down -v
        print_success "所有 Docker 资源已清理。"
    fi

    print_info "2. 移除项目目录 ${INSTALL_DIR}..."
    rm -rf "${INSTALL_DIR}"
    print_success "项目目录已删除。"
    
    print_success "Cloud Manager Docker 版已彻底卸载！"
}

ensure_files_and_fixes() {
    print_info "检查并应用兼容性修复..."

    # 修复1: 确保所有必需的文件都已创建，防止Docker挂载时创建成目录
    touch azure_keys.json oci_profiles.json key.txt azure_tasks.db oci_tasks.db
    chmod 666 azure_keys.json oci_profiles.json key.txt azure_tasks.db oci_tasks.db
    print_success "修复1: 所有必需的配置文件和数据库文件已确保存在。"
    
    # 修复2: 更新 Dockerfile 基础镜像以增强兼容性
    if [ -f "Dockerfile" ]; then
        sed -i 's/python:3.8-buster/python:3.8-bullseye/g' Dockerfile
        print_success "修复2: Dockerfile 已更新为 Bullseye 基础镜像。"
    fi
}


install_or_update_docker_panel() {
    print_info "步骤 1: 检查并安装 Docker 环境..."
    if ! command -v docker &> /dev/null; then
        print_warning "未检测到 Docker，正在尝试自动安装..."
        curl -fsSL https://get.docker.com | bash
        systemctl start docker
        systemctl enable docker
    fi
    if ! docker compose version &> /dev/null; then
        print_warning "未检测到 Docker Compose 插件，正在尝试自动安装..."
        apt-get update
        apt-get install -y docker-compose-plugin
    fi
    print_success "Docker 环境检查通过。"

    if [ -d "${INSTALL_DIR}" ]; then
        print_info "步骤 2: 检测到现有安装，执行更新流程..."
        cd "${INSTALL_DIR}"
        git config --global --add safe.directory ${INSTALL_DIR}
        git pull origin main
    else
        print_info "步骤 2: 未检测到安装，执行全新安装..."
        git clone ${REPO_URL} ${INSTALL_DIR}
        cd ${INSTALL_DIR}
    fi
    
    ensure_files_and_fixes
    
    local use_custom_port=false
    local final_access_address=""

    if ! check_port 80 || ! check_port 443; then
        print_warning "检测到 80 或 443 端口已被占用！"
        print_info "Caddy 默认需要使用 80 和 443 端口来提供 Web 服务并自动申请 HTTPS 证书。"
        echo "------------------------------------------------------------"
        echo "请选择您的操作："
        echo "  1) 使用备用端口 ${CUSTOM_PORT} 进行安装 (将以 HTTP 方式访问，无法自动申请证书)"
        echo "  2) 退出脚本，我将手动暂停占用端口的服务 (如 Nginx, Apache 等)"
        echo "------------------------------------------------------------"
        read -p "请输入选项 [1]: " port_choice
        
        case ${port_choice:-1} in
            1)
                print_info "好的，将使用备用端口 ${CUSTOM_PORT} 进行安装。"
                use_custom_port=true
                # 【核心修正】直接修改 docker-compose.yml 文件
                print_info "正在修改 docker-compose.yml以使用备用端口..."
                # 为了安全，先备份
                cp docker-compose.yml docker-compose.yml.bak
                # 使用 sed 注释掉原有的 80 和 443 端口，并添加新的端口
                # 这个sed命令会找到caddy服务块中，从ports:开始到第一个- "443:443"行为止的范围进行操作
                sed -i -e "/caddy:/,/- \"443:443\"/s/- \"80:80\"/- \"${CUSTOM_PORT}:80\"/" \
                       -e "/caddy:/,/- \"443:443\"/s/- \"443:443\"/#- \"443:443\"/" docker-compose.yml
                print_success "docker-compose.yml 已成功修改。"
                ;;
            2)
                print_info "脚本已退出。请先运行 'sudo systemctl stop nginx' 等命令释放端口，然后再重新运行此脚本。"
                exit 0
                ;;
            *)
                print_error "无效的选项。"
                ;;
        esac
    else
        print_success "端口 80 和 443 未被占用，将进行标准安装。"
        # 如果之前有备份，恢复原始文件
        [ -f docker-compose.yml.bak ] && mv docker-compose.yml.bak docker-compose.yml
    fi

    if [ ! -f ".env" ]; then
        print_info "步骤 4: 首次安装，开始配置面板..."
        cp .env.example .env
        read -p "请输入您的域名 (留空则自动使用服务器公网IP): " domain_name
        if [ -z "$domain_name" ]; then
            ACCESS_ADDRESS=$(curl -s http://ipv4.icanhazip.com || curl -s http://ipinfo.io/ip)
            if [ -z "$ACCESS_ADDRESS" ]; then print_error "无法自动获取公网IP地址。"; fi
        else
            ACCESS_ADDRESS=$domain_name
        fi
        read -s -p "请输入新的面板登录密码: " new_password; echo

        if [ "$use_custom_port" = true ]; then
            final_access_address="http://${ACCESS_ADDRESS}:${CUSTOM_PORT}"
            CADDY_ADDRESS=$final_access_address
        elif [[ "$ACCESS_ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            final_access_address="http://${ACCESS_ADDRESS}"
            CADDY_ADDRESS=$final_access_address
        else
            final_access_address="https://${ACCESS_ADDRESS}"
            CADDY_ADDRESS=$ACCESS_ADDRESS
        fi
        
        sed -i "s|^DOMAIN_OR_IP=.*|DOMAIN_OR_IP=${CADDY_ADDRESS}|" .env
        sed -i "s|^PANEL_PASSWORD=.*|PANEL_PASSWORD=${new_password}|" .env
        print_success "配置已保存到 .env 文件。"
    fi

    print_info "步骤 5: 启动所有服务 (可能需要构建镜像，请耐心等待)..."
    # 【核心修正】增加了错误检查，如果 docker compose 失败则脚本会退出
    if ! docker compose up -d --build; then
        print_error "Docker Compose 启动失败！请检查上面的日志输出以确定问题。"
        # 如果是因为端口修改失败，可以尝试恢复
        [ -f docker-compose.yml.bak ] && mv docker-compose.yml.bak docker-compose.yml
        exit 1
    fi
    
    # 获取最终访问地址
    source .env
    # 提取基础地址 (IP或域名)，兼容http/https前缀和可能存在的端口号
    base_address=$(echo $DOMAIN_OR_IP | sed -E 's#^https?://##; s#:[0-9]+.*##')
    if [ "$use_custom_port" = true ]; then
        final_access_address="http://${base_address}:${CUSTOM_PORT}"
    elif [[ "$DOMAIN_OR_IP" =~ ^http:// ]]; then
        final_access_address="http://${base_address}"
    else
        final_access_address="https://$base_address"
    fi

    echo ""
    print_success "Cloud Manager Docker 版已成功部署/更新！"
    echo "------------------------------------------------------------"
    print_info "访问地址: ${final_access_address}"
    print_info "登录密码: 您设置的密码"
    echo "------------------------------------------------------------"
}


# --- 脚本主入口 ---
if [ "$(id -u)" -ne 0 ]; then
    print_error "此脚本必须以root用户身份运行。"
fi

clear
print_info "欢迎使用 Cloud Manager Docker 版管理脚本 (最终完整修正版)"
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
        install_or_update_docker_panel
        ;;
    2)
        uninstall_docker_panel
        ;;
    3)
        print_info "操作已取消，退出脚本。"
        exit 0
        ;;
    *)
        print_error "无效的选项，请输入 1, 2 或 3。"
        ;;
esac
