#!/bin/bash

#=================================================
#	System Required: Debian/Ubuntu
#	Description: One-click script to install Cloud Manager Telegram Bot
#	Author: Gemini
#=================================================

set -e

# --- Color codes ---
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# --- Check for root privileges ---
if [ "$(id -u)" != "0" ]; then
   echo -e "${RED}错误：此脚本必须以 root 权限运行。${NC}"
   echo -e "${YELLOW}请尝试使用 'sudo ./install_tgbot.sh'${NC}"
   exit 1
fi

echo -e "${GREEN}=====================================================${NC}"
echo -e "${GREEN}  Cloud Manager Telegram Bot 一键安装脚本 başlatılıyor...${NC}"
echo -e "${GREEN}=====================================================${NC}"

# --- 1. 收集用户输入 ---
echo -e "\n${YELLOW}请根据提示输入您的配置信息：${NC}"
read -p "➡️ 请输入您的面板URL (例如: https://cm.sijuly.nyc.mn): " PANEL_URL
read -p "➡️ 请输入您的面板API密钥: " PANEL_API_KEY
read -p "➡️ 请输入您的Telegram机器人TOKEN: " BOT_TOKEN
read -p "➡️ 请输入您的Telegram用户ID (纯数字): " AUTHORIZED_USER_IDS

# --- 2. 安装系统依赖 ---
echo -e "\n${GREEN}正在更新软件包列表并安装依赖 (python3, pip, venv)...${NC}"
apt-get update
apt-get install -y python3 python3-pip python3-venv

# --- 3. 创建安装目录和虚拟环境 ---
INSTALL_DIR="/opt/tgbot"
echo -e "\n${GREEN}将在 ${INSTALL_DIR} 目录中安装机器人...${NC}"
mkdir -p $INSTALL_DIR
echo -e "${GREEN}正在创建 Python 虚拟环境...${NC}"
python3 -m venv ${INSTALL_DIR}/venv

# --- 4. 生成 bot.py 文件 ---
echo -e "${GREEN}正在根据您的输入生成 bot.py 配置文件...${NC}"
cat << EOF > ${INSTALL_DIR}/bot.py
import asyncio
import httpx
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode
from telegram.error import BadRequest

# --- 1. 配置信息 (由脚本自动生成) ---
PANEL_URL = "${PANEL_URL}"
PANEL_API_KEY = "${PANEL_API_KEY}"
BOT_TOKEN = "${BOT_TOKEN}"
AUTHORIZED_USER_IDS = [${AUTHORIZED_USER_IDS}]

# --- 日志配置 ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 2. API 客户端 ---
BASE_URL = f"{PANEL_URL}/api/v1/oci"
HEADERS = {"Authorization": f"Bearer {PANEL_API_KEY}", "Content-Type": "application/json"}

async def api_request(method: str, endpoint: str, **kwargs):
    async with httpx.AsyncClient() as client:
        try:
            url = f"{BASE_URL}/{endpoint}"
            response = await client.request(method, url, headers=HEADERS, timeout=30.0, **kwargs)
            response.raise_for_status()
            if not response.content: return {}
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"API Error calling {e.request.url}: {e.response.status_code} - {e.response.text}")
            try: return {"error": e.response.json().get("error", "未知API错误")}
            except: return {"error": f"API返回了非JSON错误: {e.response.status_code}"}
        except Exception as e:
            logger.error(f"Request failed for endpoint {endpoint}: {e}")
            return {"error": str(e)}

