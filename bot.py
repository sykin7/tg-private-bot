from telegram.ext import Application, CommandHandler, MessageHandler, filters
import os
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging

# Configure logging to see output
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Your Telegram User ID (replace with your actual ID)
OWNER_ID = 5768851426  # e.g., 123456789

# A simple server for platform health checks
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

# Handler for the /start command
async def start(update, context):
    await update.message.reply_text('Welcome! Your messages will be forwarded to the owner.')

# Handler to forward all other text messages
async def forward_message(update, context):
    user = update.message.from_user
    message_text = update.message.text or "[This was not a text message]"
    
    forward_text = f"Message from {user.first_name} (ID: {user.id}):\n\n{message_text}"
    
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=forward_text)
        await update.message.reply_text('Your message has been forwarded!')
    except Exception as e:
        logging.error(f"Failed to forward message: {e}")
        await update.message.reply_text('Sorry, an error occurred while forwarding your message.')

def main():
    token = os.getenv('BOT_TOKEN')
    if not token:
        logging.error("FATAL: The BOT_TOKEN environment variable is not set!")
        return

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, forward_message))

    server_thread = Thread(target=run_server, daemon=True)
    server_thread.start()

    logging.info("Bot is starting...")
    app.run_polling()

if __name__ == '__main__':
    main()

