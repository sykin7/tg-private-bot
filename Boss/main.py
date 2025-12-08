import logging
import unicodedata
import re
import os
import random
import asyncio
from logging.handlers import RotatingFileHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import config
from database import init_db, check_user_status, update_user_status, clean_old_logs, get_all_users

os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        RotatingFileHandler('logs/bot.log', maxBytes=5*1024*1024, backupCount=3),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

cached_spam_keywords = set(config.SPAM_KEYWORDS)
ID_PATTERN = re.compile(r"\(ID: (\d+)\)")
CLEAN_PATTERN = re.compile(r'[^\w\u4e00-\u9fa5]+')

verification_attempts = {}
admin_queue = asyncio.Queue(maxsize=1000)

async def delete_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, message_id = job.data
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

def schedule_auto_delete(context, message, delay=5):
    if message:
        context.job_queue.run_once(delete_job, delay, data=(message.chat_id, message.message_id))

def is_spam(text):
    if not text: return False
    safe_text = text[:2000]
    text_normalized = unicodedata.normalize('NFKC', safe_text).lower()
    for kw in cached_spam_keywords:
        if kw in text_normalized: return True
    cleaned = CLEAN_PATTERN.sub('', text_normalized)
    for kw in cached_spam_keywords:
        if kw.isalnum() and kw in cleaned: return True
    return False

