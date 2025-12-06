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

# 修复点 3.1：内存映射的最大限制（防止内存耗尽）
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

# ================= 核心功能函数 =================

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

def get_sender_footer(user):
    first = user.first_name if user.first_name else "User"
    safe_first = re.sub(r'[^\w\s]', '', first)
    return f"\n[ 用户: {safe_first} | ID: {user.id} ]"

def smart_truncate(text, footer, max_length):
    if not text: return footer
    available_len = max_length - len(footer) - 10
    if len(text) > available_len:
        return text[:available_len] + "..." + footer
    return text + footer

# 修复点 1：基于大小的内存清理
def periodic_map_cleanup():
    while True:
        # 每隔一段时间检查一次，而不是每次都检查
        time.sleep(MAP_CLEANUP_INTERVAL) 
        
        # 只有在超过最大限制时才清理
        if len(MESSAGE_MAP) > MAX_MAP_SIZE:
            MESSAGE_MAP.clear()
            logging.warning(f"MESSAGE_MAP size exceeded {MAX_MAP_SIZE}. Cleared map.")

def send_interception_feedback(user_id, reason="违规内容"):
    """发送拦截反馈消息，同时忽略用户可能已屏蔽机器人的异常。"""
    try:
        bot.send_message(user_id, f"🚫 您的消息包含{reason}，已自动拦截。")
    except apihelper.ApiTelegramException:
        pass

# ================= 消息处理逻辑 =================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "👋 你好！直接给我发送消息，我会转发给管理员。")

@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation', 
                                    'contact', 'location', 'poll'], # 修复点 2：添加敏感信息类型
                     func=lambda m: m.chat.type == 'private' and m.from_user.id != ADMIN_ID)
def handle_user_message(message):
    user = message.from_user
    
    if check_flood(user.id): 
        try:
            bot.send_message(user.id, "🛑 您的消息发送过于频繁，请稍后再试。")
        except apihelper.ApiTelegramException:
            pass
        return

    # 修复点 2.1：明确拦截敏感信息类型
    if message.content_type in ['contact', 'location', 'poll']:
        send_interception_feedback(user.id, reason=f"禁止的{message.content_type}类型")
        return

    check_content = message.text or message.caption or ""
    
    if not is_spam(check_content):
        footer = get_sender_footer(user)
        sent_msg = None

        try:
            # 转发逻辑与V18.0保持一致
            if message.content_type == 'text':
                final_text = smart_truncate(message.text, footer, 4096)
                sent_msg = bot.send_message(ADMIN_ID, final_text)
            elif message.content_type == 'photo':
                photo_id = message.photo[-1].file_id
                caption = smart_truncate(message.caption, footer, 1024)
                sent_msg = bot.send_photo(ADMIN_ID, photo_id, caption=caption)
            elif message.content_type == 'video':
                caption = smart_truncate(message.caption, footer, 1024)
                sent_msg = bot.send_video(ADMIN_ID, message.video.file_id, caption=caption)
            elif message.content_type == 'document':
                caption = smart_truncate(message.caption, footer, 1024)
                sent_msg = bot.send_document(ADMIN_ID, message.document.file_id, caption=caption)
            elif message.content_type == 'voice':
                caption = smart_truncate(message.caption, footer, 1024)
                sent_msg = bot.send_voice(ADMIN_ID, message.voice.file_id, caption=caption)
            elif message.content_type == 'animation':
                caption = smart_truncate(message.caption, footer, 1024)
                sent_msg = bot.send_animation(ADMIN_ID, message.animation.file_id, caption=caption)
            elif message.content_type == 'sticker':
                sent_msg = bot.send_sticker(ADMIN_ID, message.sticker.file_id)
                msg_for_map = bot.send_message(ADMIN_ID, f"👆 收到贴纸 (请回复本条){footer}")
                MESSAGE_MAP[msg_for_map.message_id] = user.id
                return

            if sent_msg:
                MESSAGE_MAP[sent_msg.message_id] = user.id

        except Exception as e:
            logging.error(f"Forward failed: {e}")
            
    else:
        # 内容不安全，发送违规反馈并返回
        send_interception_feedback(user.id)
        return

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id != ADMIN_ID, content_types=None)
def handle_unknown_message(message):
    try:
        user = message.from_user
        footer = get_sender_footer(user)
        # 修复点 2.2：未知类型也明确告知用户，并发送到管理员作为警告
        send_interception_feedback(user.id, reason=f"未知({message.content_type})类型")
        bot.send_message(ADMIN_ID, f"⚠️ 未知类型消息 ({message.content_type}){footer}")
    except:
        pass

@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation'],
                     func=lambda m: m.chat.id == ADMIN_ID and m.reply_to_message)
def handle_admin_reply(message):
    original_msg = message.reply_to_message
    original_msg_id = original_msg.message_id
    target_id = None 

    try:
        # 从内存映射中查找目标ID，并立即移除
        target_id = MESSAGE_MAP.pop(original_msg_id, None)
        
        if target_id:
            bot.copy_message(chat_id=target_id, from_chat_id=ADMIN_ID, message_id=message.message_id)
        else:
            bot.reply_to(message, "⚠️ 错误：无法在内存中找到此消息的映射用户 ID。\n可能原因：1. 消息太旧或已被清理。2. 您回复的不是原始转发消息。")

    except apihelper.ApiTelegramException as e:
        if "bot was blocked by the user" in str(e):
            bot.reply_to(message, f"🚫 回复失败：目标用户（ID: {target_id}）已屏蔽机器人。")
        else:
            # 报告其他 API 错误，但不对管理员暴露内部变量
            bot.reply_to(message, f"❌ 发送失败 (Telegram API 错误): {e.description}")
    except Exception as e:
        # 捕获其他非Telegram API异常
        bot.reply_to(message, f"❌ 发送失败 (未知错误): {e}")

if __name__ == "__main__":
    logging.info("🚀 Bot started (V19.0 Final Security Edition)...")
    
    update_thread = threading.Thread(target=update_spam_rules_thread, daemon=True)
    update_thread.start()
    
    # 启动内存清理线程
    cleanup_thread = threading.Thread(target=periodic_map_cleanup, daemon=True)
    cleanup_thread.start()
    
    try: bot.remove_webhook()
    except: pass
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
