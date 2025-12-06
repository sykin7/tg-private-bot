import logging
import unicodedata
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import config
from database import init_db, check_user_status, clean_old_logs

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

cached_spam_keywords = set(config.SPAM_KEYWORDS)

def is_spam(text):
    if not text: return False
    safe_text = text[:2000]
    text_normalized = unicodedata.normalize('NFKC', safe_text).lower()
    
    for kw in cached_spam_keywords:
        if kw in text_normalized: return True
        
    cleaned = re.sub(r'[^\w\u4e00-\u9fa5]+', '', text_normalized)
    for kw in cached_spam_keywords:
        if kw.isalnum() and kw in cleaned: return True
            
    return False

async def delete_and_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target_message = update.message or update.edited_message
        if target_message:
            try:
                await target_message.delete()
            except Exception:
                pass

            if target_message.chat.type in ["group", "supergroup"]:
                await context.bot.ban_chat_member(
                    chat_id=target_message.chat_id,
                    user_id=target_message.from_user.id
                )
    except Exception as e:
        logger.error(f"Ban failed: {e}")

async def delete_system_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message:
            await update.message.delete()
    except Exception:
        pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message or update.edited_message
    if not message or not message.from_user:
        return

    user = message.from_user
    
    if user.id == config.ADMIN_ID:
        if message.chat.type == "private" and message.reply_to_message:
            try:
                original_text = message.reply_to_message.text or message.reply_to_message.caption or ""
                match = re.search(r"\(ID: (\d+)\)", original_text)
                
                if match:
                    target_user_id = int(match.group(1))
                    await message.copy(chat_id=target_user_id)
                    await message.reply_text("✅")
                else:
                    await message.reply_text("❌")
            except Exception as e:
                await message.reply_text(f"❌: {e}")
        return

    text = message.text or message.caption or ""
    
    if is_spam(text):
        logger.info(f"Spam detected: {user.id}")
        await delete_and_ban(update, context)
        return

    if update.edited_message:
        return

    status = await check_user_status(
        user.id, 
        config.RATE_LIMIT_WINDOW, 
        config.RATE_LIMIT_COUNT, 
        config.BAN_DURATION
    )

    if status == "BANNED":
        if message.chat.type != "private":
            await message.delete()
        return
    elif status == "BANNED_NOW":
        logger.info(f"Rate limit triggered: {user.id}")
        await delete_and_ban(update, context)
        return

    if message.chat.type == "private":
        try:
            info_header = f"📩 {user.first_name} (ID: {user.id}):\n\n"
            if message.text:
                await context.bot.send_message(
                    chat_id=config.ADMIN_ID, 
                    text=info_header + message.text
                )
            else:
                await message.copy(
                    chat_id=config.ADMIN_ID, 
                    caption=info_header + (message.caption or "")
                )
        except Exception as e:
            logger.error(f"Forward error: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == config.ADMIN_ID:
        await update.message.reply_text("🔰")
    else:
        await update.message.reply_text("👋")

async def scheduled_cleanup(context: ContextTypes.DEFAULT_TYPE):
    await clean_old_logs(config.LOG_RETENTION)

async def post_init(application: Application):
    await init_db()
    application.job_queue.run_repeating(scheduled_cleanup, interval=3600, first=10)
    logger.info("Database initialized.")

def main():
    application = Application.builder().token(config.TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.StatusUpdate.ALL, delete_system_message))
    
    combined_filter = (
        filters.TEXT | 
        filters.CAPTION | 
        filters.PHOTO | 
        filters.VIDEO | 
        filters.Sticker.ALL | 
        filters.Document.ALL
    )
    application.add_handler(MessageHandler(
        combined_filter | filters.UpdateType.EDITED_MESSAGE, 
        handle_message
    ))

    webhook_path = f"/{config.TOKEN}"
    full_webhook_url = f"{config.WEBHOOK_URL}{webhook_path}"
    
    logger.info(f"Starting webhook on port {config.PORT}")
    
    application.run_webhook(
        listen="0.0.0.0",
        port=config.PORT,
        url_path=config.TOKEN,
        webhook_url=full_webhook_url,
        health_check_endpoint="/"
    )

if __name__ == '__main__':
    main()
