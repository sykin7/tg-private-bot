# -*- coding: utf-8 -*-
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
import secrets
from collections import deque

try:
    import redis
except ImportError:
    redis = None

try:
    import psycopg
    from psycopg.rows import tuple_row
except ImportError:
    psycopg = None
    tuple_row = None

BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID_STR = os.environ.get('ADMIN_ID') or os.environ.get('OWNER_ID')
try:
    ADMIN_ID = int(ADMIN_ID_STR) if ADMIN_ID_STR else None
except ValueError:
    ADMIN_ID = None

WELCOME_ZH = os.environ.get('WELCOME_ZH') or "👋 您好，请选择功能或直接发送消息。"
VERIFIED_ZH = os.environ.get('VERIFIED_ZH') or "✅ 验证通过！您现在可以发送消息了。"
AUTO_REPLY_ZH = os.environ.get('AUTO_REPLY_ZH') or "✅ 消息已送达，管理员会尽快回复。"

WELCOME_EN = os.environ.get('WELCOME_EN') or "👋 Hello, please choose an option or send a message directly."
VERIFIED_EN = os.environ.get('VERIFIED_EN') or "✅ Verified! You can now send messages."
AUTO_REPLY_EN = os.environ.get('AUTO_REPLY_EN') or "✅ Message sent. The admin will reply shortly."

FALLBACK_SPAM_KEYWORDS = [
    "u币", "USDT", "泰达币", "跑分", "博彩", "兼职", "刷单", "各行各业", "代开",
    "发票", "迷药", "枪支", "色情", "裸聊", "办证", "查询", "定位", "监听",
    "傻逼", "出u", "收u", "高价收"
]

SPAM_MARKETING_TERMS = [
    "代开", "发票", "办证", "兼职", "刷单", "博彩", "担保", "盘口", "上分", "下分", "跑分",
    "出u", "收u", "usdt", "泰达币", "高价", "返佣", "推广", "引流", "开户", "接单",
    "私聊", "加我", "联系", "客服", "代理", "项目", "赚钱", "变现", "裸聊", "约炮"
]

CONFUSABLE_TRANS = str.maketrans({
    '0': 'o', '1': 'l', '3': 'e', '4': 'a', '5': 's', '7': 't', '@': 'a', '$': 's', '|': 'l'
})

DEFAULT_REMOTE_SPAM_URL = "https://raw.githubusercontent.com/sykin7/my-telegram-spam-rules/refs/heads/main/spam.txt"
REMOTE_SPAM_URL = os.environ.get('REMOTE_SPAM_URL') or DEFAULT_REMOTE_SPAM_URL
DB_PATH = os.environ.get('BOT_DB_PATH', '/app/data/bot_core.db')
DATABASE_URL = os.environ.get('DATABASE_URL') or os.environ.get('POSTGRES_DSN')
REDIS_URL = os.environ.get('REDIS_URL')
REDIS_ENABLED = os.environ.get('REDIS_ENABLED', 'true').lower() not in ('0', 'false', 'no', 'off')
MIGRATE_SQLITE_TO_POSTGRES = os.environ.get('MIGRATE_SQLITE_TO_POSTGRES', 'false').lower() in ('1', 'true', 'yes', 'on')
CAPTCHA_TEXT_FALLBACK = os.environ.get('CAPTCHA_TEXT_FALLBACK', 'false').lower() in ('1', 'true', 'yes', 'on')

FLOOD_WINDOW = 10
MAX_MSGS_PER_WINDOW = 6
GLOBAL_MESSAGE_LIMIT = 20
OUTBOUND_MESSAGE_LIMIT = 25
FLOOD_PENALTY_TIME = 900
CAPTCHA_TIMEOUT = 120
CAPTCHA_PROMPT_COOLDOWN = 45
UNVERIFIED_SILENCE_TIME = 300
UNVERIFIED_MAX_PROMPTS = 3
UNVERIFIED_WINDOW = 600
MIN_BAN_DURATION = 3600
MAX_BAN_DURATION = 10800
CAPTCHA_MAX_RETRIES = 3
SPAM_UPDATE_INTERVAL = 3600
REMOTE_MAX_CONTENT_BYTES = 128 * 1024
MAX_SPAM_KEYWORDS = 2000
MSG_AUTO_DELETE_DELAY = 10
CAPTCHA_DELETE_DELAY = 60
CACHE_TTL = 300
DB_TOUCH_INTERVAL = 3600
DB_CLEANUP_INTERVAL = 3600

DB_MAX_ROWS = 1000
DB_SIZE_LIMIT_MB = 10
DB_RETENTION_DAYS = 7
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024
DELETE_QUEUE_MAXSIZE = 5000
MAX_FORWARD_TEXT_PARTS = 10

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if not BOT_TOKEN or not ADMIN_ID:
    logging.error("Error: BOT_TOKEN and ADMIN_ID must be set.")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

_db_lock = threading.Lock()
_spam_lock = threading.Lock()
_flood_lock = threading.Lock()
_cache_lock = threading.Lock()
_global_limit_lock = threading.Lock()
_outbound_limit_lock = threading.Lock()

user_flood_control = {}
media_group_cache = {}
user_status_cache = {}
captcha_prompt_state = {}
spam_regex_pattern = None
_db_conn = None
_redis_client = None
_use_postgres = bool(DATABASE_URL and psycopg)

_global_token_bucket = GLOBAL_MESSAGE_LIMIT
_last_token_update = time.time()
_outbound_token_bucket = OUTBOUND_MESSAGE_LIMIT
_last_outbound_token_update = time.time()
_last_db_cleanup = 0

def get_redis_client():
    global _redis_client
    if not REDIS_ENABLED or not REDIS_URL or redis is None: return None
    if _redis_client is not None: return _redis_client
    try:
        client = redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=3, socket_timeout=3)
        client.ping()
        _redis_client = client
        logging.info("Redis connected.")
    except Exception as e:
        logging.warning(f"Redis unavailable, falling back to memory state: {e}")
        _redis_client = None
    return _redis_client

def redis_rate_limit(key, limit, window):
    client = get_redis_client()
    if not client: return None
    try:
        current = client.incr(key)
        if current == 1: client.expire(key, window)
        return current <= limit
    except Exception as e:
        logging.warning(f"Redis rate limit failed for {key}: {e}")
        return None

def redis_set_once(key, value, ttl):
    client = get_redis_client()
    if not client: return None
    try:
        return bool(client.set(key, value, nx=True, ex=ttl))
    except Exception as e:
        logging.warning(f"Redis set-once failed for {key}: {e}")
        return None

def redis_delete(key):
    client = get_redis_client()
    if not client: return False
    try:
        client.delete(key)
        return True
    except Exception as e:
        logging.warning(f"Redis delete failed for {key}: {e}")
        return False

