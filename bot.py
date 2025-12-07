import telebot
from telebot import apihelper
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
import logging
import time
import os
import re
import requests
import threading
from collections import deque
import random
import sqlite3
import unicodedata


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


DB_PATH = os.environ.get('BOT_DB_PATH', '/app/data/bot_core.db')

FLOOD_WINDOW = 10
MAX_MSGS_PER_WINDOW = 5
FLOOD_PENALTY_TIME = 60

CAPTCHA_TIMEOUT = 120
MIN_BAN_DURATION = 600
MAX_BAN_DURATION = 3600
CAPTCHA_MAX_RETRIES = 3

SPAM_UPDATE_INTERVAL = 3600
REMOTE_MAX_CONTENT_BYTES = 128 * 1024

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if not BOT_TOKEN or not ADMIN_ID:
    logging.error("Error: BOT_TOKEN and ADMIN_ID must be set.")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

_db_lock = threading.Lock()
_spam_lock = threading.Lock()
_flood_lock = threading.Lock()

user_flood_control = {}
spam_regex_pattern = None
_db_conn = None

CN_NUM_MAP = {
    '0': '零', '1': '壹', '2': '贰', '3': '叁', '4': '肆', 
    '5': '伍', '6': '陆', '7': '柒', '8': '捌', '9': '玖',
    '10': '拾'
}

def get_db_conn():
    global _db_conn
    if _db_conn is None:

        try:
            db_dir = os.path.dirname(DB_PATH)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
                logging.info(f"Created database directory: {db_dir}")
        except Exception as e:
            logging.error(f"Failed to create DB directory: {e}")

        _db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _db_conn.execute("PRAGMA journal_mode=WAL")
        _db_conn.execute("PRAGMA synchronous=NORMAL")
    return _db_conn

