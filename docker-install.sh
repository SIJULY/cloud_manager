#!/bin/bash

# ==============================================================================
# Cloud Manager Docker版一键安装脚本 (作者: 小龙女她爸)
# ==============================================================================

# --- 配置 ---
INSTALL_DIR="/opt/cloud_manager"
REPO_URL="https://github.com/SIJULY/cloud_manager.git"
ENV_FILE="$INSTALL_DIR/.env"

# --- 辅助函数 ---
print_info() { echo -e "\e[34m[信息]\e[0m $1"; }
print_success() { echo -e "\e[32m[成功]\e[0m $1"; }
print_warning() { echo -e "\e[33m[警告]\e[0m $1"; }
print_error() { echo -e "\e[31m[错误]\e[0m $1"; exit 1; }

# --- 核心逻辑函数 ---

# 1. 生成 Docker 配置文件
generate_docker_config() {
    local mode=$1
    local port=${2:-5000} 

    print_info "正在生成 Docker 配置 (模式: $mode)..."

    if [ "$mode" == "ip" ]; then
        # === IP 模式 ===
        cat > docker-compose.override.yml <<EOF
version: '3.8'
services:
  web:
    ports:
      - "${port}:5000"
EOF
    else
        # === 域名模式 ===
        if [ ! -f "Caddyfile" ] || ! grep -q "reverse_proxy" "Caddyfile"; then
             if grep -q "DOMAIN_OR_IP=" "$ENV_FILE"; then
                 DOMAIN=$(grep "DOMAIN_OR_IP=" "$ENV_FILE" | cut -d= -f2)
             else
                 read -p "请输入您的域名: " DOMAIN
                 echo "DOMAIN_OR_IP=$DOMAIN" >> "$ENV_FILE"
             fi
             
             cat > Caddyfile <<EOF
$DOMAIN {
    reverse_proxy web:5000
}
EOF
        fi

        cat > docker-compose.override.yml <<EOF
version: '3.8'
services:
  web:
    expose:
      - "5000"
  caddy:
    image: caddy:latest
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
      - caddy_config:/config
    environment:
      - DOMAIN_OR_IP=\${DOMAIN_OR_IP}
    depends_on:
      - web
EOF
    fi
}

# 2. 环境检查 (修复重点：增加了错误检测)
prepare_environment() {
    # 检测是否安装 Docker
    if ! command -v docker &> /dev/null; then 
        print_warning "未检测到 Docker，正在准备安装..."
        
        # 尝试安装 Docker
        curl -fsSL https://get.docker.com | bash
        
        # --- [新增] 校验安装结果 ---
        if ! command -v docker &> /dev/null; then
            echo "----------------------------------------------------"
            print_error "Docker 安装失败！\n可能原因：系统后台正在进行更新(apt被占用)。\n解决方法：\n1. 请等待几分钟后重试。\n2. 或者运行 'rm /var/lib/apt/lists/lock' 强制解锁(需谨慎)。\n3. 手动运行 'apt install docker.io' 查看具体错误。"
        fi

        systemctl enable --now docker
        print_success "Docker 安装成功。"
    fi
    
    if [ ! -d "${INSTALL_DIR}" ]; then
        git clone ${REPO_URL} ${INSTALL_DIR}
    fi
    cd ${INSTALL_DIR}
    
    # 初始化文件
    touch azure_keys.json oci_profiles.json tg_settings.json key.txt azure_tasks.db oci_tasks.db
    chmod -R 777 .

    # 清理旧版逻辑
    if grep -q "docker-compose.yml" .gitignore 2>/dev/null; then
        sed -i "/docker-compose.yml/d" .gitignore
        git rm --cached docker-compose.yml > /dev/null 2>&1 || true
    fi
}

# 3. 安装逻辑 (IP模式)
install_ip_mode() {
    prepare_environment
    print_info "步骤: 配置 IP+端口 模式..."

    read -p "请输入新的面板登录密码: " new_password
    read -p "请输入要映射的主机端口 [默认: 5000]: " host_port
    host_port=${host_port:-5000}

    cp .env.example .env 2>/dev/null || touch .env
    sed -i "/PANEL_PASSWORD=/d" .env
    sed -i "/INSTALL_MODE=/d" .env
    
    echo "PANEL_PASSWORD=${new_password}" >> .env
    echo "INSTALL_MODE=ip" >> .env
    echo "HOST_PORT=${host_port}" >> .env

    generate_docker_config "ip" "$host_port"

    print_info "正在启动..."
    docker compose down --remove-orphans
    
    # --- [新增] 启动结果校验 ---
    if docker compose up -d --build; then
        SERVER_IP=$(curl -s ifconfig.me)
        print_success "安装完成！访问地址: http://${SERVER_IP}:${host_port}"
    else
        print_error "启动失败！请检查上方报错信息 (通常是端口冲突或配置错误)。"
    fi
}