def check_outbound_limit():
    global _outbound_token_bucket, _last_outbound_token_update
    allowed = redis_rate_limit('bot:rate:outbound:1s', OUTBOUND_MESSAGE_LIMIT, 1)
    if allowed is not None: return allowed
    with _outbound_limit_lock:
        now = time.time()
        time_passed = now - _last_outbound_token_update
        new_tokens = int(time_passed * OUTBOUND_MESSAGE_LIMIT)
        if new_tokens > 0:
            _outbound_token_bucket = min(OUTBOUND_MESSAGE_LIMIT, _outbound_token_bucket + new_tokens)
            _last_outbound_token_update = now
        if _outbound_token_bucket > 0:
            _outbound_token_bucket -= 1
            return True
        return False

def safe_send(func, *args, **kwargs):
    while not check_outbound_limit():
        time.sleep(0.05)
    return func(*args, **kwargs)

class MsgDeleter:
    def __init__(self):
        self.queue = queue.PriorityQueue(maxsize=DELETE_QUEUE_MAXSIZE)
        self.running = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def schedule(self, chat_id, message_id, delay):
        delete_at = time.time() + delay
        try:
            self.queue.put_nowait((delete_at, chat_id, message_id))
        except queue.Full:
            logging.warning("Delete queue full; message cleanup skipped.")

    def _worker(self):
        while self.running:
            try:
                task = self.queue.get(timeout=1)
                delete_at, chat_id, message_id = task
                now = time.time()
                if now >= delete_at:
                    try: safe_send(bot.delete_message, chat_id, message_id)
                    except Exception as e: logging.debug(f"Delete message failed: {e}")
                else:
                    self.queue.put(task)
                    time.sleep(min(delete_at - now, 1.0))
            except queue.Empty: continue
            except Exception as e: logging.exception(f"MsgDeleter worker error: {e}")

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
                except apihelper.ApiTelegramException as e: logging.exception(f"API Error: {e}")
                except Exception as e: logging.exception(f"Sender Error: {e}")
                time.sleep(0.2)
            except Exception as e: logging.exception(f"AdminSender worker error: {e}")

deleter = MsgDeleter()
admin_sender = AdminSender()

