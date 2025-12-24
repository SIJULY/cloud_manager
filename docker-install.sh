#!/bin/bash

# ==============================================================================
# Cloud Manager Docker版一键安装脚本 (作者: 小龙女她爸)
# ==============================================================================

# 定义颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

APP_DIR="/opt/cloud_manager"
ENV_FILE="$APP_DIR/.env"

echo -e "${GREEN}=== 正在启动 Cloud Manager 智能安装程序 ===${NC}"

# ------------------------------------------
# 1. 环境检查与 Docker 安装
# ------------------------------------------
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}未检测到 Docker，正在自动安装...${NC}"
    curl -fsSL https://get.docker.com | bash -s docker
    systemctl enable --now docker
else
    echo -e "${GREEN}Docker 环境检查通过。${NC}"
fi

# ------------------------------------------
# 2. 拉取/更新代码
# ------------------------------------------
if [ ! -d "$APP_DIR" ]; then
    echo -e "${YELLOW}正在克隆仓库...${NC}"
    git clone https://github.com/SIJULY/cloud_manager.git "$APP_DIR"
    cd "$APP_DIR" || exit
else
    cd "$APP_DIR" || exit
    echo -e "${YELLOW}正在拉取最新代码...${NC}"
    
    # === 关键修正：清理旧脚本造成的污染 ===
    # 如果 .gitignore 里有 docker-compose.yml，说明是旧版环境，清理掉
    if grep -q "docker-compose.yml" .gitignore 2>/dev/null; then
        sed -i "/docker-compose.yml/d" .gitignore
    fi
    # 强制重置代码，确保 docker-compose.yml 回归纯净
    git fetch --all
    git reset --hard origin/main
    git pull
fi

# ------------------------------------------
# 3. 智能模式识别
# ------------------------------------------

# 加载 .env 变量
if [ -f "$ENV_FILE" ]; then
    set -a
    source <(grep -v '^#' "$ENV_FILE" | sed 's/^export //')
    set +a
fi

# 如果 .env 里没有 INSTALL_MODE，尝试根据旧环境猜测或询问
if [ -z "$INSTALL_MODE" ]; then
    echo -e "\n${YELLOW}>>> 部署模式配置 <<<${NC}"
    
    # 自动探测逻辑：如果当前没有 Caddyfile，或者用户之前的 .env 设置了 IP，则默认为 IP 模式
    DEFAULT_CHOICE="1"
    if [ -f "Caddyfile" ]; then
        echo -e "检测到存在 Caddyfile，推荐使用域名模式。"
        DEFAULT_CHOICE="1"
    else
        echo -e "未检测到 Caddy 配置，推荐使用 IP 模式。"
        DEFAULT_CHOICE="2"
    fi

    echo "1) 域名自动 HTTPS 模式 (安装 Caddy，占用 80/443)"
    echo "2) IP/自定义端口模式 (不安装 Caddy，仅暴露 5000，适合自建 Nginx)"
    
    read -p "请输入选项 [1/2] (默认 $DEFAULT_CHOICE): " mode_choice
    mode_choice=${mode_choice:-$DEFAULT_CHOICE}
    
    if [ "$mode_choice" == "2" ]; then
        INSTALL_MODE="ip"
    else
        INSTALL_MODE="domain"
    fi

    # 写入 .env 实现永久记忆
    if [ ! -f "$ENV_FILE" ]; then touch "$ENV_FILE"; fi
    if ! grep -q "INSTALL_MODE=" "$ENV_FILE"; then
        echo "" >> "$ENV_FILE"
        echo "# 部署模式记忆" >> "$ENV_FILE"
        echo "INSTALL_MODE=$INSTALL_MODE" >> "$ENV_FILE"
    fi
    echo -e "${GREEN}模式已保存: $INSTALL_MODE${NC}"
fi

# ------------------------------------------
# 4. 动态生成 Override 配置 (这是解决你问题的核心)
# ------------------------------------------
echo -e "${YELLOW}正在生成 Docker 配置...${NC}"

if [ "$INSTALL_MODE" == "ip" ]; then
    # === IP 模式 ===
    cat > docker-compose.override.yml <<EOF
version: '3.8'
services:
  web:
    ports:
      - "5000:5000"
EOF
    echo -e "${GREEN}已配置: Web 服务运行在 5000 端口，Caddy 已禁用。${NC}"

else
    # === 域名模式 ===
    
    # 确保 Caddyfile 存在
    if [ ! -f "Caddyfile" ] || ! grep -q "reverse_proxy" "Caddyfile"; then
        read -p "请输入您的域名 (例如 example.com): " USER_DOMAIN
        if ! grep -q "DOMAIN_OR_IP=" "$ENV_FILE"; then
            echo "DOMAIN_OR_IP=$USER_DOMAIN" >> "$ENV_FILE"
        fi
        cat > Caddyfile <<EOF
$USER_DOMAIN {
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
    echo -e "${GREEN}已配置: Caddy 反代模式 (80/443)。${NC}"
fi

# ------------------------------------------
# 5. 初始化密码 (仅首次)
# ------------------------------------------
if [ ! -f "$ENV_FILE" ] || ! grep -q "PANEL_PASSWORD" "$ENV_FILE"; then
    echo -e "\n${YELLOW}>>> 初始化设置 <<<${NC}"
    read -p "请设置管理员登录密码: " ADMIN_PWD
    echo "PANEL_PASSWORD=$ADMIN_PWD" >> "$ENV_FILE"
fi

# ------------------------------------------
# 6. 启动服务
# ------------------------------------------
echo -e "${YELLOW}正在构建并启动容器...${NC}"

# 清理可能的旧容器和孤儿容器 (这会清理掉旧脚本产生的残留)
docker compose down --remove-orphans

if docker compose up -d --build; then
    echo -e "\n${GREEN}=======================================${NC}"
    echo -e "${GREEN}   安装/更新成功！服务已启动。${NC}"
    if [ "$INSTALL_MODE" == "ip" ]; then
        PUBLIC_IP=$(curl -s ifconfig.me)
        echo -e "访问地址: http://$PUBLIC_IP:5000"
        echo -e "注意: 您当前使用的是 IP 模式，请配置 Nginx 反代或直接访问。"
    else
        echo -e "访问地址: https://(您的域名)"
    fi
    echo -e "${GREEN}=======================================${NC}"
else
    echo -e "${RED}启动失败，请检查 Docker 日志。${NC}"
fi