def generate_math_captcha():
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    correct_answer = num1 + num2
    options = {correct_answer}
    while len(options) < 4:
        fake = correct_answer + random.randint(-5, 5)
        if fake > 0: options.add(fake)
    buttons_list = list(options)
    random.shuffle(buttons_list)
    keyboard = []
    row = []
    for num in buttons_list:
        row.append(InlineKeyboardButton(str(num), callback_data=f"verify:{correct_answer}:{num}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    return num1, num2, InlineKeyboardMarkup(keyboard)

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != config.ADMIN_ID: return

    message_text = update.message.text.partition(' ')[2]
    try:
        await update.message.delete()
    except Exception:
        pass

    if not message_text:
        msg = await update.message.reply_text("⚠️ 格式错误: /gb 内容")
        schedule_auto_delete(context, msg, 5)
        return

    status_msg = await update.message.reply_text("⏳ 广播中...")
    success_count = 0
    fail_count = 0
    
    try:
        users = await get_all_users()
        for (uid,) in users:
            try:
                if uid == config.ADMIN_ID: continue
                await context.bot.send_message(chat_id=uid, text=f"📢 **公告**\n\n{message_text}", parse_mode="Markdown")
                success_count += 1
                await asyncio.sleep(0.05)
            except Exception:
                fail_count += 1
        
        final_report = await context.bot.send_message(
            chat_id=config.ADMIN_ID,
            text=f"✅ **广播完成**\n成功: {success_count}\n失败: {fail_count}"
        )
        schedule_auto_delete(context, final_report, 60)
        schedule_auto_delete(context, status_msg, 1)

    except Exception as e:
        err_msg = await context.bot.send_message(chat_id=config.ADMIN_ID, text=f"❌ 错误: {e}")
        schedule_auto_delete(context, err_msg, 60)

async def background_sender(context: ContextTypes.DEFAULT_TYPE):
    while True:
        try:
            task = await admin_queue.get()
            if task:
                target_id, text, reply_id = task
                try:
                    await context.bot.send_message(chat_id=target_id, text=text, reply_to_message_id=reply_id)
                except Exception as e:
                    logger.error(f"Queue send error: {e}")
            admin_queue.task_done()
        except asyncio.CancelledError: break
        except Exception: await asyncio.sleep(1)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message or update.edited_message
    if not message or not message.from_user: return
    user = message.from_user
    
    if user.id == config.ADMIN_ID:
        if message.chat.type == ChatType.PRIVATE and message.reply_to_message:
            try:
                if message.reply_to_message.from_user.id != context.bot.id: return
                original_text = message.reply_to_message.text or message.reply_to_message.caption or ""
                match = ID_PATTERN.search(original_text)
                if match:
                    target_user_id = int(match.group(1))
                    await context.bot.copy_message(chat_id=target_user_id, from_chat_id=message.chat_id, message_id=message.message_id)
                    success_msg = await message.reply_text("✅")
                    schedule_auto_delete(context, success_msg, 5)
            except Exception as e:
                err_msg = await message.reply_text(f"❌: {e}")
                schedule_auto_delete(context, err_msg, 5)
        return

    text = message.text or message.caption or ""
    if is_spam(text):
        try:
            await message.delete()
            if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
                await context.bot.ban_chat_member(message.chat_id, user.id)
        except: pass
        return

    status = await check_user_status(user.id, config.RATE_LIMIT_WINDOW, config.RATE_LIMIT_COUNT, config.BAN_DURATION)
    
    if status != "OK":
        if status in ["BANNED", "FLOOD_BANNED", "FLOOD_BANNED_NOW"]:
            try: await message.delete()
            except: pass
        elif status == "UNVERIFIED" and message.chat.type == ChatType.PRIVATE:
            n1, n2, markup = generate_math_captcha()
            verify_msg = await message.reply_text(
                f"🤖 **人机验证**\n\n{n1} + {n2} = ?\n⚠️ 3次错误自动封禁",
                reply_markup=markup, parse_mode="Markdown"
            )
            schedule_auto_delete(context, verify_msg, 60)
        return

    if message.chat.type == ChatType.PRIVATE:
        info_header = f"📩 {user.first_name} (ID: {user.id}):\n\n"
        full_text = info_header + (message.text or "[Media]")
        try:
            admin_queue.put_nowait((config.ADMIN_ID, full_text, None))
            if not message.text:
                await message.copy(chat_id=config.ADMIN_ID, caption=info_header + (message.caption or ""))
        except asyncio.QueueFull: pass

async def delete_system_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message: await update.message.delete()
    except: pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    status = await check_user_status(user.id, config.RATE_LIMIT_WINDOW, config.RATE_LIMIT_COUNT, config.BAN_DURATION)
    
    if user.id == config.ADMIN_ID:
        msg = await update.message.reply_text("🔰")
        schedule_auto_delete(context, msg, 5)
    elif status == "OK":
        msg = await update.message.reply_text("👋")
        schedule_auto_delete(context, msg, 5)
    else:
        n1, n2, markup = generate_math_captcha()
        msg = await update.message.reply_text(
            f"🤖 **人机验证**\n\n{n1} + {n2} = ?\n⚠️ 3次错误自动封禁",
            reply_markup=markup, parse_mode="Markdown"
        )
        schedule_auto_delete(context, msg, 60)

async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if not query.data.startswith("verify:"): await query.answer(); return

    try:
        _, real_ans, clicked_ans = query.data.split(":")
        if user_id not in verification_attempts: verification_attempts[user_id] = 0

        if real_ans == clicked_ans:
            await query.answer("✅")
            await update_user_status(user_id, "OK")
            verification_attempts.pop(user_id, None)
            await query.edit_message_text("✅")
            schedule_auto_delete(context, query.message, 5)
        else:
            verification_attempts[user_id] += 1
            attempts_left = 3 - verification_attempts[user_id]
            
            if attempts_left <= 0:
                await update_user_status(user_id, "BANNED")
                await query.answer("❌ 封禁", show_alert=True)
                await query.edit_message_text("🚫")
                schedule_auto_delete(context, query.message, 5)
            else:
                await query.answer(f"❌ 剩余 {attempts_left} 次", show_alert=True)
                n1, n2, markup = generate_math_captcha()
                await query.edit_message_text(
                    f"❌\n{n1} + {n2} = ?",
                    reply_markup=markup,
                    parse_mode="Markdown"
                )
    except Exception as e:
        logger.error(f"Verify error: {e}")

async def scheduled_cleanup(context: ContextTypes.DEFAULT_TYPE):
    await clean_old_logs(config.LOG_RETENTION)

async def post_init(application: Application):
    await init_db()
    application.job_queue.run_repeating(scheduled_cleanup, interval=3600, first=10)
    asyncio.create_task(background_sender(ContextTypes.DEFAULT_TYPE(application.bot, application)))
    logger.info("Ready")

def main():
    application = Application.builder().token(config.TOKEN).post_init(post_init).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("gb", broadcast_command))
    application.add_handler(CallbackQueryHandler(verify_callback))
    application.add_handler(MessageHandler(filters.StatusUpdate.ALL, delete_system_message))
    application.add_handler(MessageHandler(filters.ALL | filters.UpdateType.EDITED_MESSAGE, handle_message))
    
    logger.info(f"Port {config.PORT}")
    application.run_webhook(
        listen="0.0.0.0", port=config.PORT, url_path=config.TOKEN,
        webhook_url=f"{config.WEBHOOK_URL}/{config.TOKEN}", health_check_endpoint="/"
    )

if __name__ == '__main__':
    main()
