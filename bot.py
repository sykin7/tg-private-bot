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

# 3. 垃圾广告关键词 (本地基础库 - 就算断网也能拦)
FALLBACK_SPAM_KEYWORDS = [
    "u币", "USDT", "泰达币", "跑分", "博彩", "兼职", "刷单", "各行各业", "代开", 
    "发票", "迷药", "枪支", "色情", "裸聊", "办证", "查询", "定位", "监听",
    "傻逼", "出u", "收u", "高价收"
]

# 4. 在线规则地址 (自动切换：Zeabur 变量优先 -> 否则用 GitHub)
DEFAULT_REMOTE_SPAM_URL = "https://raw.githubusercontent.com/sykin7/my-telegram-spam-rules/refs/heads/main/spam.txt"
REMOTE_SPAM_URL = os.environ.get('REMOTE_SPAM_URL', DEFAULT_REMOTE_SPAM_URL)

# 5. 防炸群设置 (10秒内最多发5条)
FLOOD_WINDOW = 10
MAX_MSGS_PER_WINDOW = 5

# ===========================================

# 初始化日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 检查 Token
if not BOT_TOKEN:
    logging.error("❌ 错误: 未检测到 BOT_TOKEN，请在 Zeabur 环境变量中设置！")
    exit(1)
if not ADMIN_ID:
    logging.error("❌ 错误: 未检测到 ADMIN_ID，请在 Zeabur 环境变量中设置！")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

# 全局变量
spam_keywords = set(FALLBACK_SPAM_KEYWORDS)
last_update_time = 0
user_flood_control = defaultdict(list) # 记录用户发消息时间

# ----------------- 核心防御函数 -----------------

def update_spam_rules():
    """从 GitHub 或指定链接更新垃圾词库"""
    global spam_keywords, last_update_time
    # 每小时更新一次
    if time.time() - last_update_time < 3600:
        return

    try:
        # logging.info(f"🔄 正在更新词库...")
        response = requests.get(REMOTE_SPAM_URL, timeout=10)
        if response.status_code == 200:
            remote_words = set(line.strip() for line in response.text.splitlines() if line.strip())
            
            # 合并：远程词库 + 本地词库 + Zeabur 自定义变量
            custom_spam = os.environ.get('CUSTOM_SPAM_KEYWORDS', '')
            custom_words = set(w.strip() for w in custom_spam.split(',') if w.strip())
            
            # 强制包含本地高危词
            spam_keywords = set(FALLBACK_SPAM_KEYWORDS) | remote_words | custom_words
            last_update_time = time.time()
            logging.info(f"✅ 词库更新成功，当前共 {len(spam_keywords)} 条规则")
        else:
            logging.warning(f"⚠️ 更新失败，状态码: {response.status_code}")
    except Exception as e:
        # 失败时保持原有词库，不报错
        logging.error(f"❌ 更新词库出错 (使用本地兜底): {e}")

def check_flood(user_id):
    """防炸群检测：如果发送太快返回 True"""
    now = time.time()
    timestamps = user_flood_control[user_id]
    
    # 过滤掉超过窗口期的时间戳
    valid_timestamps = [t for t in timestamps if now - t < FLOOD_WINDOW]
    
    if len(valid_timestamps) >= MAX_MSGS_PER_WINDOW:
        # 触发熔断，更新时间戳并拒绝
        user_flood_control[user_id] = valid_timestamps
        return True
    else:
        # 通过，记录当前时间
        valid_timestamps.append(now)
        user_flood_control[user_id] = valid_timestamps
        return False

def is_spam(text):
    """检查是否包含垃圾词"""
    if not text:
        return False
    update_spam_rules() # 检查前尝试更新
    for keyword in spam_keywords:
        if keyword.lower() in text.lower():
            logging.info(f"🗑️ 拦截垃圾广告: {keyword}")
            return True
    return False

def clean_user_name(user):
    """净化名字"""
    first = user.first_name if user.first_name else ""
    last = user.last_name if user.last_name else ""
    full_name = f"{first} {last}".strip()
    if not full_name: return "Unnamed"
    return re.sub(r'[^\w\s\u4e00-\u9fff]', '', full_name)

# ----------------- 消息处理逻辑 -----------------

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """欢迎语"""
    bot.reply_to(message, "👋 您好！请直接发送消息，我会转发给管理员。")

@bot.message_handler(func=lambda message: message.chat.type == 'private' and message.from_user.id != ADMIN_ID)
def handle_private_message(message):
    """处理用户发来的私聊"""
    user = message.from_user
    user_id = user.id
    
    # 1. 防炸群检测 (新增回归)
    if check_flood(user_id):
        # 可以在这里回一句 "发太快了"，但为了防骚扰通常选择静默
        return

    # 2. 垃圾广告检测
    if message.text and is_spam(message.text):
        try: bot.reply_to(message, "🚫 Message blocked (Spam detected).")
        except: pass
        return

    # 3. 准备转发
    safe_name = clean_user_name(user)
    
    # 构建信息头（关键：ID必须清晰可见）
    info_text = (
        f"📩 **新消息**\n"
        f"👤 来自: {safe_name}\n"
        f"🆔 ID: {user_id}\n"
        f"------------------"
    )

    try:
        # 发送提示头
        bot.send_message(ADMIN_ID, info_text, parse_mode='Markdown')
        
        # 复制内容
        bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )
        
    except Exception as e:
        logging.error(f"❌ 转发失败: {e}")

@bot.message_handler(func=lambda message: message.chat.id == ADMIN_ID and message.reply_to_message)
def handle_reply(message):
    """管理员回复逻辑"""
    try:
        original_message = message.reply_to_message
        
        # 提取目标 ID
        target_id = None
        if original_message.text:
            # 正则寻找 "ID: 12345"
            match = re.search(r"ID:\s*(\d+)", original_message.text)
            if match:
                target_id = int(match.group(1))
        
        if not target_id:
            bot.reply_to(message, "⚠️ 无法获取用户 ID。\n请务必回复带有 '🆔 ID: xxx' 的那条消息头！")
            return

        # 发送给用户
        bot.copy_message(
            chat_id=target_id,
            from_chat_id=ADMIN_ID,
            message_id=message.message_id
        )
        bot.reply_to(message, "✅ 已回复")

    except Exception as e:
        bot.reply_to(message, f"❌ 发送失败: {e}")

# ----------------- 启动程序 -----------------
if __name__ == "__main__":
    logging.info("🚀 机器人 V15.5 (防御+回复完全体) 已启动...")
    try:
        bot.remove_webhook()
    except:
        pass
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
