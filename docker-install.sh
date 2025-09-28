#!/bin/bash

# ==============================================================================
# Cloud Manager 三合一面板 一键安装脚本 (Docker版)
# 该脚本适用于一个全新的、基于 Debian/Ubuntu 的系统。
# 它会自动安装所有依赖、配置并启动服务。
# 作者: 小龙女她爸
# ==============================================================================

# --- 辅助函数 ---
print_info() { echo -e "\e[34m[信息]\e[0m $1"; }
print_success() { echo -e "\e[32m[成功]\e[0m $1"; }
print_warning() { echo -e "\e[33m[警告]\e[0m $1"; }
print_error() { echo -e "\e[31m[错误]\e[0m $1"; exit 1; }

# --- 脚本主逻辑 ---
if [ "$(id -u)" -ne 0 ]; then
   print_error "此脚本必须以root用户身份运行。"
fi

# 1. 检查 Docker 和 Docker Compose 是否安装
if ! command -v docker &> /dev/null || ! command -v docker-compose &> /dev/null; then
    print_error "Docker 或 Docker Compose 未安装。请先安装它们后再运行此脚本。"
    print_info "Docker 安装教程: https://docs.docker.com/engine/install/"
    print_info "Docker Compose 安装教程: https://docs.docker.com/compose/install/"
    exit 1
fi

# 2. 检查端口冲突
if systemctl is-active --quiet caddy || lsof -i :80 -i :443 &>/dev/null; then
    print_warning "检测到您的主机可能正在使用80或443端口（例如，已安装了Caddy或Nginx）。"
    print_warning "Docker版的Caddy也需要使用这些端口。为避免冲突，请先停止您主机上的Web服务器。"
    read -p "是否需要脚本尝试停止主机的Caddy服务？(y/n): " stop_caddy
    if [ "$stop_caddy" = "y" ]; then
        systemctl stop caddy || true
        print_success "已尝试停止主机的Caddy服务。"
    fi
fi

# 3. 创建并配置 .env 文件
if [ -f ".env" ]; then
    print_info ".env 文件已存在，跳过创建。如需修改请手动编辑。"
else
    print_info "从模板创建 .env 配置文件..."
    cp .env.example .env
fi

# ★★★ 新增的智能IP检测逻辑 ★★★
print_info "请为您的面板进行配置..."
read -p "请输入您的域名 (留空则自动使用服务器公网IP): " domain_name

if [ -z "$domain_name" ]; then
    print_info "未输入域名，正在尝试获取服务器公网IP..."
    ACCESS_ADDRESS=$(curl -s http://ipv4.icanhazip.com || curl -s http://ipinfo.io/ip)
    if [ -z "$ACCESS_ADDRESS" ]; then
        print_error "无法自动获取公网IP地址，请手动输入。"
        exit 1
    fi
    print_success "成功获取到公网IP: ${ACCESS_ADDRESS}"
else
    ACCESS_ADDRESS=$domain_name
fi

read -s -p "请输入新的面板登录密码: " new_password
echo

# 使用 sed 安全地替换 .env 文件中的值
sed -i "s|^DOMAIN_OR_IP=.*|DOMAIN_OR_IP=${ACCESS_ADDRESS}|" .env
sed -i "s|^PANEL_PASSWORD=.*|PANEL_PASSWORD=${new_password}|" .env
print_success "配置已保存到 .env 文件。"

# 4. 创建空的密钥和数据库文件
print_info "正在创建空的密钥和数据库文件..."
touch azure_keys.json oci_profiles.json key.txt azure_tasks.db oci_tasks.db

# 5. 启动 Docker Compose
print_info "正在后台启动所有服务... (首次启动需要一些时间来构建镜像)"
docker-compose up -d --build

echo ""
print_success "Cloud Manager Docker 版已成功部署！"
echo "------------------------------------------------------------"
if [ -z "$domain_name" ]; then
    print_info "访问地址: http://${ACCESS_ADDRESS}"
else
    print_info "访问地址: https://${ACCESS_ADDRESS}"
fi
print_info "登录密码: 您刚刚设置的密码"
echo "------------------------------------------------------------"
