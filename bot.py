import telebot
import logging
import time
import os
import re
import requests
from telebot import apihelper

# ================= 配置区域 =================
# 1. 从环境变量获取 Token (最安全)
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# 2. 管理员 ID (必须填对，否则只有你能用)
ADMIN_ID = int(os.environ.get('ADMIN_ID', '你的管理员ID'))

# 3. 垃圾广告关键词 (本地基础库)
FALLBACK_SPAM_KEYWORDS = [
    "u币", "USDT", "泰达币", "跑分", "博彩", "兼职", "刷单", "各行各业", "代开", 
    "发票", "迷药", "枪支", "色情", "裸聊", "办证", "查询", "定位", "监听"
]

# 4. 在线规则地址 (自动切换：Zeabur 变量优先 -> 否则用 GitHub)
DEFAULT_REMOTE_SPAM_URL = "https://raw.githubusercontent.com/F720/Spam_Keywords/main/Spam_Keywords.txt"
REMOTE_SPAM_URL = os.environ.get('REMOTE_SPAM_URL', DEFAULT_REMOTE_SPAM_URL)

# ===========================================

# 初始化日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 检查 Token
if not BOT_TOKEN:
    logging.error("❌ 错误: 未检测到 BOT_TOKEN，请在 Zeabur 环境变量中设置！")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

# 内存中的垃圾词库
spam_keywords = set(FALLBACK_SPAM_KEYWORDS)
last_update_time = 0

# ----------------- 核心功能函数 -----------------

def update_spam_rules():
    """从 GitHub 或指定链接更新垃圾词库"""
    global spam_keywords, last_update_time
    # 每小时更新一次
    if time.time() - last_update_time < 3600:
        return

    try:
        logging.info(f"🔄 正在从 {REMOTE_SPAM_URL} 更新词库...")
        response = requests.get(REMOTE_SPAM_URL, timeout=10)
        if response.status_code == 200:
            remote_words = set(line.strip() for line in response.text.splitlines() if line.strip())
            
            # 合并：远程词库 + 本地词库 + Zeabur 自定义变量
            custom_spam = os.environ.get('CUSTOM_SPAM_KEYWORDS', '')
            custom_words = set(w.strip() for w in custom_spam.split(',') if w.strip())
            
            spam_keywords = set(FALLBACK_SPAM_KEYWORDS) | remote_words | custom_words
            last_update_time = time.time()
            logging.info(f"✅ 词库更新成功，当前共 {len(spam_keywords)} 条规则")
        else:
            logging.warning(f"⚠️ 更新失败，状态码: {response.status_code}")
    except Exception as e:
        logging.error(f"❌ 更新词库出错: {e}")

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
    """净化名字，防止特殊字符炸群，无名字时显示 Unnamed"""
    first = user.first_name if user.first_name else ""
    last = user.last_name if user.last_name else ""
    full_name = f"{first} {last}".strip()
    
    if not full_name:
        return "Unnamed"
    
    # 移除可能破坏显示的特殊符号
    return re.sub(r'[^\w\s\u4e00-\u9fff]', '', full_name)

# ----------------- 消息处理逻辑 -----------------

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """欢迎语"""
    bot.reply_to(message, "👋 您好！我是私聊机器人。\n直接发送消息即可，我会转发给管理员。")

@bot.message_handler(func=lambda message: message.chat.type == 'private' and message.from_user.id != ADMIN_ID)
def handle_private_message(message):
    """处理用户发来的私聊"""
    user = message.from_user
    user_id = user.id
    
    # 1. 垃圾检测
    if message.text and is_spam(message.text):
        return

    # 2. 名字净化
    safe_name = clean_user_name(user)
    
    # 3. 构建只有管理员能看见的各种信息
    # 格式重点：ID单独一行，方便正则提取
    info_text = (
        f"📩 **新消息**\n"
        f"👤 来自: {safe_name}\n"
        f"🆔 ID: {user_id}\n" # 关键修改：ID 独立成行，且必须是纯数字
        f"------------------"
    )

    try:
        # 发送提示头
        sent_header = bot.send_message(ADMIN_ID, info_text, parse_mode='Markdown')
        
        # 复制用户消息内容（使用 copy_message 保护隐私）
        bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )
        
        logging.info(f"✅ 已转发用户 {user_id} 的消息")
        
    except Exception as e:
        logging.error(f"❌ 转发失败: {e}")

@bot.message_handler(func=lambda message: message.chat.id == ADMIN_ID and message.reply_to_message)
def handle_reply(message):
    """管理员回复用户"""
    try:
        # 获取管理员回复的那条原始消息（就是机器人的提示头）
        original_message = message.reply_to_message
        
        # 1. 尝试从文本中提取 ID
        # 逻辑：寻找 "ID: " 后面跟着的一串数字
        target_id = None
        
        if original_message.text:
            match = re.search(r"ID:\s*(\d+)", original_message.text)
            if match:
                target_id = int(match.group(1))
        
        if not target_id:
            bot.reply_to(message, "❌ 无法找到用户 ID，请确认您回复的是带有 '🆔 ID:' 的消息头。")
            return

        # 2. 发送回复给用户
        # 使用 copy_message 避免暴露管理员 ID
        bot.copy_message(
            chat_id=target_id,
            from_chat_id=ADMIN_ID,
            message_id=message.message_id
        )
        
        bot.reply_to(message, "✅ 回复成功！")
        logging.info(f"✅ 管理员回复了用户 {target_id}")

    except Exception as e:
        logging.error(f"❌ 回复失败: {e}")
        bot.reply_to(message, f"❌ 发送失败: {e}")

# ----------------- 启动程序 -----------------
if __name__ == "__main__":
    logging.info("🚀 机器人 V15.4 (ID 修复版) 已启动...")
    # 移除 Webhook 保证 Polling 正常
    try:
        bot.remove_webhook()
    except:
        pass
    
    # 无限重连模式
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
