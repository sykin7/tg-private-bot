import telebot
import logging
import time
import os
import re
import requests
from collections import defaultdict

# ================= 配置区域 =================
# 1. 从环境变量获取 Token
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# 2. 管理员 ID
ADMIN_ID_STR = os.environ.get('ADMIN_ID')
ADMIN_ID = int(ADMIN_ID_STR) if ADMIN_ID_STR else None

# 3. 垃圾广告关键词
FALLBACK_SPAM_KEYWORDS = [
    "u币", "USDT", "泰达币", "跑分", "博彩", "兼职", "刷单", "各行各业", "代开", 
    "发票", "迷药", "枪支", "色情", "裸聊", "办证", "查询", "定位", "监听",
    "傻逼", "出u", "收u", "高价收"
]

# 4. 在线规则地址
DEFAULT_REMOTE_SPAM_URL = "https://raw.githubusercontent.com/sykin7/my-telegram-spam-rules/refs/heads/main/spam.txt"
REMOTE_SPAM_URL = os.environ.get('REMOTE_SPAM_URL', DEFAULT_REMOTE_SPAM_URL)

# 5. 防炸群设置
FLOOD_WINDOW = 10
MAX_MSGS_PER_WINDOW = 5

# ===========================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if not BOT_TOKEN or not ADMIN_ID:
    logging.error("❌ 错误: 请在 Zeabur 环境变量中设置 BOT_TOKEN 和 ADMIN_ID")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

# 全局变量
spam_keywords = set(FALLBACK_SPAM_KEYWORDS)
last_update_time = 0
user_flood_control = defaultdict(list)

# ----------------- 辅助工具函数 -----------------

def update_spam_rules():
    global spam_keywords, last_update_time
    if time.time() - last_update_time < 3600: return
    try:
        response = requests.get(REMOTE_SPAM_URL, timeout=10)
        if response.status_code == 200:
            remote_words = set(line.strip() for line in response.text.splitlines() if line.strip())
            custom_spam = os.environ.get('CUSTOM_SPAM_KEYWORDS', '')
            custom_words = set(w.strip() for w in custom_spam.split(',') if w.strip())
            spam_keywords = set(FALLBACK_SPAM_KEYWORDS) | remote_words | custom_words
            last_update_time = time.time()
            logging.info(f"✅ 词库更新成功，当前共 {len(spam_keywords)} 条规则")
    except Exception as e:
        logging.error(f"❌ 更新词库出错: {e}")

def check_flood(user_id):
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
    update_spam_rules()
    for keyword in spam_keywords:
        if keyword.lower() in text.lower():
            logging.info(f"🗑️ 拦截垃圾: {keyword}")
            return True
    return False

def get_sender_footer(user):
    first = user.first_name if user.first_name else "用户"
    return f"\n\n----------------\n👤 {first} | 🆔 ID: {user.id}"

# ----------------- 消息处理逻辑 (用户发给你的) -----------------

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "👋 您好！请直接发送消息，我会转发给管理员。")

@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker'], 
                     func=lambda m: m.chat.type == 'private' and m.from_user.id != ADMIN_ID)
def handle_user_message(message):
    user = message.from_user
    if check_flood(user.id): return
    
    check_content = message.text or message.caption or ""
    if is_spam(check_content): return

    footer = get_sender_footer(user)

    try:
        if message.content_type == 'text':
            bot.send_message(ADMIN_ID, message.text + footer)
        elif message.content_type == 'photo':
            photo_id = message.photo[-1].file_id
            caption = (message.caption or "") + footer
            bot.send_photo(ADMIN_ID, photo_id, caption=caption)
        elif message.content_type == 'video':
            caption = (message.caption or "") + footer
            bot.send_video(ADMIN_ID, message.video.file_id, caption=caption)
        elif message.content_type == 'document':
            caption = (message.caption or "") + footer
            bot.send_document(ADMIN_ID, message.document.file_id, caption=caption)
        elif message.content_type == 'voice':
            caption = (message.caption or "") + footer
            bot.send_voice(ADMIN_ID, message.voice.file_id, caption=caption)
        elif message.content_type == 'sticker':
            bot.send_sticker(ADMIN_ID, message.sticker.file_id)
            bot.send_message(ADMIN_ID, f"👆 收到一个表情包\n{footer}")
    except Exception as e:
        logging.error(f"❌ 转发消息失败: {e}")

# ----------------- 管理员回复逻辑 (你发给用户的) -----------------

# 🔥 修复点在这里：增加了 content_types 参数，让你能回复表情、图片、视频、语音等所有类型
@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker'],
                     func=lambda m: m.chat.id == ADMIN_ID and m.reply_to_message)
def handle_admin_reply(message):
    """管理员回复用户的消息"""
    try:
        original_msg = message.reply_to_message
        
        # 提取目标 ID
        content_to_search = original_msg.text or original_msg.caption or ""
        match = re.search(r"ID:\s*(\d+)", content_to_search)
        
        if match:
            target_id = int(match.group(1))
            # 这里的 copy_message 会自动处理所有类型（包括贴纸、图片、文字）
            bot.copy_message(chat_id=target_id, from_chat_id=ADMIN_ID, message_id=message.message_id)
            
            # 为了不打扰你，回复表情包时不弹“已回复”的文字提示，只在日志里记一下
            # 如果是文字回复，可以在这里加个 feedback
            if message.content_type == 'text':
                pass # 你发文字时，界面上会有 sending 状态，就不多发消息打扰你了
            
        else:
            bot.reply_to(message, "⚠️ 无法回复：找不到用户 ID。\n请确保你回复的是带有 '🆔 ID: xxx' 的那条消息。")

    except Exception as e:
        bot.reply_to(message, f"❌ 发送失败: {e}")

if __name__ == "__main__":
    logging.info("🚀 机器人已启动 (V16.1 修复管理员回复贴纸问题)...")
    try: bot.remove_webhook()
    except: pass
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
