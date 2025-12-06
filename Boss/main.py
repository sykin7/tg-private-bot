import logging
import asyncio
import socket
import re
import unicodedata
import httpx
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.error import Forbidden, BadRequest

from config import settings
from database import init_db, check_user_status, clean_old_logs

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

cached_spam_keywords = set(settings.FALLBACK_KEYWORDS)

class SilentHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass
    def do_GET(self):
        self.send_response(200)
        self.wfile.write(b'OK')

def run_health_server():
    socket.setdefaulttimeout(10)
    server = HTTPServer(('0.0.0.0', settings.PORT), SilentHandler)
    Thread(target=server.serve_forever, daemon=True).start()

async def update_rules_task():
    global cached_spam_keywords
    while True:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(settings.SPAM_RULES_URL, timeout=10)
            if resp.status_code == 200:
                new_rules = set()
                for line in resp.text.splitlines():
                    if line and not line.startswith('#'):
                        kw = line.split(':', 1)[-1].strip().lower()
                        if kw: new_rules.add(kw)
                if new_rules:
                    cached_spam_keywords = new_rules.union(settings.FALLBACK_KEYWORDS)
        except Exception:
            pass
        await asyncio.sleep(3600)

async def maintenance_task():
    while True:
        await asyncio.sleep(600)
        try: await clean_old_logs()
        except: pass

def is_spam(text):
    if not text: return False
    text = unicodedata.normalize('NFKC', text).lower()
    for kw in cached_spam_keywords:
        if kw in text: return True
    cleaned = re.sub(r'[\W_]+', '', text)
    for kw in cached_spam_keywords:
        if kw.isalnum() and kw in cleaned: return True
    return False

async def forward_handler(update, context):
    user = update.message.from_user
    
    status = await check_user_status(user.id, settings.FLOOD_WINDOW, settings.MAX_MSGS, settings.BAN_TIME)
    
    if status == "BANNED":
        return 
    if status == "BANNED_NOW":
        try: await update.message.reply_text(f"⛔ 触发防护，封禁 {settings.BAN_TIME//60} 分钟。")
        except: pass
        return

    text = update.message.text or update.message.caption or ""
    if is_spam(text):
        try: await update.message.reply_text("已拦截。")
        except: pass
        return

    header = f"📩 来自 {user.first_name} (ID: {user.id}):\n\n"
    try:
        if update.message.text:
            await context.bot.send_message(chat_id=settings.OWNER_ID, text=header + update.message.text[:4000])
        else:
            await update.message.copy(chat_id=settings.OWNER_ID, caption=header + (update.message.caption or "")[:1000])
    except Exception:
        pass

async def reply_handler(update, context):
    if not update.message.reply_to_message:
        return await update.message.reply_text("请回复消息。")
    
    target_id = None
    original = update.message.reply_to_message
    if original.forward_from:
        target_id = original.forward_from.id
    else:
        content = original.text or original.caption or ""
        match = re.search(r"\(ID: (\d+)\):", content)
        if match: target_id = int(match.group(1))

    if target_id:
        try:
            await update.message.copy(chat_id=target_id)
            await update.message.reply_text("✅ 已发送")
        except Exception as e:
            await update.message.reply_text(f"❌ 失败: {e}")
    else:
        await update.message.reply_text("❌ 无法识别用户ID")

async def post_init(app):
    await init_db()
    asyncio.create_task(update_rules_task())
    asyncio.create_task(maintenance_task())

def main():
    logger.info("启动企业级防御版 Bot...")
    app = Application.builder().token(settings.BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler('start', lambda u, c: u.message.reply_text("欢迎。")))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.User(settings.OWNER_ID) & filters.REPLY, reply_handler))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.User(settings.OWNER_ID), forward_handler))

    run_health_server()
    app.run_polling()

if __name__ == "__main__":
    main()
