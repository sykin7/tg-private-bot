import telebot
import logging
import time
import os
import re
import requests
import threading
from collections import defaultdict

BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID_STR = os.environ.get('ADMIN_ID')
ADMIN_ID = int(ADMIN_ID_STR) if ADMIN_ID_STR else None

FALLBACK_SPAM_KEYWORDS = [
    "u币", "USDT", "泰达币", "跑分", "博彩", "兼职", "刷单", "各行各业", "代开", 
    "发票", "迷药", "枪支", "色情", "裸聊", "办证", "查询", "定位", "监听",
    "傻逼", "出u", "收u", "高价收"
]

DEFAULT_REMOTE_SPAM_URL = "https://raw.githubusercontent.com/sykin7/my-telegram-spam-rules/refs/heads/main/spam.txt"
REMOTE_SPAM_URL = os.environ.get('REMOTE_SPAM_URL', DEFAULT_REMOTE_SPAM_URL)

FLOOD_WINDOW = 10
MAX_MSGS_PER_WINDOW = 5

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if not BOT_TOKEN or not ADMIN_ID:
    logging.error("Error: BOT_TOKEN and ADMIN_ID must be set.")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

spam_keywords = set(FALLBACK_SPAM_KEYWORDS)
user_flood_control = defaultdict(list)

def update_spam_rules_thread():
    global spam_keywords
    while True:
        try:
            response = requests.get(REMOTE_SPAM_URL, timeout=10)
            if response.status_code == 200:
                remote_words = set(line.strip() for line in response.text.splitlines() if line.strip())
                custom_spam = os.environ.get('CUSTOM_SPAM_KEYWORDS', '')
                custom_words = set(w.strip() for w in custom_spam.split(',') if w.strip())
                spam_keywords = set(FALLBACK_SPAM_KEYWORDS) | remote_words | custom_words
                logging.info(f"Spam rules updated: {len(spam_keywords)} keywords.")
        except Exception as e:
            logging.error(f"Update rules failed: {e}")
        time.sleep(3600)

def check_flood(user_id):
    if len(user_flood_control) > 5000:
        user_flood_control.clear()
        
    now = time.time()
    timestamps = user_flood_control[user_id]
    valid_timestamps = [t for t in timestamps if now - t < FLOOD_WINDOW]
    
    if len(valid_timestamps) >= MAX_MSGS_PER_WINDOW:
        user_flood_control[user_id] = valid_timestamps
        return True
    
    valid_timestamps.append(now)
    user_flood_control[user_id] = valid_timestamps
    return False

def is_spam(text):
    if not text: return False
    clean_text = re.sub(r'\s+|[^\w]', '', text).lower()
    for keyword in spam_keywords:
        clean_keyword = re.sub(r'\s+|[^\w]', '', keyword).lower()
        if clean_keyword in clean_text:
            logging.info(f"Spam detected: {keyword}")
            return True
    return False

def get_sender_footer(user):
    first = user.first_name if user.first_name else "User"
    safe_first = re.sub(r'[^\w\s]', '', first)
    return f"\n\n----------------\n👤 {safe_first} | 🆔 ID: {user.id}"

def smart_truncate(text, footer, max_length):
    if not text: return footer
    available_len = max_length - len(footer) - 10
    if len(text) > available_len:
        return text[:available_len] + "..." + footer
    return text + footer

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "👋 Hello! Send me a message and I will forward it to the admin.")

# 修复点1: 增加了 'animation' (GIF) 支持
@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation'], 
                     func=lambda m: m.chat.type == 'private' and m.from_user.id != ADMIN_ID)
def handle_user_message(message):
    user = message.from_user
    if check_flood(user.id): return
    
    check_content = message.text or message.caption or ""
    if is_spam(check_content): return

    footer = get_sender_footer(user)

    try:
        if message.content_type == 'text':
            final_text = smart_truncate(message.text, footer, 4096)
            bot.send_message(ADMIN_ID, final_text)
        elif message.content_type == 'photo':
            photo_id = message.photo[-1].file_id
            caption = smart_truncate(message.caption, footer, 1024)
            bot.send_photo(ADMIN_ID, photo_id, caption=caption)
        elif message.content_type == 'video':
            caption = smart_truncate(message.caption, footer, 1024)
            bot.send_video(ADMIN_ID, message.video.file_id, caption=caption)
        elif message.content_type == 'document':
            caption = smart_truncate(message.caption, footer, 1024)
            bot.send_document(ADMIN_ID, message.document.file_id, caption=caption)
        elif message.content_type == 'voice':
            caption = smart_truncate(message.caption, footer, 1024)
            bot.send_voice(ADMIN_ID, message.voice.file_id, caption=caption)
        elif message.content_type == 'animation':  # 新增 GIF 处理
            caption = smart_truncate(message.caption, footer, 1024)
            bot.send_animation(ADMIN_ID, message.animation.file_id, caption=caption)
        elif message.content_type == 'sticker':
            bot.send_sticker(ADMIN_ID, message.sticker.file_id)
            # 修复点2: 优化提示语，防止管理员回复错误
            bot.send_message(ADMIN_ID, f"👆 Sticker Received (Reply to THIS message to answer)\n{footer}")
    except Exception as e:
        logging.error(f"Forward failed: {e}")

# 修复点3: 增加未知类型消息的兜底处理
@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id != ADMIN_ID, content_types=None)
def handle_unknown_message(message):
    try:
        user = message.from_user
        footer = get_sender_footer(user)
        bot.send_message(ADMIN_ID, f"⚠️ Received unknown message type ({message.content_type})\n{footer}")
    except:
        pass

@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation'],
                     func=lambda m: m.chat.id == ADMIN_ID and m.reply_to_message)
def handle_admin_reply(message):
    try:
        original_msg = message.reply_to_message
        content_to_search = original_msg.text or original_msg.caption or ""
        
        ids = re.findall(r"ID:\s*(\d+)", content_to_search)
        
        if ids:
            target_id = int(ids[-1])
            bot.copy_message(chat_id=target_id, from_chat_id=ADMIN_ID, message_id=message.message_id)
        else:
            # 针对管理员回复贴纸导致的报错，给出更智能的提示
            if original_msg.content_type == 'sticker':
                bot.reply_to(message, "⚠️ Error: You replied to a Sticker image. Please reply to the TEXT message below it containing the ID.")
            else:
                bot.reply_to(message, "⚠️ Error: Could not find User ID in the message you replied to.")

    except Exception as e:
        bot.reply_to(message, f"❌ Failed: {e}")

if __name__ == "__main__":
    logging.info("🚀 Bot started (V16.4 Complete Edition)...")
    
    update_thread = threading.Thread(target=update_spam_rules_thread, daemon=True)
    update_thread.start()
    
    try: bot.remove_webhook()
    except: pass
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
