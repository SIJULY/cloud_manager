#!/bin/bash

# ==============================================================================
# Cloud Manager 三合一面板 一键安装脚本 (Docker版)

# 该脚本适用于一个全新的、基于 Debian/Ubuntu 的系统。

# 它会自动安装所有依赖、配置并启动服务。

# 作者: 小龙女她爸

# ==============================================================================

print_info() { echo -e "\e[34m[信息]\e[0m $1"; }
print_success() { echo -e "\e[32m[成功]\e[0m $1"; }
print_warning() { echo -e "\e[33m[警告]\e[0m $1"; }
print_error() { echo -e "\e[31m[错误]\e[0m $1"; exit 1; }

if [ "$(id -u)" -ne 0 ]; then print_error "此脚本必须以root用户身份运行。"; fi

if ! command -v docker &> /dev/null || ! command -v docker-compose &> /dev/null; then
    print_error "Docker 或 Docker Compose 未安装。请先安装它们后再运行此脚本。"
    exit 1
fi

if systemctl is-active --quiet caddy; then
    print_warning "检测到主机正在运行Caddy服务，为避免端口冲突，建议先停止。"
    read -p "是否需要脚本尝试停止主机的Caddy服务？(y/n): " stop_caddy
    if [ "$stop_caddy" = "y" ]; then
        systemctl stop caddy || true
        print_success "已尝试停止主机的Caddy服务。"
    fi
fi

if [ ! -f ".env" ]; then
    print_info "从模板创建 .env 配置文件..."
    cp .env.example .env
fi

print_info "请为您的面板进行配置..."
read -p "请输入您的域名或服务器IP: " domain_name
read -s -p "请输入新的面板登录密码: " new_password; echo

sed -i "s|^DOMAIN_OR_IP=.*|DOMAIN_OR_IP=${domain_name}|" .env
sed -i "s|^PANEL_PASSWORD=.*|PANEL_PASSWORD=${new_password}|" .env
print_success "配置已保存到 .env 文件。"

print_info "正在创建空的密钥和数据库文件..."
touch azure_keys.json oci_profiles.json key.txt azure_tasks.db oci_tasks.db

print_info "正在后台启动所有服务... (首次启动需要一些时间来构建镜像)"
docker-compose up -d --build

echo ""
print_success "Cloud Manager Docker 版已成功部署！"
echo "------------------------------------------------------------"
print_info "访问地址: http://${domain_name} 或 https://${domain_name}"
print_info "登录密码: 您刚刚设置的密码"
echo "------------------------------------------------------------"
