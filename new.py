import telebot
from telebot import apihelper
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
import logging
import time
import os
import re
import requests
import threading
import queue
import sqlite3
import unicodedata
import html
import random
from collections import deque

BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID_STR = os.environ.get('ADMIN_ID') or os.environ.get('OWNER_ID')
ADMIN_ID = int(ADMIN_ID_STR) if ADMIN_ID_STR else None

WELCOME_ZH = os.environ.get('WELCOME_ZH', "👋 您好，请选择功能或直接发送消息。")
VERIFIED_ZH = os.environ.get('VERIFIED_ZH', "✅ 验证通过！您现在可以发送消息了。")
AUTO_REPLY_ZH = os.environ.get('AUTO_REPLY_ZH', "✅ 消息已送达，管理员会尽快回复。")

WELCOME_EN = os.environ.get('WELCOME_EN', "👋 Hello, please choose an option or send a message directly.")
VERIFIED_EN = os.environ.get('VERIFIED_EN', "✅ Verified! You can now send messages.")
AUTO_REPLY_EN = os.environ.get('AUTO_REPLY_EN', "✅ Message sent. The admin will reply shortly.")

FALLBACK_SPAM_KEYWORDS = [
    "u币", "USDT", "泰达币", "跑分", "博彩", "兼职", "刷单", "各行各业", "代开",
    "发票", "迷药", "枪支", "色情", "裸聊", "办证", "查询", "定位", "监听",
    "傻逼", "出u", "收u", "高价收"
]

DEFAULT_REMOTE_SPAM_URL = "https://raw.githubusercontent.com/sykin7/my-telegram-spam-rules/refs/heads/main/spam.txt"
REMOTE_SPAM_URL = os.environ.get('REMOTE_SPAM_URL', DEFAULT_REMOTE_SPAM_URL)
DB_PATH = os.environ.get('BOT_DB_PATH', '/app/data/bot_core.db')

FLOOD_WINDOW = 10
MAX_MSGS_PER_WINDOW = 6
GLOBAL_MESSAGE_LIMIT = 20
FLOOD_PENALTY_TIME = 900
CAPTCHA_TIMEOUT = 120
MIN_BAN_DURATION = 3600
MAX_BAN_DURATION = 10800
CAPTCHA_MAX_RETRIES = 3
SPAM_UPDATE_INTERVAL = 3600
REMOTE_MAX_CONTENT_BYTES = 128 * 1024
MAX_SPAM_KEYWORDS = 2000
MSG_AUTO_DELETE_DELAY = 10
CAPTCHA_DELETE_DELAY = 60
CACHE_TTL = 300

DB_MAX_ROWS = 1000
DB_SIZE_LIMIT_MB = 10
DB_RETENTION_DAYS = 7
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if not BOT_TOKEN or not ADMIN_ID:
    logging.error("Error: BOT_TOKEN and ADMIN_ID must be set.")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

_db_lock = threading.Lock()
_spam_lock = threading.Lock()
_flood_lock = threading.Lock()
_cache_lock = threading.Lock()

user_flood_control = {}
media_group_cache = {}
user_status_cache = {}
spam_regex_pattern = None
_db_conn = None

_global_token_bucket = GLOBAL_MESSAGE_LIMIT
_last_token_update = time.time()

class MsgDeleter:
    def __init__(self):
        self.queue = queue.PriorityQueue()
        self.running = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def schedule(self, chat_id, message_id, delay):
        delete_at = time.time() + delay
        self.queue.put((delete_at, chat_id, message_id))

    def _worker(self):
        while self.running:
            try:
                task = self.queue.get(timeout=1)
                delete_at, chat_id, message_id = task
                now = time.time()
                if now >= delete_at:
                    try: bot.delete_message(chat_id, message_id)
                    except: pass
                else:
                    self.queue.put(task)
                    time.sleep(min(delete_at - now, 1.0))
            except queue.Empty: continue
            except: pass

class AdminSender:
    def __init__(self):
        self.queue = queue.Queue(maxsize=1000)
        self.running = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def send(self, func, *args, **kwargs):
        try:
            self.queue.put_nowait((func, args, kwargs))
        except queue.Full:
            logging.warning("Admin Queue Full! Message dropped.")

    def _worker(self):
        while self.running:
            try:
                func, args, kwargs = self.queue.get()
                try: func(*args, **kwargs)
                except apihelper.ApiTelegramException as e: logging.error(f"API Error: {e}")
                except Exception as e: logging.error(f"Sender Error: {e}")
                time.sleep(0.2)
            except: pass

