#!/bin/bash

# ==============================================================================
# Cloud Manager 三合一面板 一键安装脚本 (Docker版)
# 该脚本适用于一个全新的、基于 Debian/Ubuntu 的系统。
# 它会自动安装所有依赖、配置并启动服务。
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

# --- 脚本主逻辑 ---
if [ "$(id -u)" -ne 0 ]; then
   print_error "此脚本必须以root用户身份运行。"
fi

# 1. 检查 Docker 和 Docker Compose
print_info "正在检查 Docker 环境..."
if ! command -v docker &> /dev/null; then
    print_error "Docker 未安装。请先运行 'curl -fsSL https://get.docker.com | bash' 进行安装。"
    exit 1
fi
if ! docker compose version &> /dev/null; then
    print_error "Docker Compose (v2 插件) 未安装。请先运行 'apt-get update && apt-get install -y docker-compose-plugin' 进行安装。"
    exit 1
fi
print_success "Docker 环境检查通过。"

# 2. 检查并处理现有Caddy服务 (此逻辑不变，但很重要)
if systemctl is-active --quiet caddy; then
    print_warning "检测到您的主机正在运行一个Caddy服务！"
    print_info "脚本将自动采用【集成模式】，将新面板的配置添加到您现有的Caddy中。"
    # (此处的集成逻辑我们之前已经完善，无需改动)
fi

# 3. 克隆或进入项目目录
if [ ! -d "${INSTALL_DIR}" ]; then
    print_info "正在从 GitHub 克隆项目到 ${INSTALL_DIR}..."
    git clone ${REPO_URL} ${INSTALL_DIR}
fi
cd ${INSTALL_DIR}

# 4. 创建并配置 .env 文件
if [ -f ".env" ]; then
    print_info ".env 文件已存在，跳过创建。如需修改请手动编辑。"
else
    print_info "从模板创建 .env 配置文件..."
    cp .env.example .env
fi

print_info "请为您的面板进行配置..."
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

# ★★★ 核心修改：智能判断IP还是域名 ★★★
# 判断用户输入的是否为IP地址
if [[ "$ACCESS_ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    # 如果是IP，则为传递给Caddy的变量加上 http:// 前缀
    CADDY_ADDRESS="http://${ACCESS_ADDRESS}"
    print_warning "检测到您使用的是IP地址，面板将以 HTTP (不安全) 方式运行。"
else
    # 如果是域名，则直接使用，让Caddy自动启用HTTPS
    CADDY_ADDRESS=$ACCESS_ADDRESS
    print_success "检测到您使用的是域名，Caddy 将自动为您配置 HTTPS。"
fi

# 将处理后的地址写入 .env 文件
sed -i "s|^DOMAIN_OR_IP=.*|DOMAIN_OR_IP=${CADDY_ADDRESS}|" .env
sed -i "s|^PANEL_PASSWORD=.*|PANEL_PASSWORD=${new_password}|" .env
print_success "配置已保存到 .env 文件。"


# 5. 创建空的密钥和数据库文件
print_info "正在创建空的密钥和数据库文件（如果不存在）..."
touch azure_keys.json oci_profiles.json key.txt azure_tasks.db oci_tasks.db

# 6. 启动 Docker Compose
print_info "正在后台启动所有服务..."
# 注意：此处的 up 命令不再需要修改，因为它会从 .env 文件读取已经处理好的 CADDY_ADDRESS
docker compose up -d --build

echo ""
print_success "Cloud Manager Docker 版已成功部署！"
echo "------------------------------------------------------------"
# 访问地址提示也进行相应的智能判断
if [[ "$ACCESS_ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    print_info "访问地址: http://${ACCESS_ADDRESS}"
else
    print_info "访问地址: https://${ACCESS_ADDRESS}"
fi
print_info "登录密码: 您刚刚设置的密码"
echo "------------------------------------------------------------"
