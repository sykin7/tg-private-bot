# -*- coding: utf-8 -*-

from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import Forbidden, BadRequest
import os
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
import re
import httpx
import unicodedata
import time
import socket
from collections import defaultdict

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.WARNING 
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

OWNER_ID_STR = os.getenv('OWNER_ID')
if not OWNER_ID_STR:
    logger.error("Error: OWNER_ID not set")
    exit(1)
try:
    OWNER_ID = int(OWNER_ID_STR)
except ValueError:
    exit(1)

DEFAULT_RULE_URL = "https://raw.githubusercontent.com/sykin7/my-telegram-spam-rules/refs/heads/main/spam.txt"
SPAM_RULES_URL = os.getenv('SPAM_RULES_URL', DEFAULT_RULE_URL)

FALLBACK_SPAM_KEYWORDS = [
    "t.me/+", "joinchat", "crypto", "bitcoin", "trx", "usdt", "eth", "binance",
    "外围", "嫩模", "空降", "约炮", "色情", "博彩", "赌博", "代发", "发单",
    "上门", "点券", "换汇", "担保", "公群", "跑分", "网赚", "兼职",
    "u币", "傻逼", "u出", "出u", "收u", "高价收", "低价出", "支付宝", "微信支付"
]

FLOOD_WINDOW = 10
MAX_MSGS_PER_WINDOW = 5
user_flood_control = defaultdict(list)

async def update_spam_rules(context: ContextTypes.DEFAULT_TYPE):
    custom_keywords = context.bot_data.get('custom_keywords', [])
    final_rules_set = set(custom_keywords)
    
    final_rules_set.update(FALLBACK_SPAM_KEYWORDS)

    if SPAM_RULES_URL:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(SPAM_RULES_URL, timeout=15.0)
            if response.status_code == 200:
                for line in response.text.splitlines():
                    line = line.strip().lower()
                    if not line or line.startswith('#'): continue
                    keyword = line.split(':', 1)[-1].strip() if ':' in line else line
                    if keyword: final_rules_set.add(keyword)
            else:
                logger.warning(f"Failed to fetch rules, status: {response.status_code}")
        except Exception as e:
            logger.warning(f"Network error fetching rules: {e}")
    
    context.bot_data['spam_keywords'] = list(final_rules_set)

async def garbage_collect(context: ContextTypes.DEFAULT_TYPE):
    now = time.time()
    keys_to_remove = []
    
    for uid, timestamps in user_flood_control.items():
        if timestamps and (now - timestamps[-1] > FLOOD_WINDOW):
            keys_to_remove.append(uid)
        elif not timestamps:
            keys_to_remove.append(uid)
            
    if keys_to_remove:
        for uid in keys_to_remove:
            del user_flood_control[uid]

class HealthCheckHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass 

    def do_GET(self):
        self.send_response(200)
        self.wfile.write(b'OK')

def run_server():
    socket.setdefaulttimeout(10) 
    port = int(os.getenv('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    Thread(target=server.serve_forever, daemon=True).start()

async def start(update, context):
    await update.message.reply_text('Ready.')

def safe_cut_utf16(text, limit):
    if text is None: return ""
    if len(text) > limit:
        return text[:limit] + "..."
    return text

def is_spam(text, keywords):
    if not text: return False
    
    text_normalized = unicodedata.normalize('NFKC', text)
    text_lower = text_normalized.lower()
    
    for keyword in keywords:
        if keyword in text_lower: return True

    text_cleaned = re.sub(r'[\W_]+', '', text_lower)
    for keyword in keywords:
        if keyword.isalnum() and keyword in text_cleaned:
            return True
            
    return False

def clean_user_name(name):
    if not name: return "Unknown"
    name = name.replace("(ID:", "").replace(")", "")
    return "".join(ch for ch in name if unicodedata.category(ch) not in ['Cf', 'Cc'])

def check_flood(user_id):
    now = time.time()
    timestamps = user_flood_control[user_id]
    
    valid_timestamps = [t for t in timestamps if now - t < FLOOD_WINDOW]
    
    if len(valid_timestamps) < MAX_MSGS_PER_WINDOW:
        valid_timestamps.append(now)
        user_flood_control[user_id] = valid_timestamps
        return False 
    else:
        user_flood_control[user_id] = valid_timestamps
        return True 

async def forward_to_owner(update, context):
    user = update.message.from_user
    
    if check_flood(user.id):
        return 

    message = update.message
    message_text = message.text or message.caption or ""

    spam_keywords = context.bot_data.get('spam_keywords', [])
    if not spam_keywords:
        spam_keywords = FALLBACK_SPAM_KEYWORDS

    if is_spam(message_text, spam_keywords):
        try: await message.reply_text("Spam detected.")
        except: pass
        return

    clean_name = clean_user_name(user.first_name)
    user_header = f"📩 来自 {clean_name} (ID: {user.id}):\n\n"
    header_len = len(user_header)
    safe_limit = 4096 - header_len - 100

    try:
        if message.text:
            safe_text = safe_cut_utf16(message.text, safe_limit)
            await context.bot.send_message(chat_id=OWNER_ID, text=user_header + safe_text)
        
        elif message.photo or message.video or message.document or message.voice or message.audio or message.animation:
            original_caption = message.caption or ""
            caption_limit = 1024 - header_len - 50
            safe_caption = user_header + safe_cut_utf16(original_caption, caption_limit)
            await message.copy(chat_id=OWNER_ID, caption=safe_caption)

        else:
            await message.forward(chat_id=OWNER_ID)

    except Exception as e:
        logger.warning(f"Forward error: {e}")
        try: await message.forward(chat_id=OWNER_ID)
        except: pass

async def reply_to_user(update, context):
    if not update.message.reply_to_message:
        await update.message.reply_text("Please reply to a message.")
        return

    original_message = update.message.reply_to_message
    target_user_id = None
    
    if original_message.forward_from:
        target_user_id = original_message.forward_from.id
    elif original_message.text or original_message.caption:
        content = original_message.text or original_message.caption
        match = re.search(r"^📩 来自 .*? \(ID: (\d+)\):\n\n", content, re.DOTALL)
        if match:
            target_user_id = int(match.group(1))

    if target_user_id:
        try:
            await update.message.copy(chat_id=target_user_id)
            await update.message.reply_text(f"Sent.")
        except Forbidden:
            await update.message.reply_text(f"Failed: User blocked bot.")
        except BadRequest as e:
            await update.message.reply_text(f"Failed: {e}")
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
    else:
        await update.message.reply_text("Cannot find User ID.")

def main():
    token = os.getenv('BOT_TOKEN')
    if not token: return

    custom_words = [w.strip().lower() for w in os.getenv('CUSTOM_SPAM_KEYWORDS', "").split(',') if w.strip()]
    app = Application.builder().token(token).build()
    app.bot_data['custom_keywords'] = custom_words

    app.job_queue.run_once(update_spam_rules, 1)
    app.job_queue.run_repeating(update_spam_rules, interval=3600, first=10)
    app.job_queue.run_repeating(garbage_collect, interval=600, first=600)

    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler('start', start, filters=private))
    app.add_handler(MessageHandler(private & filters.User(user_id=OWNER_ID) & filters.REPLY & ~filters.COMMAND, reply_to_user))
    app.add_handler(MessageHandler(private & ~filters.COMMAND & ~filters.User(user_id=OWNER_ID), forward_to_owner))

    run_server()
    app.run_polling()

if __name__ == '__main__':
    main()
