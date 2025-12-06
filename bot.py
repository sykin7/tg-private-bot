import telebot
from telebot import apihelper
import logging
import time
import os
import re
import requests
import threading
from collections import defaultdict

# ================= 配置区域 =================
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID_STR = os.environ.get('ADMIN_ID') or os.environ.get('OWNER_ID')
ADMIN_ID = int(ADMIN_ID_STR) if ADMIN_ID_STR else None

# 默认垃圾词库
FALLBACK_SPAM_KEYWORDS = [
    "u币", "USDT", "泰达币", "跑分", "博彩", "兼职", "刷单", "各行各业", "代开", 
    "发票", "迷药", "枪支", "色情", "裸聊", "办证", "查询", "定位", "监听",
    "傻逼", "出u", "收u", "高价收"
]

DEFAULT_REMOTE_SPAM_URL = "https://raw.githubusercontent.com/sykin7/my-telegram-spam-rules/refs/heads/main/spam.txt"
REMOTE_SPAM_URL = os.environ.get('REMOTE_SPAM_URL', DEFAULT_REMOTE_SPAM_URL)

FLOOD_WINDOW = 10
MAX_MSGS_PER_WINDOW = 5
FLOOD_PENALTY_TIME = 60
MAX_MAP_SIZE = 50000 
MAP_CLEANUP_INTERVAL = 3600 * 6

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if not BOT_TOKEN or not ADMIN_ID:
    logging.error("Error: BOT_TOKEN and ADMIN_ID must be set.")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

spam_keywords = set(FALLBACK_SPAM_KEYWORDS)
user_flood_control = defaultdict(list)
user_penalty_status = {}
MESSAGE_MAP = {} 

# ================= 核心功能函数 (未修改) =================

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
    
    if user_id in user_penalty_status and user_penalty_status[user_id] > now:
        return True
    
    if user_id in user_penalty_status and user_penalty_status[user_id] <= now:
        del user_penalty_status[user_id]

    timestamps = user_flood_control[user_id]
    valid_timestamps = [t for t in timestamps if now - t < FLOOD_WINDOW]
    
    is_flooding = len(valid_timestamps) >= MAX_MSGS_PER_WINDOW
    
    if is_flooding:
        user_penalty_status[user_id] = now + FLOOD_PENALTY_TIME
        user_flood_control[user_id] = []
        return True
    
    valid_timestamps.append(now)
    user_flood_control[user_id] = valid_timestamps
    return False

def is_spam(text):
    if not text: return False
    clean_text = re.sub(r'\s+|[^\w]', '', text).lower()
    for keyword in spam_keywords:
        clean_keyword = re.sub(r'\s+|[^\w]', '', keyword).lower()
        if not clean_keyword: 
            continue
        if clean_keyword in clean_text:
            logging.info(f"Spam detected: {keyword}")
            return True
    return False

# ----------------- 已移除 -----------------
# def get_sender_footer(user):
#     ...
# ----------------- 已移除 -----------------
# ----------------- 已移除 -----------------
# def smart_truncate(text, footer, max_length):
#     ...
# ----------------- 已移除 -----------------

def periodic_map_cleanup():
    while True:
        time.sleep(MAP_CLEANUP_INTERVAL) 
        
        if len(MESSAGE_MAP) > MAX_MAP_SIZE:
            MESSAGE_MAP.clear()
            logging.warning(f"MESSAGE_MAP size exceeded {MAX_MAP_SIZE}. Cleared map.")

def send_interception_feedback(user_id, reason="违规内容"):
    """发送拦截反馈消息，同时忽略用户可能已屏蔽机器人的异常。"""
    try:
        # V20.0 调整了反馈语
        bot.send_message(user_id, f"🚫 您的消息 ({reason}) 已被系统拦截。")
    except apihelper.ApiTelegramException:
        pass

# ================= 消息处理逻辑 =================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "👋 你好！直接给我发送消息，我会转发给管理员。")

@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation', 
                                    'contact', 'location', 'poll'],
                     func=lambda m: m.chat.type == 'private' and m.from_user.id != ADMIN_ID)