def init_db():
    with _db_lock:
        conn = get_db_conn()
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        verified INTEGER DEFAULT 0,
                        ban_until REAL DEFAULT 0
                    )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS pending_captcha (
                        user_id INTEGER PRIMARY KEY,
                        answer TEXT,
                        timestamp REAL,
                        retries INTEGER
                    )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS message_map (
                        msg_id INTEGER PRIMARY KEY,
                        user_id INTEGER,
                        created_at REAL
                    )''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_map_created ON message_map(created_at)''')
        conn.commit()

def db_check_and_verify(user_id, input_ans):
    now = time.time()
    with _db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        
        cur.execute("SELECT verified, ban_until FROM users WHERE user_id=?", (user_id,))
        user_row = cur.fetchone()
        if user_row and user_row[1] > now:
            return 'banned', user_row[1]
        if user_row and user_row[0] == 1:
            return 'verified', 0

        cur.execute("SELECT answer, timestamp, retries FROM pending_captcha WHERE user_id=?", (user_id,))
        cap_row = cur.fetchone()
        
        if not cap_row:
            return 'no_captcha', 0
            
        expected, ts, retries = cap_row
        
        if now - ts > CAPTCHA_TIMEOUT:
            ban_until = now + random.randint(MIN_BAN_DURATION, MAX_BAN_DURATION)
            cur.execute("INSERT OR REPLACE INTO users (user_id, verified, ban_until) VALUES (?, 0, ?)", (user_id, ban_until))
            cur.execute("DELETE FROM pending_captcha WHERE user_id=?", (user_id,))
            conn.commit()
            return 'timeout_ban', ban_until
            
        if input_ans == expected:
            cur.execute("INSERT OR REPLACE INTO users (user_id, verified, ban_until) VALUES (?, 1, 0)", (user_id,))
            cur.execute("DELETE FROM pending_captcha WHERE user_id=?", (user_id,))
            conn.commit()
            return 'success', 0
        else:
            new_retries = retries + 1
            if new_retries >= CAPTCHA_MAX_RETRIES:
                ban_until = now + random.randint(MIN_BAN_DURATION, MAX_BAN_DURATION)
                cur.execute("INSERT OR REPLACE INTO users (user_id, verified, ban_until) VALUES (?, 0, ?)", (user_id, ban_until))
                cur.execute("DELETE FROM pending_captcha WHERE user_id=?", (user_id,))
                conn.commit()
                return 'fail_ban', ban_until
            else:
                cur.execute("UPDATE pending_captcha SET retries=? WHERE user_id=?", (new_retries, user_id))
                conn.commit()
                return 'wrong_answer', 0

def db_get_user_status(user_id):
    with _db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT verified, ban_until FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return row if row else (0, 0)

def db_ban_user(user_id, duration):
    ban_until = time.time() + duration
    with _db_lock:
        conn = get_db_conn()
        conn.execute("INSERT OR REPLACE INTO users (user_id, verified, ban_until) VALUES (?, 0, ?)", (user_id, ban_until))
        conn.execute("DELETE FROM pending_captcha WHERE user_id=?", (user_id,))
        conn.commit()
    return ban_until

def db_unban_user(user_id):
    with _db_lock:
        conn = get_db_conn()
        conn.execute("UPDATE users SET ban_until=0 WHERE user_id=?", (user_id,))
        conn.commit()

def db_save_captcha(user_id, answer):
    with _db_lock:
        conn = get_db_conn()
        conn.execute("INSERT OR REPLACE INTO pending_captcha (user_id, answer, timestamp, retries) VALUES (?, ?, ?, 0)", 
                  (user_id, answer, time.time()))
        conn.commit()

def db_save_map(msg_id, user_id):
    with _db_lock:
        conn = get_db_conn()
        conn.execute("INSERT OR REPLACE INTO message_map (msg_id, user_id, created_at) VALUES (?, ?, ?)", 
                  (msg_id, user_id, time.time()))
        conn.commit()

def db_get_map(msg_id):
    with _db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM message_map WHERE msg_id=?", (msg_id,))
        row = cur.fetchone()
        return row[0] if row else None

def db_cleanup_map():
    limit_time = time.time() - (86400 * 7)
    with _db_lock:
        conn = get_db_conn()
        conn.execute("DELETE FROM message_map WHERE created_at < ?", (limit_time,))
        conn.commit()

def safe_requests_get(url):
    try:
        r = requests.get(url, timeout=10, stream=True)
        if r.status_code != 200: return None
        content = b''
        for chunk in r.iter_content(4096):
            content += chunk
            if len(content) > REMOTE_MAX_CONTENT_BYTES: break
        return content.decode(errors='ignore')
    except Exception:
        return None

def normalize_text(s):
    if not s: return ''
    return unicodedata.normalize('NFKC', s).lower().strip()

def build_spam_regex(keywords):
    sorted_kws = sorted(list(keywords), key=len, reverse=True)
    escaped_kws = [re.escape(normalize_text(k)) for k in sorted_kws if k.strip()]
    if not escaped_kws: return None
    pattern = r'(?:' + '|'.join(escaped_kws) + r')'
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return None

def update_spam_rules():
    global spam_regex_pattern
    while True:
        try:
            text = safe_requests_get(REMOTE_SPAM_URL)
            remote_words = set()
            if text:
                for line in text.splitlines():
                    w = line.strip()
                    if w: remote_words.add(w)
            all_keywords = set(FALLBACK_SPAM_KEYWORDS) | remote_words
            new_regex = build_spam_regex(all_keywords)
            with _spam_lock:
                spam_regex_pattern = new_regex
                logging.info(f"Rules Updated: {len(all_keywords)}")
        except Exception:
            pass
        time.sleep(SPAM_UPDATE_INTERVAL)

def cleanup_flood_dict():
    while True:
        time.sleep(30)
        now = time.time()
        with _flood_lock:
            to_remove = []
            for uid, timestamps in list(user_flood_control.items()):
                valid = [t for t in timestamps if now - t < FLOOD_WINDOW]
                if not valid:
                    to_remove.append(uid)
                else:
                    user_flood_control[uid] = valid
            for uid in to_remove:
                del user_flood_control[uid]
            db_cleanup_map()

def check_flood(user_id):
    now = time.time()
    with _flood_lock:
        if user_id not in user_flood_control:
            user_flood_control[user_id] = deque(maxlen=MAX_MSGS_PER_WINDOW + 2)
        
        timestamps = user_flood_control[user_id]
        
        while len(timestamps) > 0 and now - timestamps[0] > FLOOD_WINDOW:
            timestamps.popleft()
            
        timestamps.append(now)
        
        return len(timestamps) > MAX_MSGS_PER_WINDOW

def is_spam(text):
    if not text: return False
    text = normalize_text(text)
    text_nospace = re.sub(r'\s+', '', text)
    with _spam_lock:
        if spam_regex_pattern:
            if spam_regex_pattern.search(text) or spam_regex_pattern.search(text_nospace):
                return True
    return False

def inject_noise(text):
    res = ""
    for char in text:
        res += char
        if random.random() < 0.3:
            res += '\u200b'
    return res

def generate_captcha(user_id):
    n1 = random.randint(1, 10)
    n2 = random.randint(1, 10)
    op = random.choice(['+', '-'])
    
    if op == '+':
        ans = n1 + n2
        n1_s = CN_NUM_MAP.get(str(n1), str(n1))
        q_raw = f"{n1_s} 加上 {n2}"
    else:
        if n1 < n2: n1, n2 = n2, n1
        ans = n1 - n2
        n1_s = CN_NUM_MAP.get(str(n1), str(n1))
        q_raw = f"{n1_s} 减去 {n2}"
    
    q_noise = inject_noise(q_raw)
    db_save_captcha(user_id, str(ans))
    return f"🤖 人机验证：\n请计算：{q_noise} = ?\n(请直接回复数字结果)"

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    try: bot.reply_to(message, "👋 您好，消息将转发给管理员。")
    except Exception: pass

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id != ADMIN_ID, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation'])
def handle_incoming(message):
    user_id = message.from_user.id
    
    if message.content_type == 'text':
        result, data = db_check_and_verify(user_id, message.text.strip())
        
        if result == 'banned':
            return
        elif result == 'timeout_ban':
            try: bot.send_message(user_id, "⚠️ 验证超时，暂时封禁。")
            except: pass
            return
        elif result == 'fail_ban':
            try: bot.send_message(user_id, "🚫 错误过多，暂时封禁。")
            except: pass
            return
        elif result == 'wrong_answer':
            try: bot.send_message(user_id, "❌ 答案错误，请重试。")
            except: pass
            return
        elif result == 'success':
            try: bot.send_message(user_id, "✅ 验证通过！请重新发送消息。")
            except: pass
            return
        elif result == 'no_captcha':
             pass 
    
    verified, ban_until = db_get_user_status(user_id)
    if ban_until > time.time(): return
    
    if not verified:
        if message.content_type != 'text':
             try: bot.send_message(user_id, "⚠️ 请先发送文字验证。")
             except: pass
        q = generate_captcha(user_id)
        try: bot.send_message(user_id, q)
        except: pass
        return

    if check_flood(user_id):
        db_ban_user(user_id, FLOOD_PENALTY_TIME)
        try: bot.send_message(user_id, "🚫 频率过高，暂停服务 60秒。")
        except: pass
        return

    text_check = message.text or message.caption or ""
    if is_spam(text_check):
        try: bot.send_message(user_id, "🚫 内容违规。")
        except: pass
        return

    user_info = f"\n👤 {message.from_user.first_name} (ID: {user_id})"
    if message.from_user.username:
        user_info = f"\n👤 @{message.from_user.username} (ID: {user_id})"

    try:
        sent_msg = None
        if message.content_type == 'text':
            sent_msg = bot.send_message(ADMIN_ID, message.text + user_info)
        elif message.content_type == 'photo':
            sent_msg = bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=(message.caption or "") + user_info)
        elif message.content_type == 'sticker':
            sent_msg = bot.send_sticker(ADMIN_ID, message.sticker.file_id)
        elif message.content_type == 'video':
            sent_msg = bot.send_video(ADMIN_ID, message.video.file_id, caption=(message.caption or "") + user_info)
        elif message.content_type == 'document':
            sent_msg = bot.send_document(ADMIN_ID, message.document.file_id, caption=(message.caption or "") + user_info)
        elif message.content_type == 'voice':
            sent_msg = bot.send_voice(ADMIN_ID, message.voice.file_id, caption=(message.caption or "") + user_info)
        
        if sent_msg:
            db_save_map(sent_msg.message_id, user_id)
            if message.content_type != 'sticker':
                bot.send_message(user_id, "✅ 已送达。")
            
    except Exception as e:
        logging.error(f"Fwd Error: {e}")

@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.reply_to_message, content_types=['text', 'photo', 'video', 'document', 'voice', 'sticker'])
def handle_admin_reply(message):
    origin_id = message.reply_to_message.message_id
    target_uid = db_get_map(origin_id)
    
    if not target_uid:
        try: bot.reply_to(message, "⚠️ 找不到发送者。")
        except: pass
        return

    if message.text and message.text.startswith('/'):
        cmd = message.text.split()[0].lower()
        if cmd == '/ban':
            db_ban_user(target_uid, 86400 * 30)
            bot.reply_to(message, f"✅ 已封禁 {target_uid}。")
            return
        elif cmd == '/unban':
            db_unban_user(target_uid)
            bot.reply_to(message, f"✅ 已解封 {target_uid}。")
            return

    try:
        if message.content_type == 'text':
            bot.send_message(target_uid, message.text)
        elif message.content_type == 'photo':
            bot.send_photo(target_uid, message.photo[-1].file_id, caption=message.caption)
        elif message.content_type == 'sticker':
            bot.send_sticker(target_uid, message.sticker.file_id)
        elif message.content_type == 'video':
            bot.send_video(target_uid, message.video.file_id, caption=message.caption)
        elif message.content_type == 'document':
            bot.send_document(target_uid, message.document.file_id, caption=message.caption)
        elif message.content_type == 'voice':
            bot.send_voice(target_uid, message.voice.file_id, caption=message.caption)
        
        bot.reply_to(message, "✅ 回复成功。")
    except apihelper.ApiTelegramException as e:
        if "blocked" in str(e).lower():
            bot.reply_to(message, "❌ 用户已屏蔽机器人。")
        else:
            bot.reply_to(message, "❌ 发送失败。")
    except Exception:
        pass

if __name__ == "__main__":
    init_db()
    
    t_spam = threading.Thread(target=update_spam_rules, daemon=True)
    t_spam.start()
    
    t_clean = threading.Thread(target=cleanup_flood_dict, daemon=True)
    t_clean.start()
    
    logging.info("Core Started.")
    
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception:
            time.sleep(5)