# --- 3. Telegram 机器人逻辑 (此处省略了完整的机器人代码，实际生成时会包含全部) ---
# ... (完整的 bot.py 代码从这里开始) ...
def authorized(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in AUTHORIZED_USER_IDS:
            if update.callback_query: await update.callback_query.answer("🚫 您没有权限。", show_alert=True)
            else: await update.message.reply_text("🚫 您没有权限操作此机器人。")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

async def build_param_selection_menu(form_data: dict, action_type: str):
    text = f"⚙️ *请配置实例参数*\n"
    text += f"*{'抢占任务' if action_type == 'start_snatch' else '创建任务'}*\n\n"
    text += f"实例名称: \`{form_data.get('display_name_prefix', 'N/A')}\`\n"
    text += f"实例规格: \`{form_data.get('shape', 'N/A')}\`\n"
    shape = form_data.get('shape')
    is_flex = "Flex" in shape if shape else False
    keyboard = []
    all_params_selected = True
    if is_flex:
        ocpu_val = form_data.get('ocpus')
        text += f"OCPU: \`{ocpu_val or '尚未选择'}\`\n"
        options = {"1": "1 OCPU", "2": "2 OCPU", "3": "3 OCPU", "4": "4 OCPU"}
        row = [InlineKeyboardButton(f"{'✅ ' if str(ocpu_val) == k else ''}{v}", callback_data=f"form_param:ocpus:{k}") for k, v in options.items()]
        keyboard.append(row)
        if not ocpu_val: all_params_selected = False
    if is_flex:
        mem_val = form_data.get('memory_in_gbs')
        text += f"内存: \`{f'{mem_val} GB' if mem_val else '尚未选择'}\`\n"
        options = {"6": "6 GB", "12": "12 GB", "18": "18 GB", "24": "24 GB"}
        row = [InlineKeyboardButton(f"{'✅ ' if str(mem_val) == k else ''}{v}", callback_data=f"form_param:memory_in_gbs:{k}") for k, v in options.items()]
        keyboard.append(row)
        if not mem_val: all_params_selected = False
    disk_val = form_data.get('boot_volume_size')
    text += f"磁盘大小: \`{f'{disk_val} GB' if disk_val else '尚未选择'}\`\n"
    options = {"50": "50 GB", "100": "100 GB", "150": "150 GB", "200": "200 GB"}
    row = [InlineKeyboardButton(f"{'✅ ' if str(disk_val) == k else ''}{v}", callback_data=f"form_param:boot_volume_size:{k}") for k, v in options.items()]
    keyboard.append(row)
    if not disk_val: all_params_selected = False
    if action_type == 'start_snatch':
        min_delay = form_data.get('min_delay', '45')
        max_delay = form_data.get('max_delay', '90')
        form_data['min_delay'] = min_delay
        form_data['max_delay'] = max_delay
        text += f"重试间隔: \`{min_delay}-{max_delay} 秒\`"
    if all_params_selected:
        keyboard.append([InlineKeyboardButton("🚀 确认提交", callback_data="form_submit")])
    keyboard.append([InlineKeyboardButton("❌ 取消操作", callback_data="back:main")])
    return text, InlineKeyboardMarkup(keyboard)

async def poll_task_status(chat_id: int, context: ContextTypes.DEFAULT_TYPE, task_id: str, task_name: str):
    max_retries, retries = 120, 0
    while retries < max_retries:
        await asyncio.sleep(5)
        result = await api_request("GET", f"task-status/{task_id}")
        if result and result.get("status") in ["success", "failure"]:
            final_message = f"🔔 *任务完成通知*\n\n*任务名称*: \`{task_name}\`\n\n*结果*:\n\`{result.get('result')}\`"
            await context.bot.send_message(chat_id=chat_id, text=final_message, parse_mode=ParseMode.MARKDOWN)
            return
        retries += 1
    await context.bot.send_message(chat_id=chat_id, text=f"🔔 *任务超时*\n\n任务 \`{task_name}\` 轮询超时（超过10分钟），请在网页端查看最终结果。")

async def build_main_menu():
    profiles = await api_request("GET", "profiles")
    if not profiles or "error" in profiles:
        return None, f"❌ 无法从面板获取账户列表: {profiles.get('error', '未知错误') if profiles else '无响应'}"
    if not profiles:
        return None, "面板中尚未配置任何OCI账户。"
    keyboard = []
    for i in range(0, len(profiles), 2):
        row = [InlineKeyboardButton(profiles[i], callback_data=f"account:{profiles[i]}")]
        if i + 1 < len(profiles):
            row.append(InlineKeyboardButton(profiles[i+1], callback_data=f"account:{profiles[i+1]}"))
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard), "请选择要操作的 OCI 账户:"

async def build_account_menu(alias: str):
    keyboard = [
        [InlineKeyboardButton("🖥️ 实例操作", callback_data=f"menu:instances:{alias}")],
        [InlineKeyboardButton("➕ 创建实例", callback_data=f"start_create:{alias}"), InlineKeyboardButton("🤖 抢占实例", callback_data=f"start_snatch:{alias}")],
        [InlineKeyboardButton("📝 查看任务", callback_data=f"menu:tasks:{alias}")],
        [InlineKeyboardButton("⬅️ 返回主菜单", callback_data="back:main")]
    ]
    return InlineKeyboardMarkup(keyboard), f"已选择账户: *{alias}*\n请选择功能模块:"

