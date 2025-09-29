from telegram.ext import Application, CommandHandler, MessageHandler, filters
import os
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging

# --- 英文代码: 日志记录配置 ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- 英文代码: 您的Telegram用户ID ---
OWNER_ID = 5768851426  # 请确保这是您的正确用户ID

# --- 英文代码: 用于平台健康检查的虚拟服务器 ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

def run_server():
    port = int(os.getenv('PORT', 8080))
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    logging.info(f"Health check server is running on port {port}...")
    httpd.serve_forever()

# --- 英文代码: /start 命令的处理器 ---
async def start(update, context):
    # 中文提示
    welcome_message = '欢迎！您发送的任何消息（包括图片、表情等）都将被转发。'
    await update.message.reply_text(welcome_message)

# --- 英文代码: 转发所有消息类型的核心功能 ---
async def forward_any_message(update, context):
    user = update.message.from_user
    
    # 1. 先给主人发一条文字通知，包含用户ID
    # 中文提示
    info_text = f"收到来自 {user.first_name} (ID: {user.id}) 的一条消息:"
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=info_text)
        
    except Exception as e:
        logging.error(f"Error sending notification message to owner: {e}")

    # 2. 使用Telegram官方的 forward 功能，完美转发原始消息
    try:
        await update.message.forward(chat_id=OWNER_ID)
        
        # 中文提示
        confirmation_message = '您的消息已成功转发！'
        await update.message.reply_text(confirmation_message)
        logging.info(f"Successfully forwarded a message from user {user.id}")
        
    except Exception as e:
        logging.error(f"Error forwarding message: {e}")
        # 中文提示
        error_message = '抱歉，转发您的消息时遇到了一个错误。'
        await update.message.reply_text(error_message)

# --- 英文代码: 主函数 ---
def main():
    token = os.getenv('BOT_TOKEN')
    if not token:
        logging.error("FATAL ERROR: The BOT_TOKEN environment variable is not set!")
        return

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, forward_any_message))

    server_thread = Thread(target=run_server, daemon=True)
    server_thread.start()

    logging.info("Bot is starting...")
    app.run_polling()

if __name__ == '__main__':
    main()

