import logging
import unicodedata
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import config
from database import init_db, check_user_status, clean_old_logs

# 设置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

cached_spam_keywords = set(config.SPAM_KEYWORDS)

# --- 辅助函数 ---

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

# --- 消息处理核心 ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message or update.edited_message
    if not message or not message.from_user:
        return

    user = message.from_user
    
    # 场景 A: 管理员回复消息
    if user.id == config.ADMIN_ID:
        if message.chat.type == "private" and message.reply_to_message:
            try:
                original_text = message.reply_to_message.text or message.reply_to_message.caption or ""
                match = re.search(r"\(ID: (\d+)\)", original_text)
                
                if match:
                    target_user_id = int(match.group(1))
                    await message.copy(chat_id=target_user_id)
                    await message.reply_text("✅ 已回复")
                else:
                    await message.reply_text("❌ 无法提取用户ID，请引用正确的转发消息。")
            except Exception as e:
                await message.reply_text(f"❌ 发送失败: {e}")
        return

    # 场景 B: 普通用户/陌生人消息
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

    # 私聊转发给管理员
    if message.chat.type == "private":
        try:
            info_header = f"📩 来自 {user.first_name} (ID: {user.id}):\n\n"
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
        await update.message.reply_text("🔰 防御系统运行中 (管理员模式)")
    else:
        await update.message.reply_text("👋 你好，请直接留言，我会转告给管理员。")

# 定时清理任务 (适配 JobQueue)
async def scheduled_cleanup(context: ContextTypes.DEFAULT_TYPE):
    await clean_old_logs(config.LOG_RETENTION)

async def post_init(application: Application):
    """启动后的初始化操作"""
    await init_db()
    # 添加定时任务：每1小时清理一次日志
    application.job_queue.run_repeating(scheduled_cleanup, interval=3600, first=10)
    logger.info("Database initialized and cleanup job scheduled.")

def main():
    # 创建 Application
    application = Application.builder().token(config.TOKEN).post_init(post_init).build()

    # 注册处理器
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

    # 启动 Webhook
    # 这里的 URL 拼接非常关键，确保 telegram 能送达
    webhook_path = f"/{config.TOKEN}"
    full_webhook_url = f"{config.WEBHOOK_URL}{webhook_path}"
    
    logger.info(f"Starting webhook on port {config.PORT}")
    
    application.run_webhook(
        listen="0.0.0.0",
        port=config.PORT,
        url_path=config.TOKEN,
        webhook_url=full_webhook_url,
        health_check_endpoint="/"  # 这是一个隐藏功能，访问根目录返回 OK，给云平台保活
    )

if __name__ == '__main__':
    main()