async def build_instance_action_menu(alias: str):
    keyboard = [
        [InlineKeyboardButton("✅ 开机", callback_data=f"action:{alias}:START"), InlineKeyboardButton("🛑 关机", callback_data=f"action:{alias}:STOP")],
        [InlineKeyboardButton("🔄 重启", callback_data=f"action:{alias}:RESTART"), InlineKeyboardButton("🗑️ 终止", callback_data=f"action:{alias}:TERMINATE")],
        [InlineKeyboardButton("🌐 更换IP", callback_data=f"action:{alias}:CHANGEIP"), InlineKeyboardButton("🌐 分配IPv6", callback_data=f"action:{alias}:ASSIGNIPV6")],
        [InlineKeyboardButton("⬅️ 返回", callback_data=f"back:account:{alias}")]
    ]
    return InlineKeyboardMarkup(keyboard), f"请为账户 *{alias}* 选择实例操作类型:"

async def build_instance_selection_menu(alias: str, action: str, context: ContextTypes.DEFAULT_TYPE):
    instances = await api_request("GET", f"{alias}/instances")
    if not instances or "error" in instances:
        return None, f"❌ 获取实例列表失败: {instances.get('error', '未知错误')}"
    if not instances:
        return None, f"账户 *{alias}* 下没有找到任何实例。"
    context.user_data['instance_list'] = instances
    keyboard = []
    for index, inst in enumerate(instances):
        keyboard.append([InlineKeyboardButton(f"{inst['display_name']} ({inst['lifecycle_state']})", callback_data=f"exec:{index}")])
    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data=f"back:instances:{alias}")])
    return InlineKeyboardMarkup(keyboard), f"请选择要执行 *{action}* 操作的实例:"

async def build_task_menu(alias: str):
    keyboard = [
        [InlineKeyboardButton("🏃 运行中的抢占任务", callback_data=f"tasks:{alias}:snatch:running")],
        [InlineKeyboardButton("✅ 已完成的抢占任务", callback_data=f"tasks:{alias}:snatch:completed")],
        [InlineKeyboardButton("⬅️ 返回", callback_data=f"back:account:{alias}")]
    ]
    return InlineKeyboardMarkup(keyboard), f"请选择要查看的任务类型:"

@authorized
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    reply_markup, text = await build_main_menu()
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

