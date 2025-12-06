import telebot
from telebot import apihelper
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
import logging
import time
import os
import re
import requests
import threading
from collections import defaultdict, OrderedDict
import random

# ================= 配置区域 (V28.0 保持不变) =================
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID_STR = os.environ.get('ADMIN_ID') or os.environ.get('OWNER_ID')
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
FLOOD_PENALTY_TIME = 60
MAX_MAP_SIZE = 1000 
MIN_NUM = 10
MAX_NUM = 99

CAPTCHA_TIMEOUT = 60
MIN_BAN_DURATION = 600
MAX_BAN_DURATION = 1800
DEFAULT_MANUAL_BAN_DURATION = 1800 # 手动禁用默认 30 分钟

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if not BOT_TOKEN or not ADMIN_ID:
    logging.error("Error: BOT_TOKEN and ADMIN_ID must be set.")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

spam_keywords = set(FALLBACK_SPAM_KEYWORDS)
user_flood_control = defaultdict(list)
user_penalty_status = {}
VERIFIED_USERS = set()
PENDING_CAPTCHA = {} 
USER_BAN_STATUS = {}

# ================= 核心定制类：FIFO 容量限制字典 (V24.0 保留) =================

class SizedOrderedDict(OrderedDict):
    def __init__(self, maxsize=1000, *args, **kwds):
        self.maxsize = maxsize
        super().__init__(*args, **kwds)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            oldest_key = next(iter(self))
            del self[oldest_key]
            logging.info(f"Capacity reached. Removed oldest map entry: {oldest_key}")

MESSAGE_MAP = SizedOrderedDict(MAX_MAP_SIZE)

# ================= 核心功能函数 (V31.0 标识符修改) =================

def get_user_identifier(user):
    user_id = user.id
    username = user.username
    
    if username:
        name_part = f"@{username}"
    else:
        first_name = user.first_name if user.first_name else ""
        last_name = user.last_name if user.last_name else ""
        name_part = f"{first_name} {last_name}".strip() if first_name or last_name else "用户"
        
    return f"\n👤 {name_part} ({user_id})"

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

def send_interception_feedback(user_id, reason="违规内容"):
    try:
        bot.send_message(user_id, f"🚫 您的消息 ({reason}) 已被系统拦截。")
    except apihelper.ApiTelegramException:
        pass

def check_ban_status(user_id):
    now = time.time()
    if user_id in USER_BAN_STATUS:
        if USER_BAN_STATUS[user_id] > now:
            return True
        else:
            del USER_BAN_STATUS[user_id]
            return False
    return False

def generate_and_send_captcha(user_id):
    if user_id in VERIFIED_USERS:
        return True
    
    now = time.time()

    if user_id in PENDING_CAPTCHA:
        _, timestamp = PENDING_CAPTCHA[user_id]
        if now - timestamp < CAPTCHA_TIMEOUT:
            return False 
        else:
            del PENDING_CAPTCHA[user_id]
            
            random_ban_time = random.randint(MIN_BAN_DURATION, MAX_BAN_DURATION)
            USER_BAN_STATUS[user_id] = now + random_ban_time
            logging.warning(f"CAPTCHA timeout for {user_id}. User banned for {random_ban_time}s.")
            
            try:
                bot.send_message(user_id, "⚠️ **验证超时！** 您已被系统暂时禁用。请稍后再试。", parse_mode="Markdown")
            except apihelper.ApiTelegramException:
                pass
            return False


    num1 = random.randint(MIN_NUM, MAX_NUM)
    num2 = random.randint(MIN_NUM, MAX_NUM)
    operator = random.choice(['+', '-'])
    
    if operator == '+':
        question = f"{num1} + {num2} = ?"
        answer = num1 + num2
    else:
        if num1 < num2:
            num1, num2 = num2, num1
        question = f"{num1} - {num2} = ?"
        answer = num1 - num2

    PENDING_CAPTCHA[user_id] = (str(answer), now)
    logging.info(f"New CAPTCHA for {user_id}: {question} -> {answer}")

    try:
        bot.send_message(user_id, f"🤖 **安全验证:** 为了证明您不是机器人，请在 **{CAPTCHA_TIMEOUT} 秒** 内回复以下算式的**数字答案**:\n\n`{question}`\n\n您无需等待或重发您的原始消息，只需直接回复答案即可。", parse_mode="Markdown")
    except apihelper.ApiTelegramException as e:
        logging.error(f"Failed to send CAPTCHA message to {user_id}: {e}")
    
    return False

