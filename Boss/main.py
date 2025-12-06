import asyncio
import logging
import unicodedata
import re
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import config
from database import init_db, check_user_status, clean_old_logs

logging.basicConfig(level=logging.ERROR)

app = Flask(__name__)
bot_app = Application.builder().token(config.TOKEN).build()
bot = Bot(token=config.TOKEN)

cached_spam_keywords = set(config.SPAM_KEYWORDS)

def is_spam(text):
    if not text: return False
    safe_text = text[:1000]
    text_normalized = unicodedata.normalize('NFKC', safe_text).lower()
    
    for kw in cached_spam_keywords:
        if kw in text_normalized: return True
        
    cleaned = re.sub(r'[\W_]+', '', text_normalized)
    for kw in cached_spam_keywords:
        if kw.isalnum() and kw in cleaned: return True
    return False

async def delete_and_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.delete()
        await context.bot.ban_chat_member(
            chat_id=update.message.chat_id,
            user_id=update.message.from_user.id
        )
    except Exception:
        pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    
    if user.id == config.ADMIN_ID:
        return

    text = update.message.text or update.message.caption or ""
    
    if is_spam(text):
        await delete_and_ban(update, context)
        return

    status = await check_user_status(
        user.id, 
        config.RATE_LIMIT_WINDOW, 
        config.RATE_LIMIT_COUNT, 
        config.BAN_DURATION
    )

    if status == "BANNED":
        await update.message.delete()
    elif status == "BANNED_NOW":
        await delete_and_ban(update, context)
    elif status == "ERROR":
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Service running.")

async def periodic_cleanup():
    while True:
        await asyncio.sleep(3600)
        await clean_old_logs(config.LOG_RETENTION)

@app.route(f'/{config.TOKEN}', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    asyncio.run(bot_app.process_update(update))
    return "OK"

@app.route('/')
def index():
    return "Running"

async def main():
    await init_db()
    
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.TEXT | filters.CAPTION, handle_message))
    
    await bot_app.initialize()
    await bot_app.start()
    
    await bot.set_webhook(url=f"{config.WEBHOOK_URL}/{config.TOKEN}")
    
    loop = asyncio.get_event_loop()
    loop.create_task(periodic_cleanup())
    
    app.run(host="0.0.0.0", port=config.PORT)

if __name__ == '__main__':
    asyncio.run(main())
