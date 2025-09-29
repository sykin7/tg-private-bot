from telegram.ext import Application, CommandHandler, MessageHandler, filters
import os
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging

# English Code: Configure logging to see output
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# English Code: Your Telegram User ID
OWNER_ID = 5768851426  # e.g., 123456789

# English Code: A simple server for platform health checks
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

def run_server():
    port = int(os.getenv('PORT', 8080))
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    logging.info(f"Health check server starting on port {port}...")
    httpd.serve_forever()

# English Code: Handler for the /start command
async def start(update, context):
    # Chinese Prompt for the user
    welcome_message = '欢迎！您发送的任何消息（包括图片、表情等）都将被转发。'
    await update.message.reply_text(welcome_message)

# English Code: New handler to forward ANY type of message
async def forward_any_message(update, context):
    user = update.message.from_user
    
    # Chinese Prompt for the owner
    info_text = f"收到来自 {user.first_name} (ID: {user.id}) 的一条消息:"
    try:
        # First, send a text notification to the owner
        await context.bot。send_message(chat_id=OWNER_ID, text=info_text)
        
        # Then, forward the original message perfectly (preserves images, stickers, etc.)
        await update.message.forward(chat_id=OWNER_ID)
        
        # Chinese Prompt for the user
        confirmation_message = '您的消息已成功转发！'
        await update.message.reply_text(confirmation_message)
        logging.info(f"Successfully forwarded a message from user {user.id}")
        
    except Exception as e:
        logging.error(f"Failed to forward message: {e}")
        # Chinese Prompt for the user
        error_message = '抱歉，转发您的消息时遇到了一个错误。'
        await update.message.reply_text(error_message)

# English Code: Main function
def main():
    token = os.getenv('BOT_TOKEN')
    if not token:
        logging.error("FATAL: The BOT_TOKEN environment variable is not set!")
        return

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler('start', start))
    
    # --- KEY CHANGE IS HERE ---
    # Instead of filters.TEXT, we now use filters.ALL to capture everything.
    # We also call our new function 'forward_any_message'.
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, forward_any_message))

    server_thread = Thread(target=run_server, daemon=True)
    server_thread.start()

    logging.info("Bot is starting...")
    app.run_polling()

if __name__ == '__main__':
    main()