def handle_user_message(message):
    user = message.from_user
    
    if check_flood(user.id): 
        try:
            bot.send_message(user.id, "🛑 您的消息发送过于频繁，请稍后再试。")
        except apihelper.ApiTelegramException:
            pass
        return

    if message.content_type in ['contact', 'location', 'poll']:
        send_interception_feedback(user.id, reason=f"禁止的{message.content_type}类型")
        return

    check_content = message.text or message.caption or ""
    
    if not is_spam(check_content):
        sent_msg = None

        try:
            # 修复点 1：转发时，不添加任何 footer 或额外的文本，直接使用原始消息内容
            if message.content_type == 'text':
                # 文本消息直接转发
                sent_msg = bot.send_message(ADMIN_ID, message.text) 
            elif message.content_type == 'photo':
                # 图片消息使用原图 ID 和原字幕
                sent_msg = bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=message.caption)
            elif message.content_type == 'video':
                sent_msg = bot.send_video(ADMIN_ID, message.video.file_id, caption=message.caption)
            elif message.content_type == 'document':
                sent_msg = bot.send_document(ADMIN_ID, message.document.file_id, caption=message.caption)
            elif message.content_type == 'voice':
                sent_msg = bot.send_voice(ADMIN_ID, message.voice.file_id, caption=message.caption)
            elif message.content_type == 'animation':
                sent_msg = bot.send_animation(ADMIN_ID, message.animation.file_id, caption=message.caption)
            elif message.content_type == 'sticker':
                sent_msg = bot.send_sticker(ADMIN_ID, message.sticker.file_id)
                # 修复点 2：贴纸的映射消息也不带 footer，只保留提示
                msg_for_map = bot.send_message(ADMIN_ID, "👆 收到贴纸 (请回复本条)")
                MESSAGE_MAP[msg_for_map.message_id] = user.id
                return

            if sent_msg:
                # 将转发消息 ID 与用户 ID 绑定到映射表，用于回复
                MESSAGE_MAP[sent_msg.message_id] = user.id

        except Exception as e:
            logging.error(f"Forward failed: {e}")
            
    else:
        send_interception_feedback(user.id)
        return

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id != ADMIN_ID, content_types=None)
def handle_unknown_message(message):
    try:
        # 修复点 3：未知类型消息也不带 footer
        send_interception_feedback(user.id, reason=f"未知({message.content_type})类型")
        bot.send_message(ADMIN_ID, f"⚠️ 未知类型消息 ({message.content_type})")
    except:
        pass

@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation'],
                     func=lambda m: m.chat.id == ADMIN_ID and m.reply_to_message)
def handle_admin_reply(message):
    original_msg = message.reply_to_message
    original_msg_id = original_msg.message_id
    target_id = None 

    try:
        target_id = MESSAGE_MAP.pop(original_msg_id, None)
        
        if target_id:
            bot.copy_message(chat_id=target_id, from_chat_id=ADMIN_ID, message_id=message.message_id)
        else:
            bot.reply_to(message, "⚠️ 错误：无法在内存中找到此消息的映射用户 ID。\n可能原因：1. 消息太旧或已被清理。2. 您回复的不是原始转发消息。")

    except apihelper.ApiTelegramException as e:
        if "bot was blocked by the user" in str(e):
            bot.reply_to(message, f"🚫 回复失败：目标用户（ID: {target_id}）已屏蔽机器人。")
        else:
            bot.reply_to(message, f"❌ 发送失败 (Telegram API 错误): {e.description}")
    except Exception as e:
        bot.reply_to(message, f"❌ 发送失败 (未知错误): {e}")

if __name__ == "__main__":
    logging.info("🚀 Bot started (V20.0 Final Security Edition)...")
    
    update_thread = threading.Thread(target=update_spam_rules_thread, daemon=True)
    update_thread.start()
    
    cleanup_thread = threading.Thread(target=periodic_map_cleanup, daemon=True)
    cleanup_thread.start()
    
    try: bot.remove_webhook()
    except: pass
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
