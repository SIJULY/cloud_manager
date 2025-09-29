#!/bin/bash

# ==============================================================================
# Cloud Manager 三合一面板 一键安装脚本 (Docker版) - 功能增强版
# 该脚本适用于一个全新的、基于 Debian/Ubuntu 的系统。
# 新增特性：
# - 启动菜单，提供安装/更新、卸载选项
# - 自动检测现有安装，智能选择全新安装或更新流程
# - 自动修复过时的 Docker 基础镜像 (Buster -> Bullseye)
# - 自动为数据文件设置正确的写入权限
# 作者: 小龙女她爸 
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
    read -p "此操作将停止并删除所有相关的容器、网络、存储卷 (数据库和密钥) 以及项目文件。此过程不可逆！请输入 'yes' 确认: " confirmation

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
    else
        print_warning "未找到项目目录或 docker-compose.yml 文件，跳过 Docker 资源清理。"
    fi

    print_info "2. 移除项目目录 ${INSTALL_DIR}..."
    rm -rf "${INSTALL_DIR}"
    print_success "项目目录已删除。"
    
    echo ""
    print_success "Cloud Manager Docker 版已彻底卸载！"
}

install_or_update_docker_panel() {
    print_info "步骤 1: 检查并安装 Docker 环境..."
    if ! command -v docker &> /dev/null; then
        print_error "Docker 未安装。请先运行 'curl -fsSL https://get.docker.com | bash' 进行安装。"
    fi
    if ! docker compose version &> /dev/null; then
        print_error "Docker Compose (v2 插件) 未安装。请先运行 'apt-get update && apt-get install -y docker-compose-plugin' 进行安装。"
    fi
    print_success "Docker 环境检查通过。"

    # 更新流程
    if [ -d "${INSTALL_DIR}" ]; then
        print_info "步骤 2: 检测到现有安装，执行更新流程..."
        cd "${INSTALL_DIR}"
        
        print_info "正在从 Git 拉取最新代码..."
        git config --global --add safe.directory ${INSTALL_DIR}
        git pull
        
        # --- 优化点: 自动修复 Dockerfile ---
        print_info "正在检查并修复 Dockerfile..."
        sed -i 's/python:3.8-buster/python:3.8-bullseye/g' Dockerfile
        print_success "Dockerfile 已更新为 Bullseye 基础镜像。"

        print_info "正在重新构建镜像并启动服务 (这可能需要一些时间)..."
        docker compose up -d --build

        echo ""
        print_success "Cloud Manager Docker 版已更新并启动！"
        echo "------------------------------------------------------------"
        if [ -f ".env" ]; then
            # 从.env文件读取地址并显示
            source .env
            print_info "您的面板地址: ${DOMAIN_OR_IP}"
        fi
        print_info "请使用您之前设置的密码登录。"
        echo "------------------------------------------------------------"

    # 全新安装流程
    else
        print_info "步骤 2: 未检测到安装，执行全新安装..."
        git clone ${REPO_URL} ${INSTALL_DIR}
        cd ${INSTALL_DIR}

        print_info "步骤 3: 配置面板..."
        if [ -f ".env" ]; then
            print_info ".env 文件已存在，跳过创建。如需修改请手动编辑。"
        else
            print_info "从模板创建 .env 配置文件..."
            cp .env.example .env
        fi
        
        read -p "请输入您的域名 (留空则自动使用服务器公网IP): " domain_name

        if [ -z "$domain_name" ]; then
            print_info "未输入域名，正在尝试获取服务器公网IP..."
            ACCESS_ADDRESS=$(curl -s http://ipv4.icanhazip.com || curl -s http://ipinfo.io/ip)
            if [ -z "$ACCESS_ADDRESS" ]; then print_error "无法自动获取公网IP地址，请手动输入。"; exit 1; fi
            print_success "成功获取到公网IP: ${ACCESS_ADDRESS}"
        else
            ACCESS_ADDRESS=$domain_name
        fi

        read -s -p "请输入新的面板登录密码: " new_password; echo

        if [[ "$ACCESS_ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            CADDY_ADDRESS="http://${ACCESS_ADDRESS}"
            print_warning "检测到您使用的是IP地址，面板将以 HTTP (不安全) 方式运行。"
        else
            CADDY_ADDRESS=$ACCESS_ADDRESS
            print_success "检测到您使用的是域名，Caddy 将自动为您配置 HTTPS。"
        fi

        sed -i "s|^DOMAIN_OR_IP=.*|DOMAIN_OR_IP=${CADDY_ADDRESS}|" .env
        sed -i "s|^PANEL_PASSWORD=.*|PANEL_PASSWORD=${new_password}|" .env
        print_success "配置已保存到 .env 文件。"

        print_info "步骤 4: 创建空的密钥和数据库文件..."
        touch azure_keys.json oci_profiles.json key.txt azure_tasks.db oci_tasks.db

        # --- 优化点: 自动为数据文件设置正确的写入权限 ---
        print_info "为数据文件设置写入权限..."
        chmod 666 azure_keys.json oci_profiles.json key.txt azure_tasks.db oci_tasks.db
        print_success "权限设置完成。"
        
        # --- 优化点: 自动修复 Dockerfile ---
        print_info "正在修复 Dockerfile 以使用更新的基础镜像..."
        sed -i 's/python:3.8-buster/python:3.8-bullseye/g' Dockerfile
        print_success "Dockerfile 已更新。"

        print_info "步骤 5: 启动所有服务 (首次启动需要构建镜像，可能需要几分钟)..."
        docker compose up -d --build

        echo ""
        print_success "Cloud Manager Docker 版已成功部署！"
        echo "------------------------------------------------------------"
        if [[ "$ACCESS_ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            print_info "访问地址: http://${ACCESS_ADDRESS}"
        else
            print_info "访问地址: https://${ACCESS_ADDRESS}"
        fi
        print_info "登录密码: 您刚刚设置的密码"
        echo "------------------------------------------------------------"
    fi
}

# --- 脚本主入口 ---
if [ "$(id -u)" -ne 0 ]; then
    print_error "此脚本必须以root用户身份运行。"
fi

clear
print_info "欢迎使用 Cloud Manager Docker 版管理脚本"
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