deleter = MsgDeleter()
admin_sender = AdminSender()

STRINGS = {
    'captcha_ask': {'zh': "🤖 <b>人机验证</b>：\n请计算：<code>{q}</code> = ?\n(请直接回复数字结果)", 'en': "🤖 <b>CAPTCHA</b>:\nPlease calculate: <code>{q}</code> = ?"},
    'captcha_wrong': {'zh': "❌ 答案错误，请重试。", 'en': "❌ Wrong answer, please try again."},
    'captcha_timeout': {'zh': "⚠️ 验证超时，暂时封禁。", 'en': "⚠️ Verification timed out. Temporarily banned."},
    'captcha_fail': {'zh': "🚫 错误过多，暂时封禁。", 'en': "🚫 Too many errors. Temporarily banned."},
    'flood_ban': {'zh': "🚫 操作过快，系统暂停服务 15分钟。", 'en': "🚫 Too fast. Service paused for 15 mins."},
    'spam_ban': {'zh': "🚫 内容违规（包含违禁词或敏感信息）。", 'en': "🚫 Content violation."},
    'spam_edit_ban': {'zh': "🚫 <b>检测到您在编辑消息中包含违规内容，系统已自动封禁。</b>", 'en': "🚫 <b>Spam detected in edited message. Banned.</b>"},
    'media_no_caption': {'zh': "⚠️ 为了防止垃圾广告，请在发送图片/文件时添加【文字说明】。", 'en': "⚠️ Anti-spam: Please add a CAPTION when sending media."},
    'wait_verify': {'zh': "⚠️ 请先完成上方的验证。", 'en': "⚠️ Please complete verification above."},
    'select_lang': {'zh': "🌐 请选择您的语言 / Please select your language:", 'en': "🌐 Please select your language / 请选择您的语言:"},
    'lang_set': {'zh': "✅ 语言已设置为中文。", 'en': "✅ Language set to English."},
    'menu_contact': {'zh': "📨 联系管理员", 'en': "📨 Contact Admin"},
    'menu_lang': {'zh': "🌐 切换语言", 'en': "🌐 Change Language"},
    'menu_help': {'zh': "❓ 常见问题", 'en': "❓ FAQ"},
    'blacklist_ban': {'zh': "🚫 <b>您已被管理员列入黑名单，所有消息将被忽略。</b>", 'en': "🚫 <b>You have been blacklisted by the admin.</b>"},
    'file_too_large': {'zh': "⚠️ 文件过大 (超过50MB)，无法发送。", 'en': "⚠️ File too large (over 50MB)."}
}

CN_NUM_MAP = {'0': '零', '1': '壹', '2': '贰', '3': '叁', '4': '肆', '5': '伍', '6': '陆', '7': '柒', '8': '捌', '9': '玖', '10': '拾'}

def get_db_conn():
    global _db_conn
    if _db_conn is None:
        try:
            db_dir = os.path.dirname(DB_PATH)
            if db_dir and not os.path.exists(db_dir): os.makedirs(db_dir, exist_ok=True)
        except: pass
        _db_conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
        _db_conn.execute("PRAGMA journal_mode=WAL")
    return _db_conn