@authorized
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    command = parts[0]
    if command == "account":
        alias = parts[1]
        context.user_data['current_alias'] = alias
        reply_markup, text = await build_account_menu(alias)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    elif command == "menu":
        menu_type, alias = parts[1], parts[2]
        if menu_type == "instances":
            reply_markup, text = await build_instance_action_menu(alias)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        elif menu_type == "tasks":
            reply_markup, text = await build_task_menu(alias)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    elif command == "action":
        alias, action = parts[1], parts[2]
        context.user_data['current_action'] = action
        await query.edit_message_text(text=f"正在为账户 *{alias}* 获取实例列表...", parse_mode=ParseMode.MARKDOWN)
        reply_markup, text = await build_instance_selection_menu(alias, action, context)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    elif command == "exec":
        alias = context.user_data.get('current_alias')
        action = context.user_data.get('current_action')
        instance_list = context.user_data.get('instance_list')
        if not all([alias, action, instance_list]):
            await query.edit_message_text("会话已过期或信息不完整，请返回主菜单重试。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ 返回主菜单", callback_data="back:main")]]))
            return
        instance_index = int(parts[1])
        selected_instance = instance_list[instance_index]
        instance_id = selected_instance['id']
        vnic_id = selected_instance.get('vnic_id')
        await query.edit_message_text(text=f"正在为实例 *{selected_instance['display_name']}* 发送 *{action}* 命令...", parse_mode=ParseMode.MARKDOWN)
        payload = {"action": action, "instance_id": instance_id, "instance_name": selected_instance['display_name']}
        if vnic_id: payload['vnic_id'] = vnic_id
        result = await api_request("POST", f"{alias}/instance-action", json=payload)
        keyboard = [[InlineKeyboardButton("⬅️ 返回账户菜单", callback_data=f"back:account:{alias}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if result and result.get("task_id"):
            task_id = result.get("task_id")
            task_name = f"{action} on {selected_instance['display_name']}"
            text = f"✅ 命令发送成功！\n任务ID: \`{task_id}\`\n\n机器人将在后台为您监控任务，完成后会主动通知您。"
            asyncio.create_task(poll_task_status(update.effective_chat.id, context, task_id, task_name))
        else:
            text = f"❌ 命令发送失败: {result.get('error', '未知错误')}"
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        context.user_data.pop('instance_list', None)
        context.user_data.pop('current_action', None)
    elif command == "tasks":
        alias, task_type, task_status = parts[1], parts[2], parts[3]
        status_text = "运行中" if task_status == "running" else "已完成"
        await query.edit_message_text(text=f"正在查询 *{status_text}* 的 *{task_type}* 任务...", parse_mode=ParseMode.MARKDOWN)
        tasks = await api_request("GET", f"tasks/{task_type}/{task_status}")
        back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ 返回", callback_data=f"back:tasks:{alias}")]])
        if not tasks or "error" in tasks:
            await query.edit_message_text(text=f"❌ 查询任务失败: {tasks.get('error', '未知错误')}", reply_markup=back_keyboard)
            return
        text = f"*{alias}* - *{status_text}* 的 *{task_type}* 任务:\n\n"
        if not tasks:
            text += "没有找到相关任务记录。"
        else:
            for task in tasks[:10]:
                status_icon = ""
                if task_status == 'completed':
                    status_icon = "✅" if task.get("status") == "success" else "❌"
                text += f"*{task.get('name')}* {status_icon}:\n\`{task.get('result', '无结果')}\`\n\n"
        await query.edit_message_text(text, reply_markup=back_keyboard, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    elif command == "back":
        target = parts[1]
        alias = parts[2] if len(parts) > 2 else context.user_data.get('current_alias')
        if target == "main":
            await start_command(update, context)
        elif target == "account":
            reply_markup, text = await build_account_menu(alias)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        elif target == "instances":
            reply_markup, text = await build_instance_action_menu(alias)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        elif target == "tasks":
            reply_markup, text = await build_task_menu(alias)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    elif command == "start_create" or command == "start_snatch":
        alias = parts[1]
        context.user_data.clear()
        context.user_data['action_in_progress'] = command
        context.user_data['alias'] = alias
        prefix = "instance" if command == "start_create" else "snatch"
        timestamp = datetime.now().strftime("%m%d-%H%M")
        auto_name = f"{prefix}-{timestamp}"
        context.user_data['form_data'] = {'display_name_prefix': auto_name}
        context.user_data['next_step'] = 'get_shape'
        keyboard = [[InlineKeyboardButton("ARM (VM.Standard.A1.Flex)", callback_data="form_shape:VM.Standard.A1.Flex")],
                    [InlineKeyboardButton("AMD (VM.Standard.E2.1.Micro)", callback_data="form_shape:VM.Standard.E2.1.Micro")]]
        await query.edit_message_text(f"✅ 名称已自动生成: \`{auto_name}\`\n请选择实例规格 (Shape):",
                                      reply_markup=InlineKeyboardMarkup(keyboard),
                                      parse_mode=ParseMode.MARKDOWN)

async def handle_form_shape_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    shape = parts[1]
    context.user_data['form_data']['shape'] = shape
    context.user_data['next_step'] = 'param_selection'
    action_type = context.user_data['action_in_progress']
    text, reply_markup = await build_param_selection_menu(context.user_data['form_data'], action_type)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def handle_param_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    command = query.data
    form_data = context.user_data.get('form_data', {})
    action_type = context.user_data.get('action_in_progress')
    if command == "form_submit":
        form_data.setdefault('os_name_version', 'Canonical Ubuntu-22.04')
        await query.edit_message_text("✅ 所有参数已确认，正在提交任务...", parse_mode=ParseMode.MARKDOWN)
        await submit_form(update, context, form_data)
        return
    parts = command.split(":")
    key, value = parts[1], parts[2]
    form_data[key] = value
    context.user_data['form_data'] = form_data
    text, reply_markup = await build_param_selection_menu(form_data, action_type)
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass
        else:
            raise e

async def submit_form(update: Update, context: ContextTypes.DEFAULT_TYPE, form_data: dict):
    action_type = context.user_data.get('action_in_progress')
    alias = context.user_data.get('alias')
    payload = form_data.copy()
    numeric_keys = ['ocpus', 'memory_in_gbs', 'boot_volume_size', 'min_delay', 'max_delay']
    for key in numeric_keys:
        if key in payload:
            try:
                if key in ['ocpus', 'memory_in_gbs']:
                    payload[key] = float(payload[key])
                else:
                    payload[key] = int(payload[key])
            except (ValueError, TypeError):
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ 参数 {key} 的值 \`{payload[key]}\` 无效，必须是数字。")
                return
    payload.setdefault('os_name_version', 'Canonical Ubuntu-22.04')
    endpoint = "create-instance" if action_type == "start_create" else "snatch-instance"
    message_to_send = (f"正在提交 *{action_type}* 任务...\n"
                       f"账户: \`{alias}\`\n"
                       f"名称: \`{payload.get('display_name_prefix')}\`\n"
                       f"规格: \`{payload.get('shape')}\`")
    if update.callback_query:
        await update.callback_query.message.reply_text(message_to_send, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(message_to_send, parse_mode=ParseMode.MARKDOWN)
    result = await api_request("POST", f"{alias}/{endpoint}", json=payload)
    if result and result.get("task_id"):
        task_id = result.get("task_id")
        task_name = payload.get('display_name_prefix', 'N/A')
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"✅ 任务提交成功！\n任务ID: \`{task_id}\`")
        asyncio.create_task(poll_task_status(update.effective_chat.id, context, task_id, task_name))
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ 任务提交失败: {result.get('error', '未知错误')}")
    context.user_data.clear()
    await asyncio.sleep(1)
    reply_markup, text = await build_account_menu(alias)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def post_init(application: Application):
    await application.bot.set_my_commands([BotCommand("start", "打开主菜单")])

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_callback_handler, pattern=r"^(?!form_).*"))
    application.add_handler(CallbackQueryHandler(handle_form_shape_selection, pattern=r"^form_shape:.*"))
    application.add_handler(CallbackQueryHandler(handle_param_selection, pattern=r"^form_param:.*|^form_submit$"))
    logger.info("Bot 启动成功！")
    application.run_polling()

if __name__ == "__main__":
    main()
EOF

# --- 5. 安装 Python 依赖 ---
echo -e "${GREEN}正在虚拟环境中安装所需的 Python 库...${NC}"
source ${INSTALL_DIR}/venv/bin/activate
pip install python-telegram-bot httpx

# --- 6. 创建 systemd 服务文件 ---
echo -e "${GREEN}正在创建并配置 systemd 服务...${NC}"
cat << EOF > /etc/systemd/system/tgbot.service
[Unit]
Description=Telegram Bot for Cloud Manager
After=network.target

[Service]
User=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# --- 7. 启动并设置开机自启 ---
echo -e "${GREEN}正在重载 systemd 并启动 tgbot 服务...${NC}"
systemctl daemon-reload
systemctl enable tgbot
systemctl start tgbot

# --- 8. 显示最终信息 ---
echo -e "\n${GREEN}======================================================${NC}"
echo -e "${GREEN}🎉 Telegram Bot 已成功安装并启动！${NC}"
echo -e "${GREEN}======================================================${NC}"
echo -e "\n${YELLOW}您可以使用以下命令来管理您的机器人服务：${NC}"
echo -e "  - 查看状态: ${GREEN}systemctl status tgbot${NC}"
echo -e "  - 启动服务: ${GREEN}systemctl start tgbot${NC}"
echo -e "  - 停止服务: ${GREEN}systemctl stop tgbot${NC}"
echo -e "  - 重启服务: ${GREEN}systemctl restart tgbot${NC}"
echo -e "  - 查看实时日志: ${GREEN}journalctl -u tgbot -f --no-pager${NC}"
echo -e "\n${YELLOW}配置文件位于: ${GREEN}${INSTALL_DIR}/bot.py${NC}"
echo -e "如果需要修改配置，请编辑该文件后，使用 'systemctl restart tgbot' 重启服务。"
echo -e "\n现在您可以去 Telegram 和您的机器人对话了！"