# ================= 消息处理逻辑 (V32.0 新增转发反馈) =================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "👋 你好！直接给我发送消息，我会转发给管理员。")

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id in PENDING_CAPTCHA, content_types=['text'])
def handle_captcha_answer(message):
    user_id = message.from_user.id
    now = time.time()
    
    if user_id in PENDING_CAPTCHA:
        expected_answer, timestamp = PENDING_CAPTCHA[user_id]
        
        if now - timestamp > CAPTCHA_TIMEOUT:
            del PENDING_CAPTCHA[user_id]
            
            random_ban_time = random.randint(MIN_BAN_DURATION, MAX_BAN_DURATION)
            USER_BAN_STATUS[user_id] = now + random_ban_time
            
            try:
                bot.send_message(user_id, "⚠️ **验证超时！** 您已被系统暂时禁用。请稍后再试。", parse_mode="Markdown")
            except apihelper.ApiTelegramException:
                pass
            return

        user_answer = message.text.strip()
        
        if user_answer.isdigit() and expected_answer == user_answer:
            VERIFIED_USERS.add(user_id)
            del PENDING_CAPTCHA[user_id]
            logging.info(f"User {user_id} passed math CAPTCHA.")
            
            try:
                bot.send_message(user_id, "✅ **验证成功!** 您现在可以发送消息了。请重新发送您想给管理员说的话。", parse_mode="Markdown")
            except apihelper.ApiTelegramException:
                 pass
        else:
            try:
                bot.send_message(user_id, "❌ 答案错误，请重新计算！")
            except apihelper.ApiTelegramException:
                 pass
            generate_and_send_captcha(user_id)


@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation', 
                                    'contact', 'location', 'poll'],
                     func=lambda m: m.chat.type == 'private' and m.from_user.id != ADMIN_ID)
def handle_user_message(message):
    user = message.from_user
    user_id = user.id
    
    if check_ban_status(user_id):
        try:
            bot.send_message(user_id, "🚫 您当前处于禁用状态，请稍后再试。")
        except apihelper.ApiTelegramException:
            pass
        return

    if user_id in PENDING_CAPTCHA and message.content_type == 'text':
         handle_captcha_answer(message)
         return
    
    if not generate_and_send_captcha(user_id):
        return
        
    if check_flood(user_id): 
        try:
            bot.send_message(user_id, "🛑 您的消息发送过于频繁，请稍后再试。")
        except apihelper.ApiTelegramException:
            pass
        return

    if message.content_type in ['contact', 'location', 'poll']:
        send_interception_feedback(user_id, reason=f"禁止的{message.content_type}类型")
        return

    check_content = message.text or message.caption or ""
    
    if not is_spam(check_content):
        sent_msg = None
        
        identifier = get_user_identifier(user)
        caption_or_text = message.caption or message.text or ""

        try:
            if message.content_type == 'text':
                sent_msg = bot.send_message(ADMIN_ID, message.text + identifier) 
            elif message.content_type == 'photo':
                sent_msg = bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=(caption_or_text + identifier))
            elif message.content_type == 'video':
                sent_msg = bot.send_video(ADMIN_ID, message.video.file_id, caption=(caption_or_text + identifier))
            elif message.content_type == 'document':
                sent_msg = bot.send_document(ADMIN_ID, message.document.file_id, caption=(caption_or_text + identifier))
            elif message.content_type == 'voice':
                sent_msg = bot.send_voice(ADMIN_ID, message.voice.file_id, caption=(caption_or_text + identifier))
            elif message.content_type == 'animation':
                sent_msg = bot.send_animation(ADMIN_ID, message.animation.file_id, caption=(caption_or_text + identifier))
            elif message.content_type == 'sticker':
                sent_msg = bot.send_sticker(ADMIN_ID, message.sticker.file_id)
                map_text = f"💬 (回复此消息即回复用户) {identifier.replace('\n', ' ')}"
                msg_for_map = bot.send_message(ADMIN_ID, map_text)
                MESSAGE_MAP[msg_for_map.message_id] = user_id
                
                # V32.0 新增：贴纸转发成功反馈
                bot.send_message(user_id, "✅ 您的消息（贴纸）已送达管理员，请勿重复发送。")
                return

            if sent_msg:
                MESSAGE_MAP[sent_msg.message_id] = user_id
                # V32.0 新增：消息转发成功反馈
                bot.send_message(user_id, "✅ 您的消息已送达管理员，请耐心等待回复。请勿重复发送。")

        except Exception as e:
            logging.error(f"Forward failed: {e}")
            
    else:
        send_interception_feedback(user_id)
        return

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id != ADMIN_ID, content_types=None)
def handle_unknown_message(message):
    try:
        if check_ban_status(message.from_user.id) or not generate_and_send_captcha(message.from_user.id):
             return
             
        send_interception_feedback(message.from_user.id, reason=f"未知({message.content_type})类型")
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
            # V32.0 移除回复确认（用户明确不要）
        else:
            bot.reply_to(message, "⚠️ 错误：该消息的用户 ID 映射已失效（可能原因：已回复过一次或消息太旧被淘汰）。")

    except apihelper.ApiTelegramException as e:
        if "bot was blocked by the user" in str(e):
            bot.reply_to(message, f"🚫 回复失败：目标用户（ID: {target_id}）已屏蔽机器人。")
        else:
            bot.reply_to(message, f"❌ 发送失败 (Telegram API 错误): {e.description}")
    except Exception as e:
        bot.reply_to(message, f"❌ 发送失败 (未知错误): {e}")

