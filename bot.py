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

# 2. 管理员 ID (必须填对)
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

# 初始化日志
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
    """更新垃圾词库"""
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
    """防炸群检测"""
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
    """垃圾广告检测"""
    if not text: return False
    update_spam_rules()
    for keyword in spam_keywords:
        if keyword.lower() in text.lower():
            logging.info(f"🗑️ 拦截垃圾: {keyword}")
            return True
    return False

def get_sender_footer(user):
    """生成 ID 小尾巴"""
    first = user.first_name if user.first_name else "用户"
    return f"\n\n----------------\n👤 {first} | 🆔 ID: {user.id}"

# ----------------- 消息处理逻辑 -----------------

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "👋 您好！请直接发送消息，我会转发给管理员。")

# 接收所有类型的消息 (文字、图片、视频、语音、文档、贴纸)
@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker'], 
                     func=lambda m: m.chat.type == 'private' and m.from_user.id != ADMIN_ID)
def handle_user_message(message):
    user = message.from_user
    
    # 1. 防炸群
    if check_flood(user.id): return

    # 2. 垃圾检测 (只检测文字和说明文字)
    check_content = message.text or message.caption or ""
    if is_spam(check_content):
        return

    # 3. 构建包含 ID 的小尾巴
    footer = get_sender_footer(user)

    try:
        # === 分类处理，实现“一条消息” ===
        
        # A. 纯文字
        if message.content_type == 'text':
            # 直接把 ID 拼接到文字后面
            bot.send_message(ADMIN_ID, message.text + footer)

        # B. 图片 (Photo)
        elif message.content_type == 'photo':
            # 获取最高清的一张图
            photo_id = message.photo[-1].file_id
            caption = (message.caption or "") + footer
            bot.send_photo(ADMIN_ID, photo_id, caption=caption)

        # C. 视频 (Video)
        elif message.content_type == 'video':
            caption = (message.caption or "") + footer
            bot.send_video(ADMIN_ID, message.video.file_id, caption=caption)

        # D. 文件/文档 (Document)
        elif message.content_type == 'document':
            caption = (message.caption or "") + footer
            bot.send_document(ADMIN_ID, message.document.file_id, caption=caption)
            
        # E. 语音 (Voice)
        elif message.content_type == 'voice':
            caption = (message.caption or "") + footer
            bot.send_voice(ADMIN_ID, message.voice.file_id, caption=caption)

        # F. 贴纸/表情包 (Sticker) - 特殊情况
        # Telegram 禁止给贴纸加文字说明，所以必须分两条发
        elif message.content_type == 'sticker':
            bot.send_sticker(ADMIN_ID, message.sticker.file_id)
            # 紧跟一条带有 ID 的小提示，方便你回复
            bot.send_message(ADMIN_ID, f"👆 收到一个表情包\n{footer}")

    except Exception as e:
        logging.error(f"❌ 转发消息失败: {e}")

# ----------------- 管理员回复逻辑 -----------------

@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.reply_to_message)
def handle_admin_reply(message):
    """管理员回复用户的消息"""
    try:
        original_msg = message.reply_to_message
        
        # 1. 尝试从【文字内容】或【图片/视频说明】中提取 ID
        # 我们要找的内容是： "🆔 ID: 12345678"
        content_to_search = original_msg.text or original_msg.caption or ""
        
        match = re.search(r"ID:\s*(\d+)", content_to_search)
        
        if match:
            target_id = int(match.group(1))
            # 复制管理员的消息给用户
            bot.copy_message(chat_id=target_id, from_chat_id=ADMIN_ID, message_id=message.message_id)
            bot.reply_to(message, "✅ 已回复")
        else:
            bot.reply_to(message, "⚠️ 无法回复：找不到用户 ID。\n请确保你回复的是带有 '🆔 ID: xxx' 的那条消息。")

    except Exception as e:
        bot.reply_to(message, f"❌ 发送失败: {e}")

if __name__ == "__main__":
    logging.info("🚀 机器人已启动 (V16.0 单条消息合并版)...")
    try: bot.remove_webhook()
    except: pass
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
