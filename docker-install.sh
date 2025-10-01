#!/bin/bash

# ==============================================================================
# Cloud Manager Docker版一键安装脚本 (V4 - 交互式预检版)
# 在配置外部Caddy前，增加交互式检查清单，提升成功率。
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
# ... (卸载、修复等函数与V3版本相同，为简洁省略)
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

    PORT_80_IN_USE=false
    if systemctl is-active --quiet caddy || ss -tuln | grep -q ':80 '; then
        print_warning "检测到现有Caddy服务或80端口已被占用，将强制进入外部代理模式。"; PORT_80_IN_USE=true
    fi

    if [ ! -f ".env" ]; then
        print_info "步骤 4: 首次安装，开始配置面板..."
        if [ "$PORT_80_IN_USE" = true ]; then
            print_info "将禁用内置的 Caddy 服务并暴露 Web 端口。"
            START_LINE=$(grep -n '^  caddy:' docker-compose.yml | cut -d: -f1); END_LINE=$(grep -n '^volumes:' docker-compose.yml | cut -d: -f1)
            if [ -n "$START_LINE" ] && [ -n "$END_LINE" ]; then
                COMMENT_END_LINE=$((END_LINE - 1)); sed -i "${START_LINE},${COMMENT_END_LINE}s/^/#/"; sed -i -e '/^  caddy_data:/s/^/#/' -e '/^  caddy_config:/s/^/#/' docker-compose.yml
            else
                print_error "无法在 docker-compose.yml 中定位 Caddy 服务块，自动化修改失败。"
            fi
            sed -i -e '/^  web:/,/^  worker:/s/    restart: always/    restart: always\n    ports:\n      - "8000:5000"/' docker-compose.yml
            cp .env.example .env
            read -p "请输入您要为Cloud Manager分配的域名 (例如 cm.example.com): " domain_name
            if [ -z "$domain_name" ]; then print_error "使用外部代理时，必须提供一个域名。"; fi
            read -s -p "请输入新的面板登录密码: " new_password; echo
            sed -i "s|^PANEL_PASSWORD=.*|PANEL_PASSWORD=${new_password}|" .env; export FINAL_DOMAIN_NAME=$domain_name; USE_EXTERNAL_PROXY=true
        else
            print_info "未检测到端口冲突，将使用内置Caddy进行安装。"; cp .env.example .env
            read -p "请输入您的域名 (留空则自动使用服务器公网IP): " domain_name
            if [ -z "$domain_name" ]; then ACCESS_ADDRESS=$(curl -s http://ipv4.icanhazip.com || curl -s http://ipinfo.io/ip); if [ -z "$ACCESS_ADDRESS" ]; then print_error "无法自动获取公网IP地址。"; fi
            else ACCESS_ADDRESS=$domain_name; fi
            read -s -p "请输入新的面板登录密码: " new_password; echo
            CADDY_ADDRESS=$([[ "$ACCESS_ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && echo "http://${ACCESS_ADDRESS}" || echo "$ACCESS_ADDRESS")
            sed -i "s|^DOMAIN_OR_IP=.*|DOMAIN_OR_IP=${CADDY_ADDRESS}|" .env; sed -i "s|^PANEL_PASSWORD=.*|PANEL_PASSWORD=${new_password}|" .env; USE_EXTERNAL_PROXY=false
        fi
        print_success "配置已保存到 .env 文件。"
    else
        print_info "步骤 4: .env 文件已存在，跳过配置。"; if [ "$PORT_80_IN_USE" = true ] && grep -q "# caddy:" docker-compose.yml; then USE_EXTERNAL_PROXY=true; fi
    fi

    print_info "步骤 5: 启动所有服务 (可能需要构建镜像，请耐心等待)..."
    if ! docker compose up -d --build; then
        print_error "Docker Compose 启动失败！请检查上面的日志输出。安装已终止。"
    fi
    
    echo ""; print_success "Cloud Manager Docker 版已成功部署/更新！"; echo "------------------------------------------------------------"

    if [ "$USE_EXTERNAL_PROXY" = true ]; then
        if [ -n "$FINAL_DOMAIN_NAME" ]; then
            CADDY_FILE="/etc/caddy/Caddyfile"
            
            # ================= V4 新增逻辑开始 =================
            echo ""
            print_warning "脚本即将修改您系统的 Caddy 服务，为域名 '${FINAL_DOMAIN_NAME}' 启用 HTTPS。"
            print_warning "为确保成功，请在继续前，务必手动确认以下两点："
            echo "    1.  【DNS 解析】：域名 '${FINAL_DOMAIN_NAME}' 是否已设置了 A 记录，并正确指向本服务器的公网 IP？"
            echo "    2.  【防火墙端口】：本服务器的云平台安全组或系统防火墙，是否已对公网开放了 TCP 的 80 和 443 端口？"
            echo ""
            read -p "您是否已确认以上两点均已配置正确？[y/N]: " confirm_prereqs

            if [[ "$confirm_prereqs" =~ ^[Yy]$ ]]; then
                print_info "好的，将继续尝试自动配置..."
                if [ ! -f "$CADDY_FILE" ]; then print_error "未找到标准的Caddy配置文件: ${CADDY_FILE}。"; fi
                if grep -q "${FINAL_DOMAIN_NAME}" "$CADDY_FILE"; then
                    print_success "检测到配置文件中已存在域名 ${FINAL_DOMAIN_NAME} 的配置，跳过修改。"
                else
                    print_info "正在停止现有的Caddy服务（服务会短暂中断）..."; systemctl stop caddy
                    print_info "正在向 ${CADDY_FILE} 追加新配置..."
                    CONFIG_BLOCK="\n${FINAL_DOMAIN_NAME} {\n    reverse_proxy localhost:8000\n}\n"
                    echo -e "$CONFIG_BLOCK" | tee -a "$CADDY_FILE" > /dev/null
                    print_info "正在重新启动Caddy服务..."; systemctl start caddy
                    sleep 3
                    if systemctl is-active --quiet caddy; then
                        print_success "Caddy服务已成功重启！"; print_info "您的面板现在应该可以通过 https://${FINAL_DOMAIN_NAME} 访问了。"
                    else
                        print_error "Caddy服务启动失败！请立即手动检查配置文件 ${CADDY_FILE} 并通过 'journalctl -u caddy' 查看日志进行修复！"
                    fi
                fi
            else
                print_info "已跳过自动配置。"; echo ""
                print_info "请在您完成 DNS 和防火墙设置后，手动执行以下命令来完成最后一步：";
                echo "    echo -e \"\n${FINAL_DOMAIN_NAME} {\\n    reverse_proxy localhost:8000\\n}\" | sudo tee -a ${CADDY_FILE}"
                echo "    sudo systemctl reload caddy"
            fi
            # ================= V4 新增逻辑结束 =================
        fi
    else
        source .env; print_info "访问地址: ${DOMAIN_OR_IP}"; print_info "登录密码: 您设置的密码"
    fi
    echo "------------------------------------------------------------"
}

# --- 脚本主入口 ---
if [ "$(id -u)" -ne 0 ]; then print_error "此脚本必须以root用户身份运行。"; fi
clear
echo "=============================================================================="
print_warning "本脚本将尝试自动检测并修改您系统中现有的Caddy服务配置。"; print_warning "这是一个高风险操作，可能导致您服务器上所有网站短暂中断或配置失败。"
echo "=============================================================================="
read -p "您已了解风险并希望继续吗？ [y/N]: " confirm_risk
if [[ ! "$confirm_risk" =~ ^[Yy]$ ]]; then print_info "操作已取消。"; exit 0; fi

print_info "欢迎使用 Cloud Manager Docker 版管理脚本 (V4-交互式预检版)"
echo "==============================================="
echo "请选择要执行的操作:"; echo "  1) 安装 或 更新 面板 (默认选项)"; echo "  2) 彻底卸载 面板"; echo "  3) 退出脚本"; echo "==============================================="
read -p "请输入选项数字 [1]: " choice
choice=${choice:-1}
case $choice in 1) install_or_update_docker_panel ;; 2) uninstall_docker_panel ;; 3) print_info "操作已取消，退出脚本。"; exit 0 ;; *) print_error "无效的选项。";; esac