# ================= V32.0 新增：管理员手动控制命令 =================

@bot.message_handler(commands=['ban', 'unban', 'check'], func=lambda m: m.chat.id == ADMIN_ID and m.reply_to_message)
def handle_admin_commands(message):
    admin_id = message.from_user.id
    command = message.text.split()[0].lower()
    
    # 1. 权限检查：确保是管理员本人
    if admin_id != ADMIN_ID:
        return

    # 2. 获取目标用户 ID
    original_msg = message.reply_to_message
    target_id = MESSAGE_MAP.get(original_msg.message_id)
    
    if not target_id:
        bot.reply_to(message, "⚠️ 错误：无法从回复的消息中找到目标用户 ID，请确保您回复的是用户转发的最新消息。")
        return

    # 3. 处理 /ban 命令
    if command.startswith('/ban'):
        duration = DEFAULT_MANUAL_BAN_DURATION
        
        # 尝试从命令中解析禁用时间
        parts = message.text.split()
        if len(parts) > 1 and parts[1].isdigit():
            duration = int(parts[1])
            if duration <= 0:
                bot.reply_to(message, "🚫 禁用时间必须大于 0 秒。")
                return

        ban_until = time.time() + duration
        USER_BAN_STATUS[target_id] = ban_until
        
        duration_str = f"{duration} 秒"
        if duration >= 3600:
            duration_str = f"{duration / 3600:.2f} 小时"
        elif duration >= 60:
            duration_str = f"{duration / 60:.2f} 分钟"
            
        bot.reply_to(message, f"✅ 已成功禁用用户 ID: {target_id}，禁用时长为 {duration_str}。")
        logging.warning(f"Admin {admin_id} manually banned user {target_id} for {duration}s.")
        
        try:
            bot.send_message(target_id, f"🚫 您已被管理员手动禁用，禁用到期时间为 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ban_until))}。")
        except apihelper.ApiTelegramException:
            pass
            
    # 4. 处理 /unban 命令
    elif command.startswith('/unban'):
        if target_id in USER_BAN_STATUS:
            del USER_BAN_STATUS[target_id]
            bot.reply_to(message, f"✅ 已成功解除对用户 ID: {target_id} 的禁用。")
            logging.info(f"Admin {admin_id} manually unbanned user {target_id}.")
            try:
                bot.send_message(target_id, "✅ 您已被管理员解除禁用，现在可以发送消息了。")
            except apihelper.ApiTelegramException:
                pass
        else:
            bot.reply_to(message, f"ℹ️ 用户 ID: {target_id} 当前并未被禁用。")

    # 5. 处理 /check 命令
    elif command.startswith('/check'):
        if target_id in USER_BAN_STATUS:
            remaining_time = USER_BAN_STATUS[target_id] - time.time()
            if remaining_time > 0:
                duration_str = f"{remaining_time:.2f} 秒"
                if remaining_time >= 3600:
                    duration_str = f"{remaining_time / 3600:.2f} 小时"
                elif remaining_time >= 60:
                    duration_str = f"{remaining_time / 60:.2f} 分钟"
                
                bot.reply_to(message, f"❌ 用户 ID: {target_id} 当前处于禁用状态，剩余时间约 {duration_str}。")
            else:
                del USER_BAN_STATUS[target_id]
                bot.reply_to(message, f"✅ 用户 ID: {target_id} 当前未被禁用。")
        else:
            bot.reply_to(message, f"✅ 用户 ID: {target_id} 当前未被禁用。")

# ================= 启动逻辑 =================

if __name__ == "__main__":
    logging.info("🚀 Bot started (V32.0 Admin Control & Feedback Edition)...")
    
    update_thread = threading.Thread(target=update_spam_rules_thread, daemon=True)
    update_thread.start()
    
    try: bot.remove_webhook()
    except: pass
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