STRINGS = {
    'captcha_ask': {'zh': "🤖 <b>人机验证</b>：\n请计算：<code>{q}</code> = ?\n请点击下方正确答案。", 'en': "🤖 <b>CAPTCHA</b>:\nPlease calculate: <code>{q}</code> = ?\nTap the correct answer below."},
    'captcha_wrong': {'zh': "❌ 答案错误，请重试。", 'en': "❌ Wrong answer, please try again."},
    'captcha_timeout': {'zh': "⚠️ 验证超时，暂时封禁。", 'en': "⚠️ Verification timed out. Temporarily banned."},
    'captcha_fail': {'zh': "🚫 错误过多，暂时封禁。", 'en': "🚫 Too many errors. Temporarily banned."},
    'captcha_stale': {'zh': "⚠️ 验证已刷新，请点击最新验证码。", 'en': "⚠️ CAPTCHA refreshed. Please use the latest one."},
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

def db_is_postgres():
    return bool(_use_postgres)

def db_param(sql):
    return sql.replace('?', '%s') if db_is_postgres() else sql

def get_db_conn():
    global _db_conn, _use_postgres
    if _db_conn is None:
        if DATABASE_URL and psycopg:
            _db_conn = psycopg.connect(DATABASE_URL, row_factory=tuple_row, autocommit=False)
            _use_postgres = True
            logging.info("PostgreSQL connected.")
        else:
            if DATABASE_URL and not psycopg:
                logging.warning("DATABASE_URL is set but psycopg is not installed; falling back to SQLite.")
            try:
                db_dir = os.path.dirname(DB_PATH)
                if db_dir and not os.path.exists(db_dir): os.makedirs(db_dir, exist_ok=True)
            except Exception as e: logging.warning(f"Ensure DB directory failed: {e}")
            _db_conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
            _db_conn.execute("PRAGMA journal_mode=WAL")
            _use_postgres = False
    return _db_conn

def db_execute(conn, sql, params=()):
    return conn.execute(db_param(sql), params)

def db_insert_user_ignore(conn, user_id, last_seen=None):
    last_seen = time.time() if last_seen is None else last_seen
    if db_is_postgres():
        db_execute(conn, "INSERT INTO users (user_id, last_seen) VALUES (?, ?) ON CONFLICT (user_id) DO NOTHING", (user_id, last_seen))
    else:
        db_execute(conn, "INSERT OR IGNORE INTO users (user_id, last_seen) VALUES (?, ?)", (user_id, last_seen))

def db_upsert_captcha(conn, user_id, answer, token):
    if db_is_postgres():
        db_execute(conn, "INSERT INTO pending_captcha (user_id, answer, token, timestamp, retries) VALUES (?, ?, ?, ?, 0) ON CONFLICT (user_id) DO UPDATE SET answer=EXCLUDED.answer, token=EXCLUDED.token, timestamp=EXCLUDED.timestamp, retries=0", (user_id, answer, token, time.time()))
    else:
        db_execute(conn, "INSERT OR REPLACE INTO pending_captcha (user_id, answer, token, timestamp, retries) VALUES (?, ?, ?, ?, 0)", (user_id, answer, token, time.time()))

def db_upsert_map(conn, msg_id, user_id):
    if db_is_postgres():
        db_execute(conn, "INSERT INTO message_map (msg_id, user_id, created_at) VALUES (?, ?, ?) ON CONFLICT (msg_id) DO UPDATE SET user_id=EXCLUDED.user_id, created_at=EXCLUDED.created_at", (msg_id, user_id, time.time()))
    else:
        db_execute(conn, "INSERT OR REPLACE INTO message_map (msg_id, user_id, created_at) VALUES (?, ?, ?)", (msg_id, user_id, time.time()))

def init_db():
    with _db_lock:
        conn = get_db_conn()
        db_execute(conn, '''CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, verified INTEGER DEFAULT 0, ban_until DOUBLE PRECISION DEFAULT 0, lang TEXT DEFAULT NULL, last_seen DOUBLE PRECISION DEFAULT 0)''')
        db_execute(conn, '''CREATE TABLE IF NOT EXISTS pending_captcha (user_id BIGINT PRIMARY KEY, answer TEXT, token TEXT DEFAULT NULL, timestamp DOUBLE PRECISION, retries INTEGER)''')
        db_execute(conn, '''CREATE TABLE IF NOT EXISTS message_map (msg_id BIGINT PRIMARY KEY, user_id BIGINT, created_at DOUBLE PRECISION)''')
        db_execute(conn, '''CREATE INDEX IF NOT EXISTS idx_map_created ON message_map(created_at)''')
        db_execute(conn, '''CREATE TABLE IF NOT EXISTS whitelist (user_id BIGINT PRIMARY KEY, added_at DOUBLE PRECISION)''')
        db_execute(conn, '''CREATE TABLE IF NOT EXISTS blacklist (user_id BIGINT PRIMARY KEY, added_at DOUBLE PRECISION)''')
        conn.commit()
        if db_is_postgres():
            db_execute(conn, "ALTER TABLE users ADD COLUMN IF NOT EXISTS lang TEXT DEFAULT NULL")
            db_execute(conn, "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen DOUBLE PRECISION DEFAULT 0")
            db_execute(conn, "ALTER TABLE pending_captcha ADD COLUMN IF NOT EXISTS token TEXT DEFAULT NULL")
            conn.commit()
        else:
            try: db_execute(conn, "ALTER TABLE users ADD COLUMN lang TEXT DEFAULT NULL")
            except Exception: conn.rollback()
            try: db_execute(conn, "ALTER TABLE users ADD COLUMN last_seen DOUBLE PRECISION DEFAULT 0")
            except Exception: conn.rollback()
            try: db_execute(conn, "ALTER TABLE pending_captcha ADD COLUMN token TEXT DEFAULT NULL")
            except Exception: conn.rollback()
            conn.commit()

def migrate_sqlite_to_postgres_once():
    if not db_is_postgres() or not MIGRATE_SQLITE_TO_POSTGRES or not os.path.exists(DB_PATH): return
    marker_key = 'bot:migration:sqlite_to_postgres_done'
    client = get_redis_client()
    if client and client.get(marker_key): return
    logging.info("Starting SQLite to PostgreSQL migration.")
    sqlite_conn = sqlite3.connect(DB_PATH)
    pg_conn = get_db_conn()
    try:
        with _db_lock:
            for table, cols in [
                ('users', ['user_id', 'verified', 'ban_until', 'lang', 'last_seen']),
                ('pending_captcha', ['user_id', 'answer', 'token', 'timestamp', 'retries']),
                ('message_map', ['msg_id', 'user_id', 'created_at']),
                ('whitelist', ['user_id', 'added_at']),
                ('blacklist', ['user_id', 'added_at']),
            ]:
                existing_cols = {row[1] for row in sqlite_conn.execute(f"PRAGMA table_info({table})").fetchall()}
                if not existing_cols:
                    continue
                select_cols = [c for c in cols if c in existing_cols]
                if not select_cols:
                    continue
                rows = sqlite_conn.execute(f"SELECT {', '.join(select_cols)} FROM {table}").fetchall()
                if not rows: continue
                placeholders = ', '.join(['?'] * len(cols))
                updates = ', '.join([f"{c}=EXCLUDED.{c}" for c in cols[1:]])
                conflict_col = cols[0]
                sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT ({conflict_col}) DO UPDATE SET {updates}"
                for row in rows:
                    values = dict(zip(select_cols, row))
                    db_execute(pg_conn, sql, tuple(values.get(c) for c in cols))
            pg_conn.commit()
        if client: client.set(marker_key, '1')
        logging.info("SQLite to PostgreSQL migration completed.")
    except Exception as e:
        pg_conn.rollback()
        logging.exception(f"SQLite to PostgreSQL migration failed: {e}")
    finally:
        sqlite_conn.close()

def db_touch_user(user_id):
    now = time.time()
    with _db_lock:
        conn = get_db_conn()
        cur = db_execute(conn, "SELECT last_seen FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if not row:
            db_insert_user_ignore(conn, user_id, now)
            conn.commit()
        elif not row[0] or now - row[0] > DB_TOUCH_INTERVAL:
            db_execute(conn, "UPDATE users SET last_seen=? WHERE user_id=?", (now, user_id))
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
        db_insert_user_ignore(conn, user_id, time.time())
        db_execute(conn, "UPDATE users SET lang=?, last_seen=? WHERE user_id=?", (lang, time.time(), user_id))
        conn.commit()
    invalidate_cache(user_id)

def db_get_full_user_status(user_id):
    with _db_lock:
        conn = get_db_conn()
        cur = db_execute(conn, "SELECT verified, ban_until, lang FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        verified, ban_until, lang = (0, 0, None)
        if row: verified, ban_until, lang = row
        else:
            db_insert_user_ignore(conn, user_id, time.time())
            conn.commit()
        cur = db_execute(conn, "SELECT 1 FROM whitelist WHERE user_id=?", (user_id,))
        is_wl = cur.fetchone() is not None
        cur = db_execute(conn, "SELECT 1 FROM blacklist WHERE user_id=?", (user_id,))
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
        cur = db_execute(conn, "SELECT timestamp FROM pending_captcha WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row and (time.time() - row[0] < CAPTCHA_TIMEOUT): return True
        if row:
            db_execute(conn, "DELETE FROM pending_captcha WHERE user_id=?", (user_id,))
            conn.commit()
        return False

def db_check_and_verify(user_id, input_ans=None, token=None):
    now = time.time()
    stat = get_cached_user_status(user_id)
    if stat['ban_until'] > now: return 'banned', stat['ban_until']
    if stat['verified'] == 1: return 'verified', 0
    with _db_lock:
        conn = get_db_conn()
        cur = db_execute(conn, "SELECT answer, token, timestamp, retries FROM pending_captcha WHERE user_id=?", (user_id,))
        cap_row = cur.fetchone()
        if not cap_row: return 'no_captcha', 0
        expected, expected_token, ts, retries = cap_row
        if now - ts > CAPTCHA_TIMEOUT:
            ban_until = now + random.randint(MIN_BAN_DURATION, MAX_BAN_DURATION)
            db_execute(conn, "UPDATE users SET verified=0, ban_until=? WHERE user_id=?", (ban_until, user_id))
            db_execute(conn, "DELETE FROM pending_captcha WHERE user_id=?", (user_id,))
            conn.commit()
            invalidate_cache(user_id)
            clear_captcha_prompt_state(user_id)
            return 'timeout_ban', ban_until
        if token is not None and expected_token and not secrets.compare_digest(str(token), str(expected_token)):
            return 'stale_captcha', 0
        token_ok = token and expected_token and secrets.compare_digest(str(token), str(expected_token))
        text_ok = CAPTCHA_TEXT_FALLBACK and input_ans is not None and str(input_ans).strip() == str(expected)
        if token_ok or text_ok:
            db_execute(conn, "UPDATE users SET verified=1, ban_until=0 WHERE user_id=?", (user_id,))
            db_execute(conn, "DELETE FROM pending_captcha WHERE user_id=?", (user_id,))
            conn.commit()
            invalidate_cache(user_id)
            clear_captcha_prompt_state(user_id)
            return 'success', 0
        else:
            new_retries = retries + 1
            if new_retries >= CAPTCHA_MAX_RETRIES:
                ban_until = now + random.randint(MIN_BAN_DURATION, MAX_BAN_DURATION)
                db_execute(conn, "UPDATE users SET verified=0, ban_until=? WHERE user_id=?", (ban_until, user_id))
                db_execute(conn, "DELETE FROM pending_captcha WHERE user_id=?", (user_id,))
                conn.commit()
                invalidate_cache(user_id)
                clear_captcha_prompt_state(user_id)
                return 'fail_ban', ban_until
            else:
                db_execute(conn, "UPDATE pending_captcha SET retries=? WHERE user_id=?", (new_retries, user_id))
                conn.commit()
                return 'wrong_answer', 0

def db_ban_user(user_id, duration):
    ban_until = time.time() + duration
    with _db_lock:
        conn = get_db_conn()
        db_insert_user_ignore(conn, user_id, time.time())
        db_execute(conn, "UPDATE users SET verified=0, ban_until=?, last_seen=? WHERE user_id=?", (ban_until, time.time(), user_id))
        db_execute(conn, "DELETE FROM pending_captcha WHERE user_id=?", (user_id,))
        conn.commit()
    invalidate_cache(user_id)
    clear_captcha_prompt_state(user_id)
    return ban_until

def db_unban_user(user_id):
    with _db_lock:
        conn = get_db_conn()
        db_execute(conn, "UPDATE users SET ban_until=0 WHERE user_id=?", (user_id,))
        conn.commit()
    invalidate_cache(user_id)

def db_save_captcha(user_id, answer, token):
    with _db_lock:
        conn = get_db_conn()
        db_upsert_captcha(conn, user_id, answer, token)
        conn.commit()

def db_save_map(msg_id, user_id):
    cleaned_info = None
    with _db_lock:
        conn = get_db_conn()
        db_upsert_map(conn, msg_id, user_id)
        conn.commit()
        
        if random.random() < 0.1:
            try:
                cur = db_execute(conn, "SELECT COUNT(*) FROM message_map")
                count = cur.fetchone()[0]
                if count > DB_MAX_ROWS:
                    limit_cnt = count - DB_MAX_ROWS
                    db_execute(conn, f"DELETE FROM message_map WHERE msg_id IN (SELECT msg_id FROM message_map ORDER BY created_at ASC LIMIT {limit_cnt})")
                    cleaned_info = f"🗑️ 数据库清理: 自动覆盖了 {limit_cnt} 条旧消息记录。"
                    conn.commit()

                if not db_is_postgres() and os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > (DB_SIZE_LIMIT_MB * 1024 * 1024):
                    db_execute(conn, "VACUUM")
                    cleaned_info = "🧹 数据库清理: 文件过大，已执行 VACUUM 压缩。"
            except Exception as e:
                logging.exception(f"DB Cleanup Error: {e}")

    if cleaned_info:
        try: safe_send(bot.send_message, ADMIN_ID, cleaned_info)
        except Exception as e: logging.warning(f"DB cleanup notice failed: {e}")

def db_get_map(msg_id):
    with _db_lock:
        conn = get_db_conn()
        cur = db_execute(conn, "SELECT user_id FROM message_map WHERE msg_id=?", (msg_id,))
        row = cur.fetchone()
        return row[0] if row else None

def db_cleanup_map():
    limit_time = time.time() - (86400 * DB_RETENTION_DAYS)
    with _db_lock:
        conn = get_db_conn()
        db_execute(conn, "DELETE FROM message_map WHERE created_at < ?", (limit_time,))
        db_execute(conn, "DELETE FROM pending_captcha WHERE timestamp < ?", (time.time() - CAPTCHA_TIMEOUT * 2,))
        db_execute(conn, "DELETE FROM users WHERE verified=0 AND ban_until < ? AND last_seen > 0 AND last_seen < ? AND user_id NOT IN (SELECT user_id FROM whitelist) AND user_id NOT IN (SELECT user_id FROM blacklist)",
                     (time.time(), time.time() - 86400 * DB_RETENTION_DAYS))
        conn.commit()

def db_add_to_list(table_name, user_id):
    if table_name not in ('whitelist', 'blacklist'): return False
    with _db_lock:
        conn = get_db_conn()
        try:
            if db_is_postgres():
                db_execute(conn, f"INSERT INTO {table_name} (user_id, added_at) VALUES (?, ?) ON CONFLICT (user_id) DO UPDATE SET added_at=EXCLUDED.added_at", (user_id, time.time()))
            else:
                db_execute(conn, f"INSERT OR REPLACE INTO {table_name} (user_id, added_at) VALUES (?, ?)", (user_id, time.time()))
            conn.commit()
            success = True
        except Exception:
            conn.rollback()
            success = False
    if success: invalidate_cache(user_id)
    return success

def db_remove_from_list(table_name, user_id):
    if table_name not in ('whitelist', 'blacklist'): return False
    with _db_lock:
        conn = get_db_conn()
        cur = db_execute(conn, f"DELETE FROM {table_name} WHERE user_id=?", (user_id,))
        conn.commit()
        success = cur.rowcount > 0
    if success: invalidate_cache(user_id)
    return success

def db_get_list(table_name):
    if table_name not in ('whitelist', 'blacklist'): return []
    with _db_lock:
        conn = get_db_conn()
        cur = db_execute(conn, f"SELECT user_id, added_at FROM {table_name} ORDER BY added_at DESC")
        return cur.fetchall()

def split_text(text, limit=TELEGRAM_TEXT_LIMIT):
    text = text or ""
    if len(text) <= limit: return [text]
    chunks = []
    while text:
        chunk = text[:limit]
        cut = max(chunk.rfind('\n'), chunk.rfind(' '))
        if cut > limit * 0.6: chunk = text[:cut]
        chunks.append(chunk)
        text = text[len(chunk):].lstrip('\n ')
    return chunks

def trim_caption(caption, suffix="", escape_html=False):
    caption = caption or ""
    suffix = suffix or ""
    available = TELEGRAM_CAPTION_LIMIT - len(suffix)
    if available <= 0: return suffix[-TELEGRAM_CAPTION_LIMIT:]
    if escape_html:
        escaped = html.escape(caption)
        if len(escaped) <= available: return escaped + suffix
        marker = "..."
        low, high = 0, len(caption)
        best = ""
        while low <= high:
            mid = (low + high) // 2
            candidate = html.escape(caption[:mid]) + marker
            if len(candidate) <= available:
                best = candidate
                low = mid + 1
            else:
                high = mid - 1
        return best + suffix
    if len(caption) > available:
        caption = caption[:max(0, available - 3)] + "..."
    return caption + suffix

def split_html_text_with_suffix(text, suffix, limit=TELEGRAM_TEXT_LIMIT):
    text = text or ""
    suffix = suffix or ""
    available = limit - len(suffix)
    if available <= 0: return [suffix[-limit:]]
    chunks = []
    while text:
        low, high = 1, len(text)
        best_len = 1
        while low <= high:
            mid = (low + high) // 2
            if len(html.escape(text[:mid])) <= available:
                best_len = mid
                low = mid + 1
            else:
                high = mid - 1
        cut = best_len
        if best_len < len(text):
            candidate = text[:best_len]
            soft_cut = max(candidate.rfind('\n'), candidate.rfind(' '))
            if soft_cut > best_len * 0.6: cut = soft_cut
        chunk = text[:cut]
        chunks.append(html.escape(chunk) + suffix)
        text = text[cut:].lstrip('\n ')
    return chunks or [suffix]

def limit_chunks(chunks, max_parts=MAX_FORWARD_TEXT_PARTS):
    if len(chunks) <= max_parts: return chunks
    notice = html.escape(f"\n\n[消息过长，仅转发前 {max_parts} 段，剩余内容已截断]")
    chunks = chunks[:max_parts]
    chunks[-1] = chunks[-1][:max(0, TELEGRAM_TEXT_LIMIT - len(notice))] + notice
    return chunks

def send_long_message(chat_id, text, **kwargs):
    sent = None
    for part in split_text(text):
        sent = safe_send(bot.send_message, chat_id, part, **kwargs)
    return sent

def safe_reply_to(message, text, **kwargs):
    sent = None
    for part in split_text(text):
        sent = safe_send(bot.reply_to, message, part, **kwargs)
    return sent

def safe_requests_get(url):
    try:
        r = requests.get(url, timeout=10, stream=True)
        if r.status_code != 200: return None
        content = b''
        for chunk in r.iter_content(4096):
            content += chunk
            if len(content) > REMOTE_MAX_CONTENT_BYTES: break
        return content.decode(errors='ignore')
    except Exception as e:
        logging.warning(f"Remote rules download failed: {e}")
        return None

def normalize_text(s):
    if not s: return ''
    return unicodedata.normalize('NFKC', s).lower().strip()

def normalize_for_spam(s):
    text = normalize_text(s).translate(CONFUSABLE_TRANS)
    return re.sub(r'[\s\u200b\u200c\u200d\ufe0f\W_]+', '', text)

def normalize_lang(lang):
    return lang if lang in ('zh', 'en') else 'zh'

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
            if new_regex:
                with _spam_lock:
                    spam_regex_pattern = new_regex
                logging.info(f"Rules Updated: {len(all_keywords)}")
            else:
                logging.warning("Spam rules build returned empty regex; keeping previous rules.")
        except Exception as e: logging.warning(f"Spam rules update failed: {e}")
        time.sleep(SPAM_UPDATE_INTERVAL)

def cleanup_dict():
    global _last_db_cleanup
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
        with _flood_lock:
            to_del_prompt = [uid for uid, v in captcha_prompt_state.items() if now - v.get('first', now) > UNVERIFIED_WINDOW and v.get('silent_until', 0) < now]
            for uid in to_del_prompt: del captcha_prompt_state[uid]
        if now - _last_db_cleanup > DB_CLEANUP_INTERVAL:
            db_cleanup_map()
            _last_db_cleanup = now

def check_global_limit():
    global _global_token_bucket, _last_token_update
    allowed = redis_rate_limit('bot:rate:inbound:1s', GLOBAL_MESSAGE_LIMIT, 1)
    if allowed is not None: return allowed
    with _global_limit_lock:
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
    if media_group_id:
        added = redis_set_once(f'bot:media_group:{media_group_id}', int(now), 5)
        if added is False: return False
    allowed = redis_rate_limit(f'bot:flood:{user_id}:{FLOOD_WINDOW}', MAX_MSGS_PER_WINDOW, FLOOD_WINDOW)
    if allowed is not None: return not allowed
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

def should_send_captcha_prompt(user_id):
    now = time.time()
    client = get_redis_client()
    if client:
        try:
            silent_key = f'bot:captcha:silent:{user_id}'
            if client.exists(silent_key): return False
            cool_key = f'bot:captcha:cool:{user_id}'
            if not client.set(cool_key, '1', nx=True, ex=CAPTCHA_PROMPT_COOLDOWN): return False
            count_key = f'bot:captcha:count:{user_id}'
            count = client.incr(count_key)
            if count == 1: client.expire(count_key, UNVERIFIED_WINDOW)
            if count > UNVERIFIED_MAX_PROMPTS:
                client.setex(silent_key, UNVERIFIED_SILENCE_TIME, '1')
                return False
            return True
        except Exception as e:
            logging.warning(f"Redis captcha state failed for {user_id}: {e}")
    with _flood_lock:
        state = captcha_prompt_state.get(user_id, {'first': now, 'last': 0, 'count': 0, 'silent_until': 0})
        if state.get('silent_until', 0) > now:
            captcha_prompt_state[user_id] = state
            return False
        if now - state.get('first', now) > UNVERIFIED_WINDOW:
            state = {'first': now, 'last': 0, 'count': 0, 'silent_until': 0}
        if now - state.get('last', 0) < CAPTCHA_PROMPT_COOLDOWN:
            captcha_prompt_state[user_id] = state
            return False
        state['last'] = now
        state['count'] = state.get('count', 0) + 1
        if state['count'] > UNVERIFIED_MAX_PROMPTS:
            state['silent_until'] = now + UNVERIFIED_SILENCE_TIME
            captcha_prompt_state[user_id] = state
            return False
        captcha_prompt_state[user_id] = state
        return True

def clear_captcha_prompt_state(user_id):
    redis_delete(f'bot:captcha:silent:{user_id}')
    redis_delete(f'bot:captcha:cool:{user_id}')
    redis_delete(f'bot:captcha:count:{user_id}')
    with _flood_lock:
        captcha_prompt_state.pop(user_id, None)

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

def spam_risk_score(text):
    if not text: return 0
    raw = normalize_text(text)
    compact = normalize_for_spam(raw)
    score = 0
    if re.search(r'https?://|t\.me/|telegram\.me/|www\.|\.com\b|\.net\b|\.org\b', raw): score += 3
    if re.search(r'@[a-zA-Z0-9_]{5,}', raw): score += 2
    if re.search(r'\+?\d[\d\s\-()]{7,}\d', raw): score += 2
    if re.search(r'(微信|威信|薇信|vx|v信|qq|飞机|电报|tg|telegram)', raw): score += 2
    if re.search(r'(usdt|trc20|erc20|充值|提现|收款|付款|钱包|交易所)', compact): score += 3
    term_hits = sum(1 for term in SPAM_MARKETING_TERMS if normalize_for_spam(term) in compact)
    score += min(term_hits * 2, 8)
    if len(compact) > 80 and term_hits >= 2: score += 2
    if re.search(r'(.)\1{5,}', compact): score += 1
    if len(re.findall(r'[!！?？]{2,}', raw)) >= 2: score += 1
    return score

def check_deep_spam(message):
    content = getattr(message, 'text', None) or getattr(message, 'caption', None) or ""
    if is_spam_text(content): return True
    if spam_risk_score(content) >= 6: return True
    user = message.from_user
    if is_spam_text(getattr(user, 'first_name', None)): return True
    if is_spam_text(getattr(user, 'last_name', None)): return True
    if is_spam_text(getattr(user, 'username', None)): return True
    profile_text = " ".join([str(getattr(user, 'first_name', '') or ''), str(getattr(user, 'last_name', '') or ''), str(getattr(user, 'username', '') or '')])
    if spam_risk_score(profile_text) >= 5: return True
    document = getattr(message, 'document', None)
    if document and hasattr(document, 'file_name'):
        if is_spam_text(document.file_name): return True
        if spam_risk_score(document.file_name) >= 5: return True
    return False

def inject_noise(text):
    res = ""
    for char in text:
        res += char
        if random.random() < 0.3: res += '\u200b'
    return res

def get_text(key, user_id, **kwargs):
    stat = get_cached_user_status(user_id)
    lang = normalize_lang(stat['lang'])
    txt = STRINGS.get(key, {}).get(lang, STRINGS.get(key, {}).get('zh', ''))
    if kwargs: return txt.format(**kwargs)
    return txt

def send_menu(user_id, text=None):
    stat = get_cached_user_status(user_id)
    lang = normalize_lang(stat['lang'])
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton(STRINGS['menu_contact'][lang]), KeyboardButton(STRINGS['menu_help'][lang]), KeyboardButton(STRINGS['menu_lang'][lang]))
    msg = text if text else (WELCOME_ZH if lang == 'zh' else WELCOME_EN)
    try:
        m = safe_send(bot.send_message, user_id, msg, reply_markup=markup)
        deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
    except Exception as e: logging.warning(f"Send menu failed for {user_id}: {e}")

def ask_language(chat_id):
    if not should_send_captcha_prompt(chat_id): return
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🇨🇳 中文", callback_data="set_lang:zh"), InlineKeyboardButton("🇺🇸 English", callback_data="set_lang:en"))
    try:
        m = safe_send(bot.send_message, chat_id, STRINGS['select_lang']['zh'], reply_markup=markup)
        deleter.schedule(chat_id, m.message_id, MSG_AUTO_DELETE_DELAY)
    except Exception as e: logging.warning(f"Ask language failed for {chat_id}: {e}")

def build_captcha_question(lang):
    mode = random.choice(['add3', 'mix', 'mul'])
    if mode == 'mul':
        n1 = random.randint(2, 9)
        n2 = random.randint(2, 9)
        ans = n1 * n2
        q_raw = f"{n1} × {n2}"
    elif mode == 'mix':
        n1 = random.randint(5, 18)
        n2 = random.randint(1, 9)
        n3 = random.randint(1, 9)
        ans = n1 + n2 - n3
        q_raw = f"{n1} + {n2} - {n3}"
    else:
        n1 = random.randint(1, 20)
        n2 = random.randint(1, 20)
        n3 = random.randint(1, 9)
        ans = n1 + n2 + n3
        n1_s = CN_NUM_MAP.get(str(n1), str(n1)) if lang == 'zh' and n1 <= 10 else str(n1)
        q_raw = f"{n1_s} + {n2} + {n3}" if lang == 'zh' else f"{n1} + {n2} + {n3}"
    return q_raw, ans

def build_captcha_markup(answer, token):
    options = {answer}
    while len(options) < 4:
        options.add(max(0, answer + random.randint(-9, 9)))
    options = list(options)
    random.shuffle(options)
    markup = InlineKeyboardMarkup()
    buttons = [InlineKeyboardButton(str(opt), callback_data=f"captcha:{token}:{opt}") for opt in options]
    markup.row(buttons[0], buttons[1])
    markup.row(buttons[2], buttons[3])
    return markup

def generate_captcha(user_id):
    if db_check_captcha_exists(user_id): return get_text('wait_verify', user_id), None
    stat = get_cached_user_status(user_id)
    lang = normalize_lang(stat['lang'])
    q_raw, ans = build_captcha_question(lang)
    q_noise = inject_noise(q_raw)
    token = secrets.token_urlsafe(8)
    db_save_captcha(user_id, str(ans), token)
    return get_text('captcha_ask', user_id, q=q_noise), build_captcha_markup(ans, token)

def get_help_message(is_admin, user_id):
    stat = get_cached_user_status(user_id)
    lang = normalize_lang(stat['lang'])
    help_msg = "📚 <b>机器人指令帮助</b>\n\n👉 <b>用户指令</b>\n• <code>/start</code> / <code>/help</code>: 打开菜单\n"
    if is_admin:
        help_msg += "\n👑 <b>管理员指令 (Admin)</b>\n• 回复消息 <code>/ban</code>: 封禁\n• 回复消息 <code>/unban</code>: 解封\n• 回复消息 <code>/awl</code>: 加白名单\n• 回复消息 <code>/abl</code>: 加黑名单\n• <code>/gb &lt;内容&gt;</code>: 广播\n• <code>/awl &lt;ID&gt;</code>: ID加白\n• <code>/vlist wl</code>: 看白名单"
    return help_msg

def broadcast_thread(text):
    with _db_lock:
        conn = get_db_conn()
        cursor = db_execute(conn, "SELECT user_id FROM users")
        all_users = cursor.fetchall()
    success_count, fail_count = 0, 0
    for row in all_users:
        try:
            send_long_message(row[0], text)
            success_count += 1
            time.sleep(0.05)
        except Exception as e:
            fail_count += 1
            logging.warning(f"Broadcast failed for {row[0]}: {e}")
    try: send_long_message(ADMIN_ID, f"📢 广播结束\n✅: {success_count}\n❌: {fail_count}")
    except Exception as e: logging.warning(f"Broadcast summary failed: {e}")

@bot.message_handler(commands=['gb'])
def handle_broadcast_command(message):
    if message.from_user.id != ADMIN_ID: return
    msg_text = message.text.replace('/gb', '').strip()
    if not msg_text: return
    safe_reply_to(message, "🚀 广播开始...")
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
            if db_add_to_list(list_name, target_uid): safe_reply_to(message, f"✅ ID {target_uid} 已加入 {list_name}。")
        else:
            if db_remove_from_list(list_name, target_uid): safe_reply_to(message, f"✅ ID {target_uid} 已移出 {list_name}。")
    elif cmd == 'vlist':
        list_name = 'whitelist' if (len(parts) > 1 and parts[1] == 'wl') else 'blacklist'
        data = db_get_list(list_name)
        msg = f"📋 {list_name} ({len(data)}):\n" + "\n".join([f"• {u[0]}" for u in data[:50]])
        safe_reply_to(message, msg)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_lang:'))
def handle_language_callback(call):
    lang = call.data.split(':', 1)[1]
    if lang not in ('zh', 'en'):
        try: safe_send(bot.answer_callback_query, call.id, "Invalid language")
        except Exception as e: logging.warning(f"Invalid language callback failed: {e}")
        return
    db_set_lang(call.from_user.id, lang)
    clear_captcha_prompt_state(call.from_user.id)
    try:
        safe_send(bot.answer_callback_query, call.id, "OK")
        safe_send(bot.delete_message, call.message.chat.id, call.message.message_id)
        send_menu(call.from_user.id, get_text('lang_set', call.from_user.id))
    except Exception as e: logging.warning(f"Language callback failed for {call.from_user.id}: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('captcha:'))
def handle_captcha_callback(call):
    user_id = call.from_user.id
    parts = call.data.split(':', 2)
    if len(parts) != 3:
        try: safe_send(bot.answer_callback_query, call.id, "Invalid")
        except Exception as e: logging.warning(f"Invalid captcha callback answer failed: {e}")
        return
    _, token, answer = parts
    result, data = db_check_and_verify(user_id, answer, token)
    try:
        if result == 'success':
            safe_send(bot.answer_callback_query, call.id, "OK")
            try: safe_send(bot.delete_message, call.message.chat.id, call.message.message_id)
            except Exception as e: logging.debug(f"Captcha message delete failed: {e}")
            send_menu(user_id, VERIFIED_ZH if normalize_lang(get_cached_user_status(user_id).get('lang')) == 'zh' else VERIFIED_EN)
        elif result in ['timeout_ban', 'fail_ban']:
            key = 'captcha_timeout' if result == 'timeout_ban' else 'captcha_fail'
            safe_send(bot.answer_callback_query, call.id, get_text(key, user_id), show_alert=True)
        elif result == 'wrong_answer':
            safe_send(bot.answer_callback_query, call.id, get_text('captcha_wrong', user_id), show_alert=True)
        elif result == 'stale_captcha':
            safe_send(bot.answer_callback_query, call.id, get_text('captcha_stale', user_id), show_alert=True)
        else:
            safe_send(bot.answer_callback_query, call.id, get_text('wait_verify', user_id), show_alert=True)
    except Exception as e:
        logging.warning(f"Captcha callback handling failed for {user_id}: {e}")

@bot.message_handler(commands=['start', 'help'])
def send_welcome_handler(message):
    user_id = message.from_user.id
    db_touch_user(user_id)
    user_status = get_cached_user_status(user_id)
    if user_status['bl']: return
    deleter.schedule(user_id, message.message_id, MSG_AUTO_DELETE_DELAY)
    if user_id != ADMIN_ID and check_flood(user_id):
        db_ban_user(user_id, FLOOD_PENALTY_TIME)
        return
    if message.text == '/help':
        m = send_long_message(user_id, get_help_message(user_id==ADMIN_ID, user_id), parse_mode='HTML')
        deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
        send_menu(user_id)
    elif message.text == '/start':
        if user_status.get('lang'):
            send_menu(user_id)
        else: ask_language(user_id)

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
            safe_send(bot.delete_message, message.chat.id, message.message_id)
            m = safe_send(bot.send_message, user_id, get_text('spam_edit_ban', user_id), parse_mode='HTML')
            deleter.schedule(user_id, m.message_id, 30)
            alert_msg = f"⚠️ <b>检测到违规编辑</b>\n用户: {user_id}\n操作: 已封禁并删除消息。"
            safe_send(bot.send_message, ADMIN_ID, alert_msg, parse_mode='HTML')
        except Exception as e: logging.warning(f"Edited spam handling failed for {user_id}: {e}")

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id != ADMIN_ID, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation', 'video_note', 'location', 'contact', 'dice'])
def handle_incoming(message):
    if not check_global_limit(): return
    user_id = message.from_user.id
    db_touch_user(user_id)
    user_status = get_cached_user_status(user_id)
    if user_status['bl']:
        try:
            m = safe_send(bot.send_message, user_id, get_text('blacklist_ban', user_id), parse_mode='HTML')
            deleter.schedule(user_id, message.message_id, 1)
            deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
        except Exception as e: logging.warning(f"Blacklist notice failed for {user_id}: {e}")
        return

    is_whitelisted = user_status['wl']

    if not is_whitelisted:
        if check_flood(user_id, getattr(message, 'media_group_id', None)):
            db_ban_user(user_id, FLOOD_PENALTY_TIME)
            m = safe_send(bot.send_message, user_id, get_text('flood_ban', user_id))
            deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
            deleter.schedule(user_id, message.message_id, MSG_AUTO_DELETE_DELAY)
            return

        if check_deep_spam(message):
            db_ban_user(user_id, MAX_BAN_DURATION)
            m = safe_send(bot.send_message, user_id, get_text('spam_ban', user_id))
            deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
            deleter.schedule(user_id, message.message_id, MSG_AUTO_DELETE_DELAY)
            return
        
        if message.content_type == 'text' and CAPTCHA_TEXT_FALLBACK:
            result, data = db_check_and_verify(user_id, message.text.strip())
            if result == 'banned': return
            elif result in ['timeout_ban', 'fail_ban', 'wrong_answer']:
                key = 'captcha_timeout' if result == 'timeout_ban' else ('captcha_fail' if result == 'fail_ban' else 'captcha_wrong')
                m = safe_send(bot.send_message, user_id, get_text(key, user_id))
                deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
                deleter.schedule(user_id, message.message_id, 1)
                return
            elif result == 'success':
                deleter.schedule(user_id, message.message_id, 1)
                send_menu(user_id, VERIFIED_ZH if normalize_lang(user_status.get('lang')) == 'zh' else VERIFIED_EN)
                return

        if user_status['ban_until'] > time.time(): return
        
        if not user_status['verified']:
            deleter.schedule(user_id, message.message_id, MSG_AUTO_DELETE_DELAY)
            if should_send_captcha_prompt(user_id):
                q, markup = generate_captcha(user_id)
                m = safe_send(bot.send_message, user_id, q, parse_mode='HTML', reply_markup=markup)
                deleter.schedule(user_id, m.message_id, CAPTCHA_DELETE_DELAY)
            return

    lang = normalize_lang(user_status.get('lang'))
    if message.content_type == 'text':
        if message.text in [STRINGS['menu_contact'][lang], STRINGS['menu_help'][lang], STRINGS['menu_lang'][lang]]:
            if message.text == STRINGS['menu_lang'][lang]: ask_language(user_id)
            elif message.text == STRINGS['menu_help'][lang]: 
                m = safe_send(bot.send_message, user_id, "💡 FAQ / 常见问题:\n1. 消息直接发送。\n2. 违规自动封禁。")
                deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
            else: 
                m = safe_send(bot.send_message, user_id, WELCOME_ZH if lang == 'zh' else WELCOME_EN)
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
        m = safe_send(bot.send_message, user_id, get_text('file_too_large', user_id))
        deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
        deleter.schedule(user_id, message.message_id, MSG_AUTO_DELETE_DELAY)
        return

    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    full_name = (first_name + " " + last_name).strip() or "User"
    safe_name = html.escape(full_name)
    
    username = message.from_user.username
    uname_line = f"🔗 @{username}" if username else "🔗 No Username"
    lang_code = normalize_lang(user_status.get('lang'))
    
    user_info = f"\n\n👤 <a href='tg://user?id={user_id}'>{safe_name}</a>\n{uname_line}\n🆔 <code>{user_id}</code> [Lang: {lang_code}]" + (" 🟢" if is_whitelisted else "")
    caption_info = user_info
    
    def send_wrapper():
        try:
            sent = None
            if message.content_type == 'text':
                for part in limit_chunks(split_html_text_with_suffix(message.text, user_info)):
                    sent = safe_send(bot.send_message, ADMIN_ID, part, parse_mode='HTML')
                    db_save_map(sent.message_id, user_id)
                return
            elif message.content_type == 'photo':
                sent = safe_send(bot.send_photo, ADMIN_ID, message.photo[-1].file_id, caption=trim_caption(message.caption or "", caption_info, escape_html=True), parse_mode='HTML')
            elif message.content_type == 'video':
                sent = safe_send(bot.send_video, ADMIN_ID, message.video.file_id, caption=trim_caption(message.caption or "", caption_info, escape_html=True), parse_mode='HTML')
            elif message.content_type == 'animation':
                sent = safe_send(bot.send_animation, ADMIN_ID, message.animation.file_id, caption=trim_caption(message.caption or "", caption_info, escape_html=True), parse_mode='HTML')
            elif message.content_type == 'audio':
                sent = safe_send(bot.send_audio, ADMIN_ID, message.audio.file_id, caption=trim_caption(message.caption or "", caption_info, escape_html=True), parse_mode='HTML')
            elif message.content_type == 'document':
                sent = safe_send(bot.send_document, ADMIN_ID, message.document.file_id, caption=trim_caption(message.caption or "", caption_info, escape_html=True), parse_mode='HTML')
            elif message.content_type == 'sticker':
                safe_send(bot.send_sticker, ADMIN_ID, message.sticker.file_id)
                sent = send_long_message(ADMIN_ID, user_info, parse_mode='HTML')
            elif message.content_type == 'voice':
                sent = safe_send(bot.send_voice, ADMIN_ID, message.voice.file_id, caption=user_info, parse_mode='HTML')
            elif message.content_type == 'video_note':
                safe_send(bot.send_video_note, ADMIN_ID, message.video_note.file_id)
                sent = send_long_message(ADMIN_ID, user_info, parse_mode='HTML')
            elif message.content_type == 'location':
                safe_send(bot.send_location, ADMIN_ID, message.location.latitude, message.location.longitude)
                sent = send_long_message(ADMIN_ID, user_info, parse_mode='HTML')
            elif message.content_type == 'contact':
                safe_send(bot.send_contact, ADMIN_ID, phone_number=message.contact.phone_number, first_name=message.contact.first_name)
                sent = send_long_message(ADMIN_ID, user_info, parse_mode='HTML')
            elif message.content_type == 'dice':
                safe_send(bot.send_dice, ADMIN_ID, emoji=message.dice.emoji)
                sent = send_long_message(ADMIN_ID, user_info, parse_mode='HTML')
            
            if sent: db_save_map(sent.message_id, user_id)
        except Exception as e: logging.exception(f"Fwd Error: {e}")

    admin_sender.send(send_wrapper)
    
    if not getattr(message, 'media_group_id', None):
        m = safe_send(bot.send_message, user_id, AUTO_REPLY_ZH if lang == 'zh' else AUTO_REPLY_EN)
        deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)

@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.reply_to_message, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation', 'video_note', 'location', 'contact', 'dice'])
def handle_admin_reply(message):
    target_uid = db_get_map(message.reply_to_message.message_id)
    if not target_uid:
        try: 
            m = safe_reply_to(message, "⚠️ 消息太久远，已无法回复 (ID丢失)。")
            deleter.schedule(ADMIN_ID, m.message_id, 5)
        except Exception as e: logging.warning(f"Missing target notice failed: {e}")
        return

    if message.text and message.text.startswith('/'):
        cmd = message.text.split()[0].lower()
        if cmd == '/ban':
            db_ban_user(target_uid, 86400 * 30)
            safe_reply_to(message, f"✅ 已封禁 {target_uid}")
            return
        elif cmd == '/unban':
            db_unban_user(target_uid)
            safe_reply_to(message, f"✅ 已解封 {target_uid}")
            return
        elif cmd == '/awl':
            db_add_to_list('whitelist', target_uid)
            safe_reply_to(message, f"✅ 已白名单 {target_uid}")
            return
        elif cmd == '/abl':
            db_add_to_list('blacklist', target_uid)
            safe_reply_to(message, f"✅ 已黑名单 {target_uid}")
            return

    try:
        if message.content_type == 'text': send_long_message(target_uid, message.text)
        elif message.content_type == 'photo': safe_send(bot.send_photo, target_uid, message.photo[-1].file_id, caption=trim_caption(message.caption))
        elif message.content_type == 'sticker': safe_send(bot.send_sticker, target_uid, message.sticker.file_id)
        elif message.content_type == 'video': safe_send(bot.send_video, target_uid, message.video.file_id, caption=trim_caption(message.caption))
        elif message.content_type == 'animation': safe_send(bot.send_animation, target_uid, message.animation.file_id, caption=trim_caption(message.caption))
        elif message.content_type == 'audio': safe_send(bot.send_audio, target_uid, message.audio.file_id, caption=trim_caption(message.caption))
        elif message.content_type == 'voice': safe_send(bot.send_voice, target_uid, message.voice.file_id)
        elif message.content_type == 'document': safe_send(bot.send_document, target_uid, message.document.file_id, caption=trim_caption(message.caption))
        elif message.content_type == 'video_note': safe_send(bot.send_video_note, target_uid, message.video_note.file_id)
        elif message.content_type == 'location': safe_send(bot.send_location, target_uid, message.location.latitude, message.location.longitude)
        elif message.content_type == 'contact': safe_send(bot.send_contact, target_uid, phone_number=message.contact.phone_number, first_name=message.contact.first_name)
        elif message.content_type == 'dice': safe_send(bot.send_dice, target_uid, emoji=message.dice.emoji)
        m = safe_reply_to(message, "✅ 已发送")
        deleter.schedule(ADMIN_ID, m.message_id, 5)
    except Exception as e:
        logging.exception(f"Admin reply failed for {target_uid}: {e}")
        try:
            m = safe_reply_to(message, "❌ 发送失败 (用户可能屏蔽了机器人)")
            deleter.schedule(ADMIN_ID, m.message_id, 5)
        except Exception as notice_error:
            logging.warning(f"Admin failure notice failed: {notice_error}")

if __name__ == "__main__":
    init_db()
    migrate_sqlite_to_postgres_once()
    threading.Thread(target=update_spam_rules, daemon=True).start()
    threading.Thread(target=cleanup_dict, daemon=True).start()
    logging.info("Bot Started.")
    while True:
        try: bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            logging.exception(f"Polling crashed, restarting in 5s: {e}")
            time.sleep(5)
