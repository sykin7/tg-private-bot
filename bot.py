# -*- coding: utf-8 -*-

from telegram.ext import Application, CommandHandler, MessageHandler, filters
import os
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
import re

# --- V4版：日志记录配置 ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- 您的Telegram用户ID ---
OWNER_ID = 5768851426  # 请确保这是您的正确用户ID

# --- 用于平台健康检查的虚拟服务器 ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

def run_server():
    port = int(os.getenv('PORT', 8080))
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    logging.info(f"Health check server on port {port} is running...")
    httpd.serve_forever()

# --- /start 命令的处理器 ---
async def start(update, context):
    welcome_message = '欢迎！您发送的任何消息都将被转发给管理员。'
    await update.message.reply_text(welcome_message)

# --- 核心功能1: 转发普通用户的消息给主人 ---
async def forward_to_owner(update, context):
    user = update.message.from_user
    info_text = f"👇 收到来自 {user.first_name} (ID: {user.id}) 的一条新消息:"
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=info_text)
    except Exception as e:
        logging.error(f"Error sending notification to owner: {e}")

    try:
        await update.message.forward(chat_id=OWNER_ID)
        confirmation_message = '您的消息已成功发送！'
        await update.message.reply_text(confirmation_message)
        logging.info(f"Successfully forwarded message from user {user.id}")
    except Exception as e:
        logging.error(f"Error forwarding message: {e}")
        error_message = '抱歉，发送消息时遇到错误。'
        await update.message.reply_text(error_message)

# --- 核心功能2 (V4终极版): 处理主人的回复，兼容隐私模式 ---
async def reply_to_user(update, context):
    if update.message.reply_to_message:
        original_message = update.message.reply_to_message
        target_user_id = None
        
        # 方案A: 优先从转发信息获取ID (对未开启隐私保护的用户)
        if original_message.forward_from:
            target_user_id = original_message.forward_from.id
        
        # 方案B: 如果方案A失败 (对方开启隐私保护), 则从提示文字中解析ID
        elif original_message.from_user.id == context.bot.id and original_message.text:
            match = re.search(r"\(ID: (\d+)\)", original_message.text)
            if match:
                target_user_id = int(match.group(1))

        if target_user_id:
            try:
                await update.message.copy(chat_id=target_user_id)
                await update.message.reply_text(f"✅ 已成功回复给用户 (ID: {target_user_id})")
                logging.info(f"Successfully replied to user {target_user_id}")
            except Exception as e:
                logging.error(f"Failed to reply to user {target_user_id}: {e}")
                await update.message.reply_text(f"❌ 回复失败！错误: {e}")
        else:
            await update.message.reply_text("⚠️ 无法回复：请确保您“回复”到用户的转发消息，或者我发送的 `(ID:...)` 提示上。")

# --- 主函数 ---
def main():
    # 自我检查的版本号
    VERSION = "V4 - 隐私兼容最终版"
    logging.info(f"==========================================")
    logging.info(f"机器人正在启动... 版本: {VERSION}")
    logging.info(f"==========================================")
    
    token = os.getenv('BOT_TOKEN')
    if not token:
        logging.error("致命错误: 环境变量 BOT_TOKEN 未设置!")
        return

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.User(user_id=OWNER_ID) & filters.REPLY & ~filters.COMMAND, reply_to_user))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.User(user_id=OWNER_ID), forward_to_owner))

    server_thread = Thread(target=run_server, daemon=True)
    server_thread.start()

    app.run_polling()

if __name__ == '__main__':
    main()
