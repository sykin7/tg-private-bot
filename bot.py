from telegram.ext import Application, CommandHandler, MessageHandler, filters
import os
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# 你的 Telegram 用户 ID（替换为实际 ID）
OWNER_ID = 5768851426  # 例如 123456789

# Dummy HTTP 服务器（监听 8080 用于健康检查）
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

def run_server():
    port = int(os.getenv('PORT', 8080))  # ClawCloud 默认 PORT=8080
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

async def start(update, context):
    await update.message.reply_text('欢迎！我是你的专属私聊机器人。你的消息会转发给主人。')

async def forward_message(update, context):
    user = update.message.from_user
    message = update.message。text or "非文本消息"
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"来自 {user.first_name} (ID: {user.id}): {message}"
    )
    await update.message.reply_text('消息已转发给主人！')

def main():
    token = os.getenv('BOT_TOKEN')
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, forward_message))

    # 启动 dummy HTTP 服务器（后台线程）
    server_thread = Thread(target=run_server, daemon=True)
    server_thread.start()

    # 启动 polling
    app.run_polling()

if __name__ == '__main__':
    main()
