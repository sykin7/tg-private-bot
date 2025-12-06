import asyncio
import logging
import unicodedata
import re
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import config
from database import init_db, check_user_status, clean_old_logs

# 设置日志级别
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

app = Flask(__name__)
bot_app = Application.builder().token(config.TOKEN).build()
bot = Bot(token=config.TOKEN)

cached_spam_keywords = set(config.SPAM_KEYWORDS)

# --- 辅助函数 ---

def is_spam(text):
    if not text: return False
    # 截断防止 CPU 炸弹
    safe_text = text[:2000]
    text_normalized = unicodedata.normalize('NFKC', safe_text).lower()
    
    for kw in cached_spam_keywords:
        if kw in text_normalized: return True
        
    cleaned = re.sub(r'[^\w\u4e00-\u9fa5]+', '', text_normalized)
    for kw in cached_spam_keywords:
        if kw.isalnum() and kw in cleaned: return True
            
    return False

async def delete_and_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    智能封禁：自动识别是群组还是私聊
    """
    try:
        target_message = update.message or update.edited_message
        if target_message:
            # 1. 尝试删除消息
            try:
                await target_message.delete()
            except Exception:
                pass # 私聊里可能删不掉对方的消息，忽略

            # 2. 如果是群组，执行踢人 API
            if target_message.chat.type in ["group", "supergroup"]:
                await context.bot.ban_chat_member(
                    chat_id=target_message.chat_id,
                    user_id=target_message.from_user.id
                )
            else:
                # 私聊不需要踢人，数据库标记为 BANNED 即可
                # 可以选择回复一句提示，或者直接静默
                pass
    except Exception as e:
        print(f"Ban failed: {e}")

async def delete_system_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """秒删系统服务消息（入群、退群等）"""
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
    
    # ------------------ 场景 A: 管理员回复消息 ------------------
    if user.id == config.ADMIN_ID:
        # 如果是管理员在私聊里回复
        if message.chat.type == "private" and message.reply_to_message:
            try:
                # 尝试从回复的消息文本中提取 ID
                # 格式参考下方: (ID: 123456)
                original_text = message.reply_to_message.text or message.reply_to_message.caption or ""
                match = re.search(r"\(ID: (\d+)\)", original_text)
                
                if match:
                    target_user_id = int(match.group(1))
                    # 将管理员的消息复制给目标用户
                    await message.copy(chat_id=target_user_id)
                    await message.reply_text("✅ 已回复")
                else:
                    await message.reply_text("❌ 无法提取用户ID，请引用正确的转发消息。")
            except Exception as e:
                await message.reply_text(f"❌ 发送失败: {e}")
        return

    # ------------------ 场景 B: 普通用户/陌生人消息 ------------------
    
    text = message.text or message.caption or ""
    
    # 1. 广告检测
    if is_spam(text):
        print(f"Spam detected: {user.id}")
        await delete_and_ban(update, context)
        return

    # 编辑过的消息不计入频率，但如果通过了广告检测就放行（防止重复转发）
    if update.edited_message:
        return

    # 2. 频率/数据库黑名单检测
    status = await check_user_status(
        user.id, 
        config.RATE_LIMIT_WINDOW, 
        config.RATE_LIMIT_COUNT, 
        config.BAN_DURATION
    )

    if status == "BANNED":
        # 黑名单用户，直接无视或删除
        if message.chat.type != "private":
            await message.delete()
        return
    elif status == "BANNED_NOW":
        print(f"Rate limit triggered: {user.id}")
        await delete_and_ban(update, context)
        return
    elif status == "ERROR":
        pass

    # 3. 【核心修复】转发给管理员
    # 只有私聊消息才转发，群组消息通常不需要全部转发给管理员（除非你需要监控）
    if message.chat.type == "private":
        try:
            # 构造包含 ID 的头部，方便管理员回复时提取
            info_header = f"📩 来自 {user.first_name} (ID: {user.id}):\n\n"
            
            if message.text:
                await context.bot.send_message(
                    chat_id=config.ADMIN_ID, 
                    text=info_header + message.text
                )
            else:
                # 如果是图片/视频，用 copy 方法并附带 ID 说明
                await message.copy(
                    chat_id=config.ADMIN_ID, 
                    caption=info_header + (message.caption or "")
                )
        except Exception as e:
            print(f"Forward error: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 根据身份发送不同欢迎语
    if update.effective_user.id == config.ADMIN_ID:
        await update.message.reply_text("🔰 防御系统运行中 (管理员模式)")
    else:
        await update.message.reply_text("👋 你好，请直接留言，我会转告给管理员。")

async def periodic_cleanup():
    while True:
        await asyncio.sleep(3600)
        await clean_old_logs(config.LOG_RETENTION)

# --- Webhook 与启动 ---

@app.route(f'/{config.TOKEN}', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    asyncio.run(bot_app.process_update(update))
    return "OK"

@app.route('/')
def index():
    return "Service Running"

async def main():
    await init_db()
    
    bot_app.add_handler(CommandHandler("start", start))
    
    # 优先拦截系统消息 (StatusUpdate)
    bot_app.add_handler(MessageHandler(filters.StatusUpdate.ALL, delete_system_message))

    # 综合过滤器
    combined_filter = (
        filters.TEXT | 
        filters.CAPTION | 
        filters.PHOTO | 
        filters.VIDEO | 
        filters.Sticker.ALL | 
        filters.Document.ALL
    )
    
    bot_app.add_handler(MessageHandler(
        combined_filter | filters.UpdateType.EDITED_MESSAGE, 
        handle_message
    ))
    
    await bot_app.initialize()
    await bot_app.start()
    
    # 设置 Webhook
    await bot.set_webhook(url=f"{config.WEBHOOK_URL}/{config.TOKEN}")
    
    loop = asyncio.get_event_loop()
    loop.create_task(periodic_cleanup())
    
    # 启动 Flask Server
    app.run(host="0.0.0.0", port=config.PORT)

if __name__ == '__main__':
    asyncio.run(main())