# 4. 安装逻辑 (域名模式)
install_domain_mode() {
    prepare_environment
    print_info "步骤: 配置 域名+Caddy 模式..."

    read -p "请输入新的面板登录密码: " new_password
    read -p "请输入您的域名: " domain_name
    
    cp .env.example .env 2>/dev/null || touch .env
    sed -i "/PANEL_PASSWORD=/d" .env
    sed -i "/DOMAIN_OR_IP=/d" .env
    sed -i "/INSTALL_MODE=/d" .env

    echo "PANEL_PASSWORD=${new_password}" >> .env
    echo "DOMAIN_OR_IP=${domain_name}" >> .env
    echo "INSTALL_MODE=domain" >> .env

    generate_docker_config "domain"

    print_info "正在启动..."
    docker compose down --remove-orphans
    
    # --- [新增] 启动结果校验 ---
    if docker compose up -d --build; then
         print_success "安装完成！访问地址: https://${domain_name}"
    else
         print_error "启动失败！请检查上方报错信息。"
    fi
}

# 5. 更新逻辑
update_panel() {
    if [ ! -d "${INSTALL_DIR}" ]; then
        print_error "未找到安装目录，请先安装。"
    fi
    cd "${INSTALL_DIR}"

    print_info "正在拉取最新代码..."
    git fetch --all
    git reset --hard origin/main
    git pull

    if [ -f ".env" ]; then
        source .env
    fi

    if [ "$INSTALL_MODE" == "ip" ]; then
        print_info "检测到当前为: IP+端口模式"
        PORT=${HOST_PORT:-5000}
        generate_docker_config "ip" "$PORT"
    elif [ "$INSTALL_MODE" == "domain" ]; then
        print_info "检测到当前为: 域名模式"
        generate_docker_config "domain"
    else
        print_warning "未检测到历史模式配置 (可能是旧版首次更新)。"
        if [ -f "Caddyfile" ]; then
             print_info "发现 Caddyfile，自动识别为 [域名模式]。"
             echo "INSTALL_MODE=domain" >> .env
             generate_docker_config "domain"
        else
             print_info "未发现 Caddyfile，自动识别为 [IP模式]。"
             echo "INSTALL_MODE=ip" >> .env
             echo "HOST_PORT=5000" >> .env
             generate_docker_config "ip" "5000"
        fi
    fi

    print_info "正在重建容器..."
    docker compose down --remove-orphans
    if docker compose up -d --build; then
        print_success "更新完成！配置已保留。"
    else
        print_error "更新失败。"
    fi
}

# 6. 卸载逻辑
uninstall_panel() {
    print_warning "确定要卸载吗？(yes/no)"
    read -p "输入 yes 确认: " confirm
    if [ "$confirm" == "yes" ] && [ -d "${INSTALL_DIR}" ]; then
        cd "${INSTALL_DIR}"
        docker compose down -v
        cd ..
        rm -rf "${INSTALL_DIR}"
        print_success "卸载完成。"
    else
        print_info "取消卸载。"
    fi
}

# --- 菜单主入口 ---
if [ "$(id -u)" -ne 0 ]; then print_error "请使用 root 运行。"; fi
clear
print_info "Cloud Manager 管理脚本 (智能修复版)"
echo "=========================================================="
echo "  1) 安装: IP+端口模式 (适合已有 Nginx 或直接访问)"
echo "  2) 安装: 域名+Caddy模式 (自动 HTTPS，占用 80/443)"
echo "  3) 更新: 升级面板 (自动识别原有模式，不覆盖配置)"
echo "  4) 卸载: 删除所有文件和容器"
echo "  5) 退出"
echo "=========================================================="
read -p "请输入选项 [1-5]: " choice

case $choice in
    1) install_ip_mode ;;
    2) install_domain_mode ;;
    3) update_panel ;;
    4) uninstall_panel ;;
    5) exit 0 ;;
    *) print_error "无效选项" ;;
esac