def init_db():
    with _db_lock:
        conn = get_db_conn()
        conn.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, verified INTEGER DEFAULT 0, ban_until REAL DEFAULT 0, lang TEXT DEFAULT NULL)''')
        try: conn.execute("ALTER TABLE users ADD COLUMN lang TEXT DEFAULT NULL")
        except: pass
        conn.execute('''CREATE TABLE IF NOT EXISTS pending_captcha (user_id INTEGER PRIMARY KEY, answer TEXT, timestamp REAL, retries INTEGER)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS message_map (msg_id INTEGER PRIMARY KEY, user_id INTEGER, created_at REAL)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_map_created ON message_map(created_at)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS whitelist (user_id INTEGER PRIMARY KEY, added_at REAL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS blacklist (user_id INTEGER PRIMARY KEY, added_at REAL)''')
        conn.commit()

def update_cache(user_id, verified, lang, ban_until, wl=False, bl=False):
    with _cache_lock:
        user_status_cache[user_id] = {'verified': verified, 'lang': lang, 'ban_until': ban_until, 'wl': wl, 'bl': bl, 'ts': time.time()}

def invalidate_cache(user_id):
    with _cache_lock:
        if user_id in user_status_cache: del user_status_cache[user_id]

def db_set_lang(user_id, lang):
    with _db_lock:
        conn = get_db_conn()
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        conn.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, user_id))
        conn.commit()
    invalidate_cache(user_id)

def db_get_full_user_status(user_id):
    with _db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT verified, ban_until, lang FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        verified, ban_until, lang = (0, 0, None)
        if row: verified, ban_until, lang = row
        else:
            conn.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
            conn.commit()
        cur.execute("SELECT 1 FROM whitelist WHERE user_id=?", (user_id,))
        is_wl = cur.fetchone() is not None
        cur.execute("SELECT 1 FROM blacklist WHERE user_id=?", (user_id,))
        is_bl = cur.fetchone() is not None
        return {'verified': verified, 'ban_until': ban_until, 'lang': lang, 'wl': is_wl, 'bl': is_bl}

def get_cached_user_status(user_id):
    now = time.time()
    with _cache_lock:
        data = user_status_cache.get(user_id)
        if data and (now - data['ts'] < CACHE_TTL): return data
    stat = db_get_full_user_status(user_id)
    update_cache(user_id, stat['verified'], stat['lang'], stat['ban_until'], stat['wl'], stat['bl'])
    return stat

def db_check_captcha_exists(user_id):
    with _db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT timestamp FROM pending_captcha WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row and (time.time() - row[0] < CAPTCHA_TIMEOUT): return True
        return False

def db_check_and_verify(user_id, input_ans):
    now = time.time()
    stat = get_cached_user_status(user_id)
    if stat['ban_until'] > now: return 'banned', stat['ban_until']
    if stat['verified'] == 1: return 'verified', 0
    with _db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT answer, timestamp, retries FROM pending_captcha WHERE user_id=?", (user_id,))
        cap_row = cur.fetchone()
        if not cap_row: return 'no_captcha', 0
        expected, ts, retries = cap_row
        if now - ts > CAPTCHA_TIMEOUT:
            ban_until = now + random.randint(MIN_BAN_DURATION, MAX_BAN_DURATION)
            cur.execute("UPDATE users SET verified=0, ban_until=? WHERE user_id=?", (ban_until, user_id))
            cur.execute("DELETE FROM pending_captcha WHERE user_id=?", (user_id,))
            conn.commit()
            invalidate_cache(user_id)
            return 'timeout_ban', ban_until
        if input_ans == expected:
            cur.execute("UPDATE users SET verified=1, ban_until=0 WHERE user_id=?", (user_id,))
            cur.execute("DELETE FROM pending_captcha WHERE user_id=?", (user_id,))
            conn.commit()
            invalidate_cache(user_id)
            return 'success', 0
        else:
            new_retries = retries + 1
            if new_retries >= CAPTCHA_MAX_RETRIES:
                ban_until = now + random.randint(MIN_BAN_DURATION, MAX_BAN_DURATION)
                cur.execute("UPDATE users SET verified=0, ban_until=? WHERE user_id=?", (ban_until, user_id))
                cur.execute("DELETE FROM pending_captcha WHERE user_id=?", (user_id,))
                conn.commit()
                invalidate_cache(user_id)
                return 'fail_ban', ban_until
            else:
                cur.execute("UPDATE pending_captcha SET retries=? WHERE user_id=?", (new_retries, user_id))
                conn.commit()
                return 'wrong_answer', 0

def db_ban_user(user_id, duration):
    ban_until = time.time() + duration
    with _db_lock:
        conn = get_db_conn()
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        conn.execute("UPDATE users SET verified=0, ban_until=? WHERE user_id=?", (ban_until, user_id))
        conn.execute("DELETE FROM pending_captcha WHERE user_id=?", (user_id,))
        conn.commit()
    invalidate_cache(user_id)
    return ban_until

def db_unban_user(user_id):
    with _db_lock:
        conn = get_db_conn()
        conn.execute("UPDATE users SET ban_until=0 WHERE user_id=?", (user_id,))
        conn.commit()
    invalidate_cache(user_id)

def db_save_captcha(user_id, answer):
    with _db_lock:
        conn = get_db_conn()
        conn.execute("INSERT OR REPLACE INTO pending_captcha (user_id, answer, timestamp, retries) VALUES (?, ?, ?, 0)",
                     (user_id, answer, time.time()))
        conn.commit()

def db_save_map(msg_id, user_id):
    cleaned_info = None
    with _db_lock:
        conn = get_db_conn()
        conn.execute("INSERT OR REPLACE INTO message_map (msg_id, user_id, created_at) VALUES (?, ?, ?)",
                     (msg_id, user_id, time.time()))
        
        if random.random() < 0.1:
            try:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM message_map")
                count = cur.fetchone()[0]
                if count > DB_MAX_ROWS:
                    limit_cnt = count - DB_MAX_ROWS
                    conn.execute(f"DELETE FROM message_map WHERE msg_id IN (SELECT msg_id FROM message_map ORDER BY created_at ASC LIMIT {limit_cnt})")
                    cleaned_info = f"🗑️ 数据库清理: 自动覆盖了 {limit_cnt} 条旧消息记录。"

                if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > (DB_SIZE_LIMIT_MB * 1024 * 1024):
                    conn.execute("VACUUM")
                    cleaned_info = "🧹 数据库清理: 文件过大，已执行 VACUUM 压缩。"
            except Exception as e:
                logging.error(f"DB Cleanup Error: {e}")
                
        conn.commit()

    if cleaned_info:
        try: bot.send_message(ADMIN_ID, cleaned_info)
        except: pass

def db_get_map(msg_id):
    with _db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM message_map WHERE msg_id=?", (msg_id,))
        row = cur.fetchone()
        return row[0] if row else None

def db_cleanup_map():
    limit_time = time.time() - (86400 * DB_RETENTION_DAYS)
    with _db_lock:
        conn = get_db_conn()
        conn.execute("DELETE FROM message_map WHERE created_at < ?", (limit_time,))
        conn.commit()

def db_add_to_list(table_name, user_id):
    with _db_lock:
        conn = get_db_conn()
        try:
            conn.execute(f"INSERT OR REPLACE INTO {table_name} (user_id, added_at) VALUES (?, ?)", (user_id, time.time()))
            conn.commit()
            success = True
        except sqlite3.Error: success = False
    if success: invalidate_cache(user_id)
    return success

def db_remove_from_list(table_name, user_id):
    with _db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(f"DELETE FROM {table_name} WHERE user_id=?", (user_id,))
        conn.commit()
        success = cur.rowcount > 0
    if success: invalidate_cache(user_id)
    return success

def db_get_list(table_name):
    with _db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(f"SELECT user_id, added_at FROM {table_name} ORDER BY added_at DESC")
        return cur.fetchall()

def safe_requests_get(url):
    try:
        r = requests.get(url, timeout=10, stream=True)
        if r.status_code != 200: return None
        content = b''
        for chunk in r.iter_content(4096):
            content += chunk
            if len(content) > REMOTE_MAX_CONTENT_BYTES: break
        return content.decode(errors='ignore')
    except Exception: return None

def normalize_text(s):
    if not s: return ''
    return unicodedata.normalize('NFKC', s).lower().strip()

def build_spam_regex(keywords):
    sorted_kws = sorted(list(keywords), key=len, reverse=True)[:MAX_SPAM_KEYWORDS]
    escaped_kws = [re.escape(normalize_text(k)) for k in sorted_kws if k.strip()]
    if not escaped_kws: return None
    pattern = r'(?:' + '|'.join(escaped_kws) + r')'
    try: return re.compile(pattern, re.IGNORECASE)
    except re.error: return None

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
        except Exception: pass
        time.sleep(SPAM_UPDATE_INTERVAL)

def cleanup_dict():
    while True:
        time.sleep(30)
        now = time.time()
        with _flood_lock:
            to_remove = []
            for uid, timestamps in list(user_flood_control.items()):
                valid = [t for t in timestamps if now - t < FLOOD_WINDOW]
                if not valid: to_remove.append(uid)
                else: user_flood_control[uid] = valid
            for uid in to_remove: del user_flood_control[uid]
            to_remove_grp = []
            for gid, ts in list(media_group_cache.items()):
                if now - ts > 5: to_remove_grp.append(gid)
            for gid in to_remove_grp: del media_group_cache[gid]
        with _cache_lock:
            to_del_cache = [k for k, v in user_status_cache.items() if now - v['ts'] > CACHE_TTL]
            for k in to_del_cache: del user_status_cache[k]
        if int(now) % 86400 < 60: db_cleanup_map()

def check_global_limit():
    global _global_token_bucket, _last_token_update
    now = time.time()
    time_passed = now - _last_token_update
    new_tokens = int(time_passed * GLOBAL_MESSAGE_LIMIT)
    if new_tokens > 0:
        _global_token_bucket = min(GLOBAL_MESSAGE_LIMIT, _global_token_bucket + new_tokens)
        _last_token_update = now
    if _global_token_bucket > 0:
        _global_token_bucket -= 1
        return True
    return False

def check_flood(user_id, media_group_id=None):
    now = time.time()
    with _flood_lock:
        if media_group_id:
            if media_group_id in media_group_cache: return False
            media_group_cache[media_group_id] = now
        if user_id not in user_flood_control:
            user_flood_control[user_id] = deque(maxlen=MAX_MSGS_PER_WINDOW + 2)
        timestamps = user_flood_control[user_id]
        while len(timestamps) > 0 and now - timestamps[0] > FLOOD_WINDOW:
            timestamps.popleft()
        timestamps.append(now)
        return len(timestamps) > MAX_MSGS_PER_WINDOW

def is_spam_text(text):
    if not text: return False
    text = normalize_text(text)
    if len(text) > 5000: text = text[:5000]
    text_nospace = re.sub(r'\s+', '', text)
    text_cleaned = re.sub(r'[^\w]', '', text)
    with _spam_lock:
        if spam_regex_pattern:
            try:
                if (spam_regex_pattern.search(text) or spam_regex_pattern.search(text_nospace) or spam_regex_pattern.search(text_cleaned)): return True
            except: return False
    return False

def check_deep_spam(message):
    content = message.text or message.caption or ""
    if is_spam_text(content): return True
    user = message.from_user
    if is_spam_text(user.first_name): return True
    if is_spam_text(user.last_name): return True
    if is_spam_text(user.username): return True
    if message.document and hasattr(message.document, 'file_name'):
        if is_spam_text(message.document.file_name): return True
    return False

def inject_noise(text):
    res = ""
    for char in text:
        res += char
        if random.random() < 0.3: res += '\u200b'
    return res

def get_text(key, user_id, **kwargs):
    stat = get_cached_user_status(user_id)
    lang = stat['lang'] if stat['lang'] else 'zh'
    txt = STRINGS.get(key, {}).get(lang, STRINGS.get(key, {}).get('zh', ''))
    if kwargs: return txt.format(**kwargs)
    return txt

def send_menu(user_id, text=None):
    stat = get_cached_user_status(user_id)
    lang = stat['lang'] if stat['lang'] else 'zh'
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton(STRINGS['menu_contact'][lang]), KeyboardButton(STRINGS['menu_help'][lang]), KeyboardButton(STRINGS['menu_lang'][lang]))
    msg = text if text else (WELCOME_ZH if lang == 'zh' else WELCOME_EN)
    try:
        m = bot.send_message(user_id, msg, reply_markup=markup)
        deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
    except: pass

def ask_language(chat_id):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🇨🇳 中文", callback_data="set_lang:zh"), InlineKeyboardButton("🇺🇸 English", callback_data="set_lang:en"))
    try:
        m = bot.send_message(chat_id, STRINGS['select_lang']['zh'], reply_markup=markup)
        deleter.schedule(chat_id, m.message_id, MSG_AUTO_DELETE_DELAY)
    except: pass

def generate_captcha(user_id):
    if db_check_captcha_exists(user_id): return get_text('wait_verify', user_id)
    stat = get_cached_user_status(user_id)
    lang = stat['lang'] if stat['lang'] else 'zh'
    n1 = random.randint(1, 10)
    n2 = random.randint(1, 10)
    op = random.choice(['+', '-'])
    if op == '+':
        ans = n1 + n2
        n1_s = CN_NUM_MAP.get(str(n1), str(n1)) if lang == 'zh' else str(n1)
        q_raw = f"{n1_s} + {n2}" if lang == 'zh' else f"{n1} + {n2}"
    else:
        if n1 < n2: n1, n2 = n2, n1
        ans = n1 - n2
        n1_s = CN_NUM_MAP.get(str(n1), str(n1)) if lang == 'zh' else str(n1)
        q_raw = f"{n1_s} - {n2}" if lang == 'zh' else f"{n1} - {n2}"
    q_noise = inject_noise(q_raw)
    db_save_captcha(user_id, str(ans))
    return get_text('captcha_ask', user_id, q=q_noise)

def get_help_message(is_admin, user_id):
    stat = get_cached_user_status(user_id)
    lang = stat['lang'] if stat['lang'] else 'zh'
    help_msg = "📚 **机器人指令帮助**\n\n👉 **用户指令**\n• `/start` / `/help`: 打开菜单\n"
    if is_admin:
        help_msg += "\n👑 **管理员指令 (Admin)**\n• 回复消息 `/ban`: 封禁\n• 回复消息 `/unban`: 解封\n• 回复消息 `/awl`: 加白名单\n• 回复消息 `/abl`: 加黑名单\n• `/gb <内容>`: 广播\n• `/awl <ID>`: ID加白\n• `/vlist wl`: 看白名单"
    return help_msg

def broadcast_thread(text):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    all_users = cursor.fetchall()
    conn.close()
    success_count, fail_count = 0, 0
    for row in all_users:
        try:
            bot.send_message(row[0], text)
            success_count += 1
            time.sleep(0.05)
        except: fail_count += 1
    try: bot.send_message(ADMIN_ID, f"📢 广播结束\n✅: {success_count}\n❌: {fail_count}")
    except: pass

@bot.message_handler(commands=['gb'])
def handle_broadcast_command(message):
    if message.from_user.id != ADMIN_ID: return
    msg_text = message.text.replace('/gb', '').strip()
    if not msg_text: return
    bot.reply_to(message, "🚀 广播开始...")
    threading.Thread(target=broadcast_thread, args=(msg_text,), daemon=True).start()

@bot.message_handler(commands=['awl', 'dwl', 'abl', 'dbl', 'vlist'])
def handle_list_commands(message):
    if message.from_user.id != ADMIN_ID: return
    cmd = message.text.split()[0].lower().replace('/', '')
    parts = message.text.split()
    if cmd in ['awl', 'dwl', 'abl', 'dbl']:
        if len(parts) < 2: return
        try: target_uid = int(parts[1].strip())
        except: return
        list_name = 'whitelist' if cmd.endswith('wl') else 'blacklist'
        if cmd.startswith('a'):
            if db_add_to_list(list_name, target_uid): bot.reply_to(message, f"✅ ID {target_uid} 已加入 {list_name}。")
        else:
            if db_remove_from_list(list_name, target_uid): bot.reply_to(message, f"✅ ID {target_uid} 已移出 {list_name}。")
    elif cmd == 'vlist':
        list_name = 'whitelist' if (len(parts) > 1 and parts[1] == 'wl') else 'blacklist'
        data = db_get_list(list_name)
        msg = f"📋 {list_name} ({len(data)}):\n" + "\n".join([f"• {u[0]}" for u in data[:50]])
        bot.reply_to(message, msg)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_lang:'))
def handle_language_callback(call):
    db_set_lang(call.from_user.id, call.data.split(':')[1])
    try:
        bot.answer_callback_query(call.id, "OK")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        send_menu(call.from_user.id, get_text('lang_set', call.from_user.id))
    except: pass

@bot.message_handler(commands=['start', 'help'])
def send_welcome_handler(message):
    user_id = message.from_user.id
    user_status = get_cached_user_status(user_id)
    if user_status['bl']: return
    deleter.schedule(user_id, message.message_id, MSG_AUTO_DELETE_DELAY)
    if check_flood(user_id):
        db_ban_user(user_id, FLOOD_PENALTY_TIME)
        return
    if message.text == '/start':
        if user_status.get('lang'): send_menu(user_id)
        else: ask_language(user_id)
    else:
        m = bot.send_message(user_id, get_help_message(user_id==ADMIN_ID, user_id), parse_mode='Markdown')
        deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
        send_menu(user_id)

@bot.edited_message_handler(func=lambda m: True)
def handle_edited_message(message):
    if message.from_user.id == ADMIN_ID: return
    user_id = message.from_user.id
    user_status = get_cached_user_status(user_id)
    
    if user_status['wl']: return
    if user_status['bl']: return

    if check_deep_spam(message):
        db_ban_user(user_id, MAX_BAN_DURATION)
        try:
            bot.delete_message(message.chat.id, message.message_id)
            m = bot.send_message(user_id, get_text('spam_edit_ban', user_id), parse_mode='HTML')
            deleter.schedule(user_id, m.message_id, 30)
            alert_msg = f"⚠️ <b>检测到违规编辑</b>\n用户: {user_id}\n操作: 已封禁并删除消息。"
            bot.send_message(ADMIN_ID, alert_msg, parse_mode='HTML')
        except: pass

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id != ADMIN_ID, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation', 'video_note', 'location', 'contact', 'dice'])
def handle_incoming(message):
    if not check_global_limit(): return
    user_id = message.from_user.id
    user_status = get_cached_user_status(user_id)
    if user_status['bl']:
        try:
            m = bot.send_message(user_id, get_text('blacklist_ban', user_id), parse_mode='HTML')
            deleter.schedule(user_id, message.message_id, 1)
            deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
        except: pass
        return

    is_whitelisted = user_status['wl']

    if not is_whitelisted:
        if check_flood(user_id, getattr(message, 'media_group_id', None)):
            db_ban_user(user_id, FLOOD_PENALTY_TIME)
            m = bot.send_message(user_id, get_text('flood_ban', user_id))
            deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
            deleter.schedule(user_id, message.message_id, MSG_AUTO_DELETE_DELAY)
            return

        if check_deep_spam(message):
            m = bot.send_message(user_id, get_text('spam_ban', user_id))
            deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
            deleter.schedule(user_id, message.message_id, MSG_AUTO_DELETE_DELAY)
            return
        
        if message.content_type == 'text':
            result, data = db_check_and_verify(user_id, message.text.strip())
            if result == 'banned': return
            elif result in ['timeout_ban', 'fail_ban', 'wrong_answer']:
                key = 'captcha_timeout' if result == 'timeout_ban' else ('captcha_fail' if result == 'fail_ban' else 'captcha_wrong')
                m = bot.send_message(user_id, get_text(key, user_id))
                deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
                deleter.schedule(user_id, message.message_id, 1)
                return
            elif result == 'success':
                deleter.schedule(user_id, message.message_id, 1)
                send_menu(user_id, get_text('verified_zh' if user_status.get('lang')=='zh' else 'verified_en', user_id))
                return

        if user_status['ban_until'] > time.time(): return
        
        if not user_status['verified']:
            if message.content_type != 'text':
                 m = bot.send_message(user_id, get_text('wait_verify', user_id))
                 deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
                 deleter.schedule(user_id, message.message_id, MSG_AUTO_DELETE_DELAY)
            q = generate_captcha(user_id)
            m = bot.send_message(user_id, q, parse_mode='HTML')
            deleter.schedule(user_id, m.message_id, CAPTCHA_DELETE_DELAY)
            return

    lang = user_status['lang'] if user_status['lang'] else 'zh'
    if message.content_type == 'text':
        if message.text in [STRINGS['menu_contact'][lang], STRINGS['menu_help'][lang], STRINGS['menu_lang'][lang]]:
            if message.text == STRINGS['menu_lang'][lang]: ask_language(user_id)
            elif message.text == STRINGS['menu_help'][lang]: 
                m = bot.send_message(user_id, "💡 FAQ / 常见问题:\n1. 消息直接发送。\n2. 违规自动封禁。")
                deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
            else: 
                m = bot.send_message(user_id, WELCOME_ZH if lang == 'zh' else WELCOME_EN)
                deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
            deleter.schedule(user_id, message.message_id, MSG_AUTO_DELETE_DELAY)
            return

    file_size = 0
    if message.content_type == 'photo': file_size = message.photo[-1].file_size
    elif message.content_type == 'video': file_size = message.video.file_size
    elif message.content_type == 'document': file_size = message.document.file_size
    elif message.content_type == 'audio': file_size = message.audio.file_size
    elif message.content_type == 'animation': file_size = message.animation.file_size
    elif message.content_type == 'voice': file_size = message.voice.file_size
    elif message.content_type == 'video_note': file_size = message.video_note.file_size
    
    if file_size > MAX_FILE_SIZE_BYTES:
        m = bot.send_message(user_id, get_text('file_too_large', user_id))
        deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
        deleter.schedule(user_id, message.message_id, MSG_AUTO_DELETE_DELAY)
        return

    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    full_name = (first_name + " " + last_name).strip() or "User"
    safe_name = html.escape(full_name)
    
    username = message.from_user.username
    uname_line = f"🔗 @{username}" if username else "🔗 No Username"
    lang_code = user_status.get('lang', 'zh') or 'zh'
    
    user_info = f"\n\n👤 <a href='tg://user?id={user_id}'>{safe_name}</a>\n{uname_line}\n🆔 <code>{user_id}</code> [Lang: {lang_code}]" + (" 🟢" if is_whitelisted else "")
    
    def send_wrapper():
        try:
            sent = None
            if message.content_type == 'text':
                sent = bot.send_message(ADMIN_ID, html.escape(message.text) + user_info, parse_mode='HTML')
            elif message.content_type == 'photo':
                sent = bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=html.escape(message.caption or "")+user_info, parse_mode='HTML')
            elif message.content_type == 'video':
                sent = bot.send_video(ADMIN_ID, message.video.file_id, caption=html.escape(message.caption or "")+user_info, parse_mode='HTML')
            elif message.content_type == 'animation':
                sent = bot.send_animation(ADMIN_ID, message.animation.file_id, caption=html.escape(message.caption or "")+user_info, parse_mode='HTML')
            elif message.content_type == 'audio':
                sent = bot.send_audio(ADMIN_ID, message.audio.file_id, caption=html.escape(message.caption or "")+user_info, parse_mode='HTML')
            elif message.content_type == 'document':
                sent = bot.send_document(ADMIN_ID, message.document.file_id, caption=html.escape(message.caption or "")+user_info, parse_mode='HTML')
            elif message.content_type == 'sticker':
                bot.send_sticker(ADMIN_ID, message.sticker.file_id)
                sent = bot.send_message(ADMIN_ID, user_info, parse_mode='HTML')
            elif message.content_type == 'voice':
                sent = bot.send_voice(ADMIN_ID, message.voice.file_id, caption=user_info, parse_mode='HTML')
            elif message.content_type == 'video_note':
                bot.send_video_note(ADMIN_ID, message.video_note.file_id)
                sent = bot.send_message(ADMIN_ID, user_info, parse_mode='HTML')
            elif message.content_type == 'location':
                bot.send_location(ADMIN_ID, message.location.latitude, message.location.longitude)
                sent = bot.send_message(ADMIN_ID, user_info, parse_mode='HTML')
            elif message.content_type == 'contact':
                bot.send_contact(ADMIN_ID, phone_number=message.contact.phone_number, first_name=message.contact.first_name)
                sent = bot.send_message(ADMIN_ID, user_info, parse_mode='HTML')
            elif message.content_type == 'dice':
                bot.send_dice(ADMIN_ID, emoji=message.dice.emoji)
                sent = bot.send_message(ADMIN_ID, user_info, parse_mode='HTML')
            
            if sent: db_save_map(sent.message_id, user_id)
        except Exception as e: logging.error(f"Fwd Error: {e}")

    admin_sender.send(send_wrapper)
    
    if not getattr(message, 'media_group_id', None):
        m = bot.send_message(user_id, AUTO_REPLY_ZH if lang == 'zh' else AUTO_REPLY_EN)
        deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)

@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.reply_to_message, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation', 'video_note', 'location', 'contact', 'dice'])
def handle_admin_reply(message):
    target_uid = db_get_map(message.reply_to_message.message_id)
    if not target_uid:
        try: 
            m = bot.reply_to(message, "⚠️ 消息太久远，已无法回复 (ID丢失)。")
            deleter.schedule(ADMIN_ID, m.message_id, 5)
        except: pass
        return

    if message.text and message.text.startswith('/'):
        cmd = message.text.split()[0].lower()
        if cmd == '/ban':
            db_ban_user(target_uid, 86400 * 30)
            bot.reply_to(message, f"✅ 已封禁 {target_uid}")
            return
        elif cmd == '/unban':
            db_unban_user(target_uid)
            bot.reply_to(message, f"✅ 已解封 {target_uid}")
            return
        elif cmd == '/awl':
            db_add_to_list('whitelist', target_uid)
            bot.reply_to(message, f"✅ 已白名单 {target_uid}")
            return
        elif cmd == '/abl':
            db_add_to_list('blacklist', target_uid)
            bot.reply_to(message, f"✅ 已黑名单 {target_uid}")
            return

    try:
        if message.content_type == 'text': bot.send_message(target_uid, message.text)
        elif message.content_type == 'photo': bot.send_photo(target_uid, message.photo[-1].file_id, caption=message.caption)
        elif message.content_type == 'sticker': bot.send_sticker(target_uid, message.sticker.file_id)
        elif message.content_type == 'video': bot.send_video(target_uid, message.video.file_id, caption=message.caption)
        elif message.content_type == 'animation': bot.send_animation(target_uid, message.animation.file_id, caption=message.caption)
        elif message.content_type == 'audio': bot.send_audio(target_uid, message.audio.file_id, caption=message.caption)
        elif message.content_type == 'voice': bot.send_voice(target_uid, message.voice.file_id)
        elif message.content_type == 'document': bot.send_document(target_uid, message.document.file_id, caption=message.caption)
        elif message.content_type == 'video_note': bot.send_video_note(target_uid, message.video_note.file_id)
        elif message.content_type == 'location': bot.send_location(target_uid, message.location.latitude, message.location.longitude)
        elif message.content_type == 'contact': bot.send_contact(target_uid, phone_number=message.contact.phone_number, first_name=message.contact.first_name)
        elif message.content_type == 'dice': bot.send_dice(target_uid, emoji=message.dice.emoji)
        m = bot.reply_to(message, "✅ 已发送")
        deleter.schedule(ADMIN_ID, m.message_id, 5)
    except:
        m = bot.reply_to(message, "❌ 发送失败 (用户可能屏蔽了机器人)")
        deleter.schedule(ADMIN_ID, m.message_id, 5)

if __name__ == "__main__":
    init_db()
    threading.Thread(target=update_spam_rules, daemon=True).start()
    threading.Thread(target=cleanup_dict, daemon=True).start()
    logging.info("Bot Started.")
    while True:
        try: bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except: time.sleep(5)
