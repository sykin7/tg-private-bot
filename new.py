# -*- coding: utf-8 -*-
import telebot
from telebot import apihelper
from telebot.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonCommands,
    ReplyKeyboardMarkup,
)
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
import hashlib
import json
from collections import deque
from itertools import islice

from ai_classifier import (
    ai_classifier as ai_cls,
    AI_ALWAYS_CHECK,
    AI_MIN_SCORE,
    AI_PROFILE_CHECK,
)
from env_utils import env_int as _env_int

import rule_sync

from rule_sync import (
    extract_rule_terms,
    fetch_r2_rules,
    github_config_enabled,
    r2_config_enabled,
    r2_quota_status,
    sync_learned_rules,
    sync_r2_mirrors,
    sync_status,
)

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
    "u币", "u 币", "U币", "USDT", "泰达币", "虚拟币", "数字货币", "卖币", "买币", "换u",
    "出u", "收u", "卖u", "买u", "高价收u", "低价出u", "跑分", "博彩", "兼职", "刷单", "各行各业", "代开",
    "发票", "迷药", "枪支", "色情", "裸聊", "办证", "查询", "定位", "监听",
    "傻逼", "高价收"
]

SPAM_MARKETING_TERMS = [
    "代开", "发票", "办证", "兼职", "刷单", "博彩", "担保", "盘口", "上分", "下分", "跑分",
    "u币", "出u", "收u", "卖u", "买u", "usdt", "泰达币", "虚拟币", "数字货币", "高价", "返佣", "推广", "引流", "开户", "接单",
    "私聊", "加我", "联系", "客服", "代理", "项目", "赚钱", "变现", "裸聊", "约炮"
]

HARD_BLOCK_TERMS = [
    "u币", "u 币", "u幣", "u 幣", "U币", "U 币", "U幣", "U 幣",
    "出u", "出U", "收u", "收U", "卖u", "卖U", "買u", "買U", "买u", "买U", "换u", "换U", "換u", "換U",
    "高价收u", "高价收U", "高價收u", "高價收U", "低价出u", "低价出U", "低價出u", "低價出U",
    "usdt", "泰达币", "泰達幣", "虚拟币", "虛擬幣", "数字货币", "數字貨幣"
]

CONFUSABLE_TRANS = str.maketrans({
    '0': 'o', '1': 'l', '3': 'e', '4': 'a', '5': 's', '7': 't', '@': 'a', '$': 's', '|': 'l'
})

URL_RE = re.compile(r'https?://|t\.me/|telegram\.me/|www\.|\.com\b|\.net\b|\.org\b')
MENTION_RE = re.compile(r'@[a-zA-Z0-9_]{5,}')
PHONE_RE = re.compile(r'\+?\d[\d\s\-()]{7,}\d')
CONTACT_RE = re.compile(r'微信|威信|薇信|vx|v信|qq|飞机|电报|tg|telegram')
CRYPTO_RE = re.compile(r'usdt|trc20|erc20|充值|提现|收款|付款|钱包|交易所')
REPEAT_CHAR_RE = re.compile(r'(.)\1{5,}')
REPEATED_PUNCT_RE = re.compile(r'[!！?？]{2,}')

# 加权评分用信号：收款、诱导、正常聊天。用于组合加权与负权重对冲，治本降误封。
MONEY_RE = re.compile(r'收款|付款|返佣|佣金|提现|充值|结算|日结|月入|时薪|工资|流水|上岸')
LURE_RE = re.compile(r'兼职|刷单|加我|私聊|接单|代理|项目|赚钱|变现|包赢|稳赚|躺赚|名额|扫码|进群|加群|开户|上分|下分|盘口')
HAM_RE = re.compile(r'请问|怎么|为什么|谢谢|多谢|你好|您好|请教|麻烦|不好意思|抱歉|如何|可以吗|是吗|求助|请问一下')

DEFAULT_REMOTE_SPAM_URL = "https://raw.githubusercontent.com/sykin7/my-telegram-spam-rules/refs/heads/main/spam.txt"
REMOTE_SPAM_URL = os.environ.get('REMOTE_SPAM_URL') or DEFAULT_REMOTE_SPAM_URL
DB_PATH = os.environ.get('BOT_DB_PATH', '/app/data/bot_core.db')
FLOOD_WINDOW = 10
MAX_MSGS_PER_WINDOW = 6
GLOBAL_MESSAGE_LIMIT = 20
OUTBOUND_MESSAGE_LIMIT = 25
DELETE_MESSAGE_LIMIT = 2
FLOOD_PENALTY_TIME = 900
CAPTCHA_TIMEOUT = 30
CAPTCHA_PROMPT_COOLDOWN = 20
CAPTCHA_TEXT_FALLBACK = os.environ.get('CAPTCHA_TEXT_FALLBACK', 'false').lower() in ('1', 'true', 'yes', 'on')
UNVERIFIED_SILENCE_TIME = 300
UNVERIFIED_MAX_PROMPTS = 3
UNVERIFIED_WINDOW = 600
MIN_BAN_DURATION = 3600
MAX_BAN_DURATION = 10800
CAPTCHA_CALLBACK_LIMIT = 3
CAPTCHA_CALLBACK_WINDOW = 3
CAPTCHA_WRONG_LIMIT = 3
CAPTCHA_WRONG_WINDOW = 600
SPAM_UPDATE_INTERVAL = 3600
REMOTE_MAX_CONTENT_BYTES = 128 * 1024
RULE_REGEX_MAX_KEYWORDS = _env_int(os.environ.get('RULE_REGEX_MAX_KEYWORDS'), 20000)
RULE_REGEX_BATCH_SIZE = _env_int(os.environ.get('RULE_REGEX_BATCH_SIZE'), 2000)
RULE_EXACT_MAX_TERMS = _env_int(os.environ.get('RULE_EXACT_MAX_TERMS'), 200000)
RULE_LEARNED_MEMORY_LIMIT = _env_int(os.environ.get('RULE_LEARNED_MEMORY_LIMIT'), 50000)
AI_KEYWORDS_LIMIT = _env_int(os.environ.get('AI_KEYWORDS_LIMIT'), 200)
MAX_SPAM_KEYWORDS = RULE_REGEX_MAX_KEYWORDS
# 内容风险分达到该值即判为广告。默认 6，可用 SPAM_BLOCK_SCORE 调松紧。
SPAM_BLOCK_SCORE = max(1, _env_int(os.environ.get('SPAM_BLOCK_SCORE'), 6))
# 用户名/资料/文件名等短文本判广告的风险分门槛，默认 5。
SPAM_PROFILE_BLOCK_SCORE = max(1, _env_int(os.environ.get('SPAM_PROFILE_BLOCK_SCORE'), 5))
RULE_AUTO_LEARN_ENABLED = os.environ.get('RULE_AUTO_LEARN_ENABLED', 'true').lower() not in ('0', 'false', 'no', 'off')
RULE_AUTO_LEARN_THRESHOLD = max(2, _env_int(os.environ.get('RULE_AUTO_LEARN_THRESHOLD'), 3))
RULE_AUTO_LEARN_MAX_RULES = max(1000, _env_int(os.environ.get('RULE_AUTO_LEARN_MAX_RULES'), 200000))
RULE_AUTO_LEARN_RETENTION_DAYS = max(1, _env_int(os.environ.get('RULE_AUTO_LEARN_RETENTION_DAYS'), 30))
RULE_IGNORE_RETENTION_DAYS = max(1, _env_int(os.environ.get('RULE_IGNORE_RETENTION_DAYS'), 7))
MSG_AUTO_DELETE_DELAY = 10
CAPTCHA_DELETE_DELAY = 60
CACHE_TTL = 300
DB_TOUCH_INTERVAL = 3600
DB_CLEANUP_INTERVAL = 3600

DB_MAX_ROWS = 10000
DB_SIZE_LIMIT_MB = 10
DB_RETENTION_DAYS = 7
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024
DELETE_QUEUE_MAXSIZE = 5000
MAX_FORWARD_TEXT_PARTS = 10
AUTO_REPLY_COOLDOWN = 30

GROUP_ENABLED = os.environ.get('GROUP_ENABLED', 'true').lower() not in ('0', 'false', 'no', 'off')
GROUP_JOIN_APPROVE = os.environ.get('GROUP_JOIN_APPROVE', 'true').lower() in ('1', 'true', 'yes', 'on')
GROUP_AUTO_APPROVE = os.environ.get('GROUP_AUTO_APPROVE', 'true').lower() in ('1', 'true', 'yes', 'on')
GROUP_JOIN_REVIEW_TIMEOUT = _env_int(os.environ.get('GROUP_JOIN_REVIEW_TIMEOUT'), 600)
GROUP_JOIN_REQUIRED_CHANNEL = (os.environ.get('GROUP_JOIN_REQUIRED_CHANNEL') or '').strip().lstrip('@')
GROUP_BAN_ON_SPAM = os.environ.get('GROUP_BAN_ON_SPAM', 'true').lower() in ('1', 'true', 'yes', 'on')
GROUP_DELETE_SPAM = os.environ.get('GROUP_DELETE_SPAM', 'true').lower() in ('1', 'true', 'yes', 'on')
# 群内广告命中多少次警告后才永久封。默认 1（首次删消息+警告，再犯永久封）。
# 设为 0 表示首次命中即永久封（旧行为）。强特征词任何时候直接封，不吃警告。
GROUP_SPAM_WARN_LIMIT = _env_int(os.environ.get('GROUP_SPAM_WARN_LIMIT'), 1)
RULE_LEARN_ENABLED = os.environ.get('RULE_LEARN_ENABLED', 'true').lower() in ('1', 'true', 'yes', 'on')


def parse_id_list(value):
    """Parse a comma-separated integer ID list, allowing negative IDs."""
    result = set()
    for part in (value or '').split(','):
        part = part.strip()
        if part.lstrip('-').isdigit():
            result.add(int(part))
    return result


GROUP_IDS = parse_id_list(os.environ.get('GROUP_IDS'))
GROUP_ADMIN_IDS = parse_id_list(os.environ.get('GROUP_ADMIN_IDS'))
if not GROUP_ADMIN_IDS and ADMIN_ID is not None:
    GROUP_ADMIN_IDS.add(ADMIN_ID)


def group_enabled_for(chat_id):
    return bool(GROUP_ENABLED and chat_id and (not GROUP_IDS or chat_id in GROUP_IDS))


def is_group_admin(user_id):
    return bool(user_id and user_id in GROUP_ADMIN_IDS)


_group_admin_cache = {}
GROUP_ADMIN_CACHE_TTL = 60
_group_join_lock = threading.Lock()
group_join_pending = {}
_channel_member_cache = {}
CHANNEL_MEMBER_CACHE_TTL = 60
# 群内广告警告计数：{(chat_id, user_id): 命中次数}，用于首次警告、再犯永久封。
group_spam_warn_state = {}
_group_spam_warn_lock = threading.Lock()


def can_manage_group(user_id, chat_id):
    if not user_id or not chat_id:
        return False
    if user_id in GROUP_ADMIN_IDS:
        return True
    now = time.monotonic()
    cached = _group_admin_cache.get(chat_id)
    if cached and cached[0] > now:
        return user_id in cached[1]
    try:
        members = bot.get_chat_administrators(chat_id)
        admin_ids = set()
        for member in members or []:
            member_user = getattr(member, 'user', None)
            member_id = getattr(member_user, 'id', None)
            if member_id is not None and getattr(member, 'status', None) in ('creator', 'administrator'):
                admin_ids.add(member_id)
    except Exception as e:
        logging.warning(f"Get chat administrators failed for {chat_id}: {e}")
        return False
    _group_admin_cache[chat_id] = (now + GROUP_ADMIN_CACHE_TTL, frozenset(admin_ids))
    return user_id in admin_ids

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if not BOT_TOKEN or ADMIN_ID is None:
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
auto_reply_cache = {}
captcha_prompt_state = {}
captcha_callback_state = {}
captcha_wrong_state = {}
captcha_attempt_state = {}
_spam_regexes = []
_spam_exact_text_terms = set()
_spam_exact_compact_terms = set()
_current_spam_keywords = set()
SPAM_RULE_SOURCE = 'none'
SPAM_RULE_KEYWORD_COUNT = 0
SPAM_RULE_REMOTE_COUNT = 0
SPAM_RULE_UPDATED_AT = 0
SPAM_RULE_LAST_ERROR = ''
_remote_rules_admin_notified = False
_remote_rule_text = ''
_current_remote_keywords = set()
_learned_keywords = set()
_db_conn = None

_global_token_bucket = GLOBAL_MESSAGE_LIMIT
_last_token_update = time.time()
_outbound_token_bucket = OUTBOUND_MESSAGE_LIMIT
_last_outbound_token_update = time.time()
_delete_token_bucket = DELETE_MESSAGE_LIMIT
_last_delete_token_update = time.time()
_last_db_cleanup = 0

def should_send_auto_reply(user_id):
    now = time.time()
    with _cache_lock:
        state = auto_reply_cache.setdefault(user_id, {'ts': 0})
        if now - state.get('ts', 0) < AUTO_REPLY_COOLDOWN:
            return False
        state['ts'] = now
        return True

def check_outbound_limit():
    global _outbound_token_bucket, _last_outbound_token_update
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

def check_delete_limit():
    global _delete_token_bucket, _last_delete_token_update
    with _outbound_limit_lock:
        now = time.time()
        time_passed = now - _last_delete_token_update
        new_tokens = int(time_passed * DELETE_MESSAGE_LIMIT)
        if new_tokens > 0:
            _delete_token_bucket = min(DELETE_MESSAGE_LIMIT, _delete_token_bucket + new_tokens)
            _last_delete_token_update = now
        if _delete_token_bucket > 0:
            _delete_token_bucket -= 1
            return True
        return False

def safe_send(func, *args, **kwargs):
    last_error = None
    for _ in range(3):
        while not check_outbound_limit():
            time.sleep(0.05)
        try:
            return func(*args, **kwargs)
        except apihelper.ApiTelegramException as e:
            last_error = e
            retry_after = 0
            try:
                result = getattr(e, 'result_json', None) or {}
                retry_after = int(result.get('parameters', {}).get('retry_after', 0))
            except Exception:
                retry_after = 0
            if retry_after > 0:
                sleep_for = min(retry_after + 1, 60)
                logging.warning(f"Telegram rate limit hit; sleeping {sleep_for}s before retry.")
                time.sleep(sleep_for)
                continue
            raise
    if last_error:
        raise last_error

def safe_delete(chat_id, message_id):
    while not check_delete_limit():
        time.sleep(0.1)
    return safe_send(bot.delete_message, chat_id, message_id)

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
                    try: safe_delete(chat_id, message_id)
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
    'captcha_wrong': {'zh': "❌ 答案错误，本题已失效，20 秒后发送新验证码。", 'en': "❌ Wrong answer. This CAPTCHA is invalid now; a new one will be sent in 20 seconds."},
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
    'admin_menu_status': {'zh': "📊 机器人状态", 'en': "📊 Bot Status"},
    'admin_menu_reload_rules': {'zh': "🔄 重载广告规则", 'en': "🔄 Reload Rules"},
    'admin_menu_ban_list': {'zh': "🚫 封禁名单", 'en': "🚫 Ban List"},
    'admin_menu_wl': {'zh': "⚪ 白名单", 'en': "⚪ Whitelist"},
    'admin_menu_bl': {'zh': "⚫ 黑名单", 'en': "⚫ Blacklist"},
    'admin_menu_unban': {'zh': "✅ 解除封禁", 'en': "✅ Unban User"},
    'admin_menu_awl': {'zh': "➕ 加白名单", 'en': "➕ Add Whitelist"},
    'admin_menu_dwl': {'zh': "➖ 移出白名单", 'en': "➖ Remove Whitelist"},
    'admin_menu_abl': {'zh': "⛔ 加黑名单", 'en': "⛔ Add Blacklist"},
    'admin_menu_dbl': {'zh': "♻️ 移出黑名单", 'en': "♻️ Remove Blacklist"},
    'admin_menu_resetverify': {'zh': "🧹 清空验证", 'en': "🧹 Reset Verification"},
    'admin_menu_broadcast': {'zh': "📣 群发广播", 'en': "📣 Broadcast"},
    'admin_menu_spamtest': {'zh': "🧪 广告测试", 'en': "🧪 Spam Test"},
    'admin_menu_id': {'zh': "🆔 查看ID", 'en': "🆔 Show ID"},
    'blacklist_ban': {'zh': "🚫 <b>您已被管理员列入黑名单，所有消息将被忽略。</b>", 'en': "🚫 <b>You have been blacklisted by the admin.</b>"},
    'file_too_large': {'zh': "⚠️ 文件过大 (超过50MB)，无法发送。", 'en': "⚠️ File too large (over 50MB)."}
}

STRINGS.update({
    'select_lang': {'zh': "🌐 请选择您的语言 / Please select your language:", 'en': "🌐 Please select your language / 请选择您的语言:"},
    'lang_set': {'zh': "✅ 语言已设置为中文。", 'en': "✅ Language set to English."},
    'menu_contact': {'zh': "📨 联系管理员", 'en': "📨 Contact Admin"},
    'menu_lang': {'zh': "🌐 切换语言", 'en': "🌐 Change Language"},
    'menu_help': {'zh': "❓ 常见问题", 'en': "❓ FAQ"},
    'admin_menu_status': {'zh': "📊 机器人状态", 'en': "📊 Bot Status"},
    'admin_menu_reload_rules': {'zh': "🔄 重载广告规则", 'en': "🔄 Reload Rules"},
    'admin_menu_ban_list': {'zh': "🚫 封禁名单", 'en': "🚫 Ban List"},
    'admin_menu_wl': {'zh': "⚪ 白名单", 'en': "⚪ Whitelist"},
    'admin_menu_bl': {'zh': "⚫ 黑名单", 'en': "⚫ Blacklist"},
})

def get_db_conn():
    global _db_conn
    if _db_conn is None:
        try:
            db_dir = os.path.dirname(DB_PATH)
            if db_dir and not os.path.exists(db_dir): os.makedirs(db_dir, exist_ok=True)
        except Exception as e: logging.warning(f"Ensure DB directory failed: {e}")
        _db_conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
        _db_conn.execute("PRAGMA journal_mode=WAL")
    return _db_conn

def db_execute(conn, sql, params=()):
    return conn.execute(sql, params)

def db_insert_user_ignore(conn, user_id, last_seen=None):
    last_seen = time.time() if last_seen is None else last_seen
    db_execute(conn, "INSERT OR IGNORE INTO users (user_id, last_seen) VALUES (?, ?)", (user_id, last_seen))

def db_upsert_captcha(conn, user_id, answer, token):
    db_execute(conn, "INSERT OR REPLACE INTO pending_captcha (user_id, answer, token, timestamp, retries) VALUES (?, ?, ?, ?, 0)", (user_id, answer, token, time.time()))

def db_upsert_map(conn, msg_id, user_id):
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
        db_execute(conn, '''CREATE TABLE IF NOT EXISTS group_bans (chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, added_at DOUBLE PRECISION NOT NULL, PRIMARY KEY (chat_id, user_id))''')
        db_execute(conn, '''CREATE TABLE IF NOT EXISTS spam_feedback (
            content_hash TEXT PRIMARY KEY,
            features TEXT NOT NULL,
            source TEXT NOT NULL,
            confirmed INTEGER NOT NULL DEFAULT 0,
            synced INTEGER NOT NULL DEFAULT 0,
            created_at DOUBLE PRECISION NOT NULL,
            hit_count INTEGER NOT NULL DEFAULT 0,
            first_seen DOUBLE PRECISION DEFAULT NULL,
            last_seen DOUBLE PRECISION DEFAULT NULL,
            blocked INTEGER NOT NULL DEFAULT 0,
            auto_learned INTEGER NOT NULL DEFAULT 0
        )''')
        db_execute(conn, '''CREATE INDEX IF NOT EXISTS idx_feedback_confirmed ON spam_feedback(confirmed, synced)''')
        db_execute(conn, '''CREATE INDEX IF NOT EXISTS idx_feedback_cleanup ON spam_feedback(confirmed, blocked, last_seen)''')
        conn.commit()
        try: db_execute(conn, "ALTER TABLE users ADD COLUMN lang TEXT DEFAULT NULL")
        except Exception: conn.rollback()
        try: db_execute(conn, "ALTER TABLE users ADD COLUMN last_seen DOUBLE PRECISION DEFAULT 0")
        except Exception: conn.rollback()
        try: db_execute(conn, "ALTER TABLE pending_captcha ADD COLUMN token TEXT DEFAULT NULL")
        except Exception: conn.rollback()
        try:
            feedback_cols = {row[1] for row in db_execute(conn, "PRAGMA table_info(spam_feedback)").fetchall()}
        except Exception:
            feedback_cols = set()
        if 'hit_count' not in feedback_cols:
            try: db_execute(conn, "ALTER TABLE spam_feedback ADD COLUMN hit_count INTEGER NOT NULL DEFAULT 0")
            except Exception: conn.rollback()
        if 'first_seen' not in feedback_cols:
            try: db_execute(conn, "ALTER TABLE spam_feedback ADD COLUMN first_seen DOUBLE PRECISION DEFAULT NULL")
            except Exception: conn.rollback()
        if 'last_seen' not in feedback_cols:
            try: db_execute(conn, "ALTER TABLE spam_feedback ADD COLUMN last_seen DOUBLE PRECISION DEFAULT NULL")
            except Exception: conn.rollback()
        if 'blocked' not in feedback_cols:
            try: db_execute(conn, "ALTER TABLE spam_feedback ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0")
            except Exception: conn.rollback()
        if 'auto_learned' not in feedback_cols:
            try: db_execute(conn, "ALTER TABLE spam_feedback ADD COLUMN auto_learned INTEGER NOT NULL DEFAULT 0")
            except Exception: conn.rollback()
        conn.commit()

def db_save_spam_feedback(content, source):
    if not RULE_LEARN_ENABLED or not content:
        return None
    features = sorted(extract_rule_terms(content))
    if not features:
        return None
    content_hash = hashlib.sha1(content.encode('utf-8', errors='ignore')).hexdigest()[:16]
    conn = get_db_conn()
    auto_confirmed = False
    with _db_lock:
        now = time.time()
        row = db_execute(
            conn,
            "SELECT confirmed, synced, blocked, hit_count FROM spam_feedback WHERE content_hash=?",
            (content_hash,),
        ).fetchone()
        if row is None:
            params = (content_hash, json.dumps(features, ensure_ascii=False), source, now, now, now)
            db_execute(
                conn,
                "INSERT INTO spam_feedback (content_hash, features, source, confirmed, synced, created_at, hit_count, first_seen, last_seen, blocked, auto_learned) "
                "VALUES (?, ?, ?, 0, 0, ?, 1, ?, ?, 0, 0)",
                params,
            )
        else:
            confirmed, synced, blocked, hit_count = row
            new_hit_count = int(hit_count or 0) + 1
            should_auto_learn = bool(
                RULE_AUTO_LEARN_ENABLED
                and not blocked
                and not confirmed
                and new_hit_count >= RULE_AUTO_LEARN_THRESHOLD
            )
            db_execute(
                conn,
                "UPDATE spam_feedback SET hit_count=?, last_seen=?, confirmed=?, auto_learned=?, synced=? WHERE content_hash=?",
                (
                    new_hit_count,
                    now,
                    1 if should_auto_learn else confirmed,
                    1 if should_auto_learn else 0,
                    0 if should_auto_learn else synced,
                    content_hash,
                ),
            )
            auto_confirmed = bool(should_auto_learn)
        conn.commit()
    if auto_confirmed:
        refresh_learned_rules()
    return content_hash


def db_feedback_features(content_hash):
    conn = get_db_conn()
    row = db_execute(conn, "SELECT features FROM spam_feedback WHERE content_hash=?", (content_hash,)).fetchone()
    if not row:
        return []
    try:
        data = json.loads(row[0])
    except (TypeError, ValueError):
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


def db_set_feedback_confirmed(content_hash, confirmed):
    conn = get_db_conn()
    with _db_lock:
        if confirmed:
            db_execute(conn, "UPDATE spam_feedback SET confirmed=1, blocked=0, auto_learned=0, synced=0 WHERE content_hash=?", (content_hash,))
        else:
            db_execute(conn, "UPDATE spam_feedback SET blocked=1, confirmed=0, auto_learned=0 WHERE content_hash=?", (content_hash,))
        conn.commit()


def db_list_learned_features():
    conn = get_db_conn()
    features = set()
    rows = db_execute(
        conn,
        "SELECT features FROM spam_feedback WHERE confirmed=1 AND blocked=0 ORDER BY last_seen DESC LIMIT ?",
        (RULE_LEARNED_MEMORY_LIMIT,),
    ).fetchall()
    for row in rows:
        try:
            data = json.loads(row[0])
        except (TypeError, ValueError):
            continue
        if isinstance(data, list):
            for item in data:
                if len(features) >= RULE_LEARNED_MEMORY_LIMIT:
                    return list(features)
                features.add(str(item))
    return list(features)


def _db_delete_feedback_hashes(conn, content_hashes, batch=500):
    for start in range(0, len(content_hashes), batch):
        chunk = content_hashes[start:start + batch]
        placeholders = ','.join('?' * len(chunk))
        db_execute(conn, f"DELETE FROM spam_feedback WHERE content_hash IN ({placeholders})", chunk)


def db_cleanup_spam_feedback():
    try:
        now = time.time()
        pending_cutoff = now - 86400 * RULE_AUTO_LEARN_RETENTION_DAYS
        blocked_cutoff = now - 86400 * RULE_IGNORE_RETENTION_DAYS
        with _db_lock:
            conn = get_db_conn()
            db_execute(conn, "DELETE FROM spam_feedback WHERE confirmed=0 AND blocked=0 AND (last_seen IS NULL OR last_seen < ?)", (pending_cutoff,))
            db_execute(conn, "DELETE FROM spam_feedback WHERE blocked=1 AND (last_seen IS NULL OR last_seen < ?)", (blocked_cutoff,))
            row = db_execute(conn, "SELECT COUNT(*) FROM spam_feedback", ()).fetchone()
            excess = int(row[0] or 0) - RULE_AUTO_LEARN_MAX_RULES
            while excess > 0:
                rows = db_execute(
                    conn,
                    "SELECT content_hash FROM spam_feedback WHERE confirmed=0 ORDER BY last_seen ASC LIMIT 500",
                    (),
                ).fetchall()
                if not rows:
                    break
                _db_delete_feedback_hashes(conn, [r[0] for r in rows])
                excess -= len(rows)
            while excess > 0:
                rows = db_execute(
                    conn,
                    "SELECT content_hash FROM spam_feedback WHERE confirmed=1 AND synced=1 ORDER BY last_seen ASC LIMIT 500",
                    (),
                ).fetchall()
                if not rows:
                    break
                _db_delete_feedback_hashes(conn, [r[0] for r in rows])
                excess -= len(rows)
            conn.commit()
    except Exception as e:
        logging.warning(f"Spam feedback cleanup failed: {e}")


def db_list_unsynced_features():
    conn = get_db_conn()
    rows = db_execute(
        conn,
        "SELECT content_hash, features FROM spam_feedback WHERE confirmed=1 AND blocked=0 AND synced=0 ORDER BY created_at ASC LIMIT 50",
        (),
    ).fetchall()
    hashes = []
    features = []
    for row in rows:
        hashes.append(row[0])
        try:
            data = json.loads(row[1])
        except (TypeError, ValueError):
            continue
        if isinstance(data, list):
            features.extend(str(item) for item in data)
    return hashes, features


def db_mark_feedback_synced(hashes):
    if not hashes:
        return
    conn = get_db_conn()
    with _db_lock:
        for content_hash in hashes:
            db_execute(conn, "UPDATE spam_feedback SET synced=1 WHERE content_hash=?", (content_hash,))
        conn.commit()


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

def db_has_captcha_token(user_id, token):
    with _db_lock:
        conn = get_db_conn()
        cur = db_execute(conn, "SELECT token FROM pending_captcha WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if not row:
            return False
        expected_token = row[0]
        return bool(expected_token and secrets.compare_digest(str(token), str(expected_token)))

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
        text_answer_ok = (
            CAPTCHA_TEXT_FALLBACK
            and token is None
            and input_ans is not None
            and str(input_ans).strip() == str(expected)
        )
        token_ok = (
            token
            and expected_token
            and secrets.compare_digest(str(token), str(expected_token))
            and input_ans is not None
            and str(input_ans).strip() == str(expected)
        ) or text_answer_ok
        if token_ok:
            db_execute(conn, "UPDATE users SET verified=1, ban_until=0 WHERE user_id=?", (user_id,))
            db_execute(conn, "DELETE FROM pending_captcha WHERE user_id=?", (user_id,))
            conn.commit()
            invalidate_cache(user_id)
            clear_captcha_prompt_state(user_id)
            clear_captcha_wrong_state(user_id)
            return 'success', 0
        else:
            wrong_count = record_captcha_wrong(user_id)
            db_execute(conn, "DELETE FROM pending_captcha WHERE user_id=?", (user_id,))
            if wrong_count >= CAPTCHA_WRONG_LIMIT:
                ban_until = now + random.randint(MIN_BAN_DURATION, MAX_BAN_DURATION)
                db_execute(conn, "UPDATE users SET verified=0, ban_until=? WHERE user_id=?", (ban_until, user_id))
                conn.commit()
                invalidate_cache(user_id)
                clear_captcha_prompt_state(user_id)
                clear_captcha_wrong_state(user_id)
                return 'fail_ban', ban_until
            else:
                conn.commit()
                set_captcha_prompt_cooldown(user_id)
                return 'wrong_answer', wrong_count

def db_reset_all_verifications():
    with _db_lock:
        conn = get_db_conn()
        if ADMIN_ID is None:
            cur = db_execute(conn, "UPDATE users SET verified=0 WHERE verified=1")
            db_execute(conn, "DELETE FROM pending_captcha")
        else:
            cur = db_execute(conn, "UPDATE users SET verified=0 WHERE verified=1 AND user_id<>?", (ADMIN_ID,))
            db_execute(conn, "DELETE FROM pending_captcha WHERE user_id<>?", (ADMIN_ID,))
        changed = cur.rowcount if getattr(cur, 'rowcount', -1) is not None and cur.rowcount >= 0 else 0
        conn.commit()
    with _cache_lock:
        user_status_cache.clear()
    with _flood_lock:
        captcha_prompt_state.clear()
        captcha_callback_state.clear()
        captcha_wrong_state.clear()
        captcha_attempt_state.clear()
    return changed

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
    clear_captcha_wrong_state(user_id)
    with _flood_lock:
        prefix = f'bot:captcha:attempt:{user_id}:'
        for key in list(captcha_attempt_state):
            if key.startswith(prefix):
                captcha_attempt_state.pop(key, None)
    return ban_until

def db_unban_user(user_id):
    with _db_lock:
        conn = get_db_conn()
        db_execute(conn, "UPDATE users SET ban_until=0 WHERE user_id=?", (user_id,))
        conn.commit()
    invalidate_cache(user_id)

def db_get_ban_list(limit=50):
    now = time.time()
    with _db_lock:
        conn = get_db_conn()
        cur = db_execute(conn, "SELECT user_id, ban_until FROM users WHERE ban_until > ? ORDER BY ban_until DESC LIMIT ?", (now, limit))
        return cur.fetchall()

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
                    db_execute(conn, "DELETE FROM message_map WHERE msg_id IN (SELECT msg_id FROM message_map ORDER BY created_at ASC LIMIT ?)", (limit_cnt,))
                    cleaned_info = f"🗑️ 数据库清理: 自动覆盖了 {limit_cnt} 条旧消息记录。"
                    conn.commit()

                if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > (DB_SIZE_LIMIT_MB * 1024 * 1024):
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
    opposite = 'blacklist' if table_name == 'whitelist' else 'whitelist'
    with _db_lock:
        conn = get_db_conn()
        try:
            db_execute(conn, f"DELETE FROM {opposite} WHERE user_id=?", (user_id,))
            db_insert_user_ignore(conn, user_id, time.time())
            db_execute(conn, "UPDATE users SET ban_until=0, last_seen=? WHERE user_id=?", (time.time(), user_id))
            db_execute(conn, "DELETE FROM pending_captcha WHERE user_id=?", (user_id,))
            db_execute(conn, f"INSERT OR REPLACE INTO {table_name} (user_id, added_at) VALUES (?, ?)", (user_id, time.time()))
            conn.commit()
            success = True
        except Exception:
            conn.rollback()
            success = False
    if success:
        invalidate_cache(user_id)
        clear_captcha_prompt_state(user_id)
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

def db_add_group_ban(chat_id, user_id):
    with _db_lock:
        conn = get_db_conn()
        db_execute(
            conn,
            "INSERT OR REPLACE INTO group_bans (chat_id, user_id, added_at) VALUES (?, ?, ?)",
            (chat_id, user_id, time.time()),
        )
        conn.commit()

def db_remove_group_ban(chat_id, user_id):
    with _db_lock:
        conn = get_db_conn()
        cur = db_execute(conn, "DELETE FROM group_bans WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        conn.commit()
        return cur.rowcount > 0

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

def has_hard_block_term(text):
    compact = normalize_for_spam(text)
    if not compact:
        return False
    return any(normalize_for_spam(term) in compact for term in HARD_BLOCK_TERMS)

def normalize_lang(lang):
    return lang if lang in ('zh', 'en') else 'zh'

def build_spam_regex(keywords):
    normalized = set()
    for k in keywords:
        if not k or not str(k).strip():
            continue
        normalized.add(normalize_text(str(k)))
        compact = normalize_for_spam(str(k))
        if compact:
            normalized.add(compact)
    if not normalized:
        return None
    sorted_kws = sorted(normalized, key=len, reverse=True)[:MAX_SPAM_KEYWORDS]
    regexes = []
    for start in range(0, len(sorted_kws), RULE_REGEX_BATCH_SIZE):
        batch = sorted_kws[start:start + RULE_REGEX_BATCH_SIZE]
        escaped = [re.escape(k) for k in batch]
        pattern = r'(?:' + '|'.join(escaped) + r')'
        try:
            regexes.append(re.compile(pattern, re.IGNORECASE))
        except re.error:
            continue
    return regexes or None


def _apply_spam_rules(all_keywords, learned, source, remote_count, error_text=''):
    global _spam_regexes, _spam_exact_text_terms, _spam_exact_compact_terms, _current_spam_keywords
    global SPAM_RULE_SOURCE, SPAM_RULE_KEYWORD_COUNT, SPAM_RULE_REMOTE_COUNT, SPAM_RULE_UPDATED_AT, SPAM_RULE_LAST_ERROR
    regex_keywords = set(all_keywords) - set(learned)
    regexes = build_spam_regex(regex_keywords)
    exact_text_terms = set()
    exact_compact_terms = set()
    for term in islice(learned, RULE_EXACT_MAX_TERMS):
        text_term = normalize_text(str(term))
        compact_term = normalize_for_spam(str(term))
        if text_term:
            exact_text_terms.add(text_term)
        if compact_term:
            exact_compact_terms.add(compact_term)
    if not regexes and not exact_text_terms and not exact_compact_terms:
        return False
    with _spam_lock:
        _spam_regexes = regexes or []
        _spam_exact_text_terms = exact_text_terms
        _spam_exact_compact_terms = exact_compact_terms
        _current_spam_keywords = set(all_keywords)
        SPAM_RULE_SOURCE = source
        SPAM_RULE_KEYWORD_COUNT = min(len(regex_keywords), RULE_REGEX_MAX_KEYWORDS) + len(exact_text_terms)
        SPAM_RULE_REMOTE_COUNT = remote_count
        SPAM_RULE_UPDATED_AT = time.time()
        SPAM_RULE_LAST_ERROR = error_text
    return True

def load_fallback_spam_rules():
    keywords = set(FALLBACK_SPAM_KEYWORDS)
    if _apply_spam_rules(keywords, set(), 'fallback', 0):
        logging.info(f"Fallback spam rules loaded: {len(FALLBACK_SPAM_KEYWORDS)}")
        return True
    logging.warning("Fallback spam rules failed to load.")
    return False


def load_remote_rule_text():
    parts = []
    text = safe_requests_get(REMOTE_SPAM_URL)
    if text:
        parts.append(text)
    r2_text = fetch_r2_rules()
    if r2_text:
        parts.append(r2_text)
    combined = '\n'.join(parts)
    remote_words = set()
    for line in combined.splitlines():
        w = line.strip()
        if w:
            remote_words.add(w)
    return combined, remote_words


def _load_and_apply_remote_rules():
    global _current_remote_keywords, _remote_rule_text
    text, remote_words = load_remote_rule_text()
    if text:
        _remote_rule_text = text
    _current_remote_keywords = remote_words
    load_learned_keywords()
    all_keywords = set(FALLBACK_SPAM_KEYWORDS) | remote_words | set(_learned_keywords)
    source = 'remote' if remote_words else 'fallback'
    error_text = '' if remote_words else '远程规则未返回内容，当前使用内置兜底规则。'
    ok = _apply_spam_rules(all_keywords, _learned_keywords, source, len(remote_words), error_text)
    return ok, remote_words


def update_spam_rules():
    global _remote_rules_admin_notified
    while True:
        try:
            ok, remote_words = _load_and_apply_remote_rules()
            if ok:
                logging.info(f"Rules Updated: {SPAM_RULE_KEYWORD_COUNT} keywords, remote {len(remote_words)}")
                if remote_words and not _remote_rules_admin_notified:
                    notify_admin_remote_rules_loaded(len(remote_words), SPAM_RULE_KEYWORD_COUNT)
                    _remote_rules_admin_notified = True
            else:
                logging.warning("Spam rules build returned empty matchers; keeping previous rules.")
        except Exception as e:
            SPAM_RULE_LAST_ERROR = str(e)
            logging.warning(f"Spam rules update failed: {e}")
        try:
            sync_pending_learned_rules()
        except Exception as e:
            logging.warning(f"Learned rules sync retry failed: {e}")
        time.sleep(SPAM_UPDATE_INTERVAL)

def reload_spam_rules_once():
    global _remote_rules_admin_notified, SPAM_RULE_LAST_ERROR
    ok, remote_words = _load_and_apply_remote_rules()
    if not ok:
        SPAM_RULE_LAST_ERROR = '广告规则编译失败，已保留上一版规则。'
        return False, SPAM_RULE_LAST_ERROR
    if remote_words:
        _remote_rules_admin_notified = True
        return True, f"第三方广告规则已生效：远程 {len(remote_words)} 条，实际生效 {SPAM_RULE_KEYWORD_COUNT} 条。"
    return False, '第三方广告规则没有拉取成功，当前仍使用内置兜底规则。'


def load_learned_keywords():
    global _learned_keywords
    if not RULE_LEARN_ENABLED:
        _learned_keywords = set()
        return
    try:
        _learned_keywords = set(db_list_learned_features())
        logging.info(f"Learned spam rules loaded: {len(_learned_keywords)}")
    except Exception as e:
        logging.warning(f"Load learned spam rules failed: {e}")


def refresh_learned_rules():
    load_learned_keywords()
    source = 'remote' if _current_remote_keywords else 'fallback'
    return _apply_spam_rules(
        set(FALLBACK_SPAM_KEYWORDS) | set(_current_remote_keywords) | set(_learned_keywords),
        _learned_keywords,
        source,
        len(_current_remote_keywords),
        '',
    )


def sync_pending_learned_rules():
    if not RULE_LEARN_ENABLED or not (github_config_enabled() or r2_config_enabled()):
        return
    hashes, features = db_list_unsynced_features()
    if not features:
        return
    features = list(dict.fromkeys(features))
    result = sync_learned_rules(features, _remote_rule_text or '')
    configured = [
        channel
        for channel, enabled in (
            ('github', github_config_enabled()),
            ('r2', r2_config_enabled()),
        )
        if enabled
    ]
    if configured and all(result.get(channel) for channel in configured):
        db_mark_feedback_synced(hashes)
        logging.info(f"Learned rules synced: github={result.get('github')}, r2={result.get('r2')}")


def sync_pending_learned_rules_async():
    threading.Thread(target=sync_pending_learned_rules, daemon=True).start()


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
            to_del_auto = [uid for uid, v in auto_reply_cache.items() if now - v.get('ts', now) > AUTO_REPLY_COOLDOWN * 4]
            for uid in to_del_auto: del auto_reply_cache[uid]
        with _flood_lock:
            to_del_prompt = [uid for uid, v in captcha_prompt_state.items() if now - v.get('first', now) > UNVERIFIED_WINDOW and v.get('silent_until', 0) < now]
            for uid in to_del_prompt: del captcha_prompt_state[uid]
        if now - _last_db_cleanup > DB_CLEANUP_INTERVAL:
            db_cleanup_map()
            db_cleanup_spam_feedback()
            _last_db_cleanup = now

def check_global_limit():
    global _global_token_bucket, _last_token_update
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
    with _flood_lock:
        captcha_prompt_state.pop(user_id, None)

def set_captcha_prompt_cooldown(user_id):
    now = time.time()
    with _flood_lock:
        state = captcha_prompt_state.get(user_id, {'first': now, 'last': 0, 'count': 0, 'silent_until': 0})
        if now - state.get('first', now) > UNVERIFIED_WINDOW:
            state = {'first': now, 'last': 0, 'count': 0, 'silent_until': 0}
        state['last'] = now
        captcha_prompt_state[user_id] = state

def send_captcha_after_cooldown(user_id):
    def _send_later():
        try:
            stat = get_cached_user_status(user_id)
            if stat['verified'] or stat['wl'] or stat['bl'] or stat['ban_until'] > time.time():
                return
            clear_captcha_prompt_state(user_id)
            q, markup = generate_captcha(user_id)
            if not markup:
                return
            m = safe_send(bot.send_message, user_id, q, parse_mode='HTML', reply_markup=markup)
            deleter.schedule(user_id, m.message_id, CAPTCHA_DELETE_DELAY)
        except Exception as e:
            logging.warning(f"Send captcha after cooldown failed for {user_id}: {e}")
    timer = threading.Timer(CAPTCHA_PROMPT_COOLDOWN, _send_later)
    timer.daemon = True
    timer.start()

def check_captcha_callback_limit(user_id):
    now = time.time()
    with _flood_lock:
        timestamps = captcha_callback_state.setdefault(user_id, deque(maxlen=CAPTCHA_CALLBACK_LIMIT + 2))
        while timestamps and now - timestamps[0] > CAPTCHA_CALLBACK_WINDOW:
            timestamps.popleft()
        if len(timestamps) >= CAPTCHA_CALLBACK_LIMIT:
            return False
        timestamps.append(now)
        return True

def claim_captcha_attempt(user_id, token):
    now = time.time()
    with _flood_lock:
        key = f'bot:captcha:attempt:{user_id}:{token}'
        expired = [k for k, ts in captcha_attempt_state.items() if now - ts > CAPTCHA_TIMEOUT + CAPTCHA_PROMPT_COOLDOWN]
        for old_key in expired:
            captcha_attempt_state.pop(old_key, None)
        if key in captcha_attempt_state:
            return False
        captcha_attempt_state[key] = now
        return True

def record_captcha_wrong(user_id):
    now = time.time()
    with _flood_lock:
        state = captcha_wrong_state.get(user_id, {'first': now, 'count': 0})
        if now - state.get('first', now) > CAPTCHA_WRONG_WINDOW:
            state = {'first': now, 'count': 0}
        state['count'] = state.get('count', 0) + 1
        captcha_wrong_state[user_id] = state
        return state['count']

def clear_captcha_wrong_state(user_id):
    with _flood_lock:
        captcha_wrong_state.pop(user_id, None)

def keyword_rule_hit(text):
    """远程/学习/兜底关键词是否命中（不含强特征词）。

    只做规则命中判定，命中结果交给 spam_risk_score 加权，不再一票即封。
    """
    if not text:
        return False
    text = normalize_text(text)
    if len(text) > 5000:
        text = text[:5000]
    text_nospace = re.sub(r'\s+', '', text)
    text_cleaned = re.sub(r'[^\w]', '', text)
    text_compact = normalize_for_spam(text)
    if not _spam_regexes and not _spam_exact_text_terms and not _spam_exact_compact_terms:
        load_fallback_spam_rules()
    with _spam_lock:
        regexes = list(_spam_regexes)
        exact_text_terms = _spam_exact_text_terms
        exact_compact_terms = _spam_exact_compact_terms
    for pattern in regexes:
        try:
            if (pattern.search(text) or pattern.search(text_nospace) or pattern.search(text_cleaned) or pattern.search(text_compact)):
                return True
        except (TypeError, ValueError, re.error):
            return False
    if exact_text_terms and any(term in text_nospace for term in exact_text_terms):
        return True
    if exact_compact_terms and any(term in text_compact for term in exact_compact_terms):
        return True
    return False

def is_spam_text(text):
    """强特征即封，或命中规则库关键词。用于用户名/文件名等一票判定入口。"""
    if not text:
        return False
    return has_hard_block_term(text) or keyword_rule_hit(text)

def spam_risk_score(text):
    if not text: return 0
    raw = normalize_text(text)
    compact = normalize_for_spam(raw)
    score = 0
    has_url = bool(URL_RE.search(raw))
    has_mention = bool(MENTION_RE.search(raw))
    has_phone = bool(PHONE_RE.search(raw))
    has_contact = bool(CONTACT_RE.search(raw))
    has_crypto = bool(CRYPTO_RE.search(compact))
    # 触达信号：广告要能被联系上才有意义（链接/@/电话/联系方式）
    if has_url: score += 2
    if has_mention: score += 2
    if has_phone: score += 2
    if has_contact: score += 2
    if has_crypto: score += 3
    reach = has_url or has_mention or has_phone or has_contact
    # 营销/诱导词命中
    term_hits = sum(1 for term in SPAM_MARKETING_TERMS if normalize_for_spam(term) in compact)
    score += min(term_hits * 2, 6)
    # 规则库命中但不在营销词表里的词才补分，避免和 term_hits 重复计分
    if term_hits == 0 and keyword_rule_hit(raw): score += 2
    # 组合重罚：收款、诱导、联系方式三类信号同时出现≥2 类才加码
    has_money = has_crypto or bool(MONEY_RE.search(raw))
    has_lure = bool(LURE_RE.search(raw))
    if sum([has_money, has_lure, has_contact]) >= 2: score += 3
    if len(compact) > 80 and term_hits >= 2: score += 2
    if REPEAT_CHAR_RE.search(compact): score += 1
    if len(REPEATED_PUNCT_RE.findall(raw)) >= 2: score += 1
    # 降误封：只有单个营销词、既无触达方式也无加密货币信号，判为讨论而非广告
    if term_hits <= 1 and not reach and not has_crypto: score -= 3
    return max(score, 0)

def get_user_profile_text(user):
    if not user:
        return ''
    return " ".join([
        str(getattr(user, 'first_name', '') or ''),
        str(getattr(user, 'last_name', '') or ''),
        str(getattr(user, 'username', '') or ''),
    ])

def get_ai_spam_result(text, profile_text=''):
    if not ai_cls.enabled:
        return None
    text = (text or '').strip()
    if not text:
        return None
    keywords = select_ai_keywords(text + ' ' + (profile_text or ''), AI_KEYWORDS_LIMIT)
    try:
        return ai_cls.classify(text, keywords=keywords, profile_text=profile_text)
    except Exception as e:
        logging.warning(f"AI spam check failed: {e}")
        return None


def select_ai_keywords(text, limit):
    """Return only the local rule keywords actually hit by this message.

    只递真正命中当前消息的本地词（更贴合事实，不凑数）。命中数在 limit 以内按实际数量递，
    超过 limit 才截断。命中判定复用 normalize_for_spam，和本地打分同一套归一化逻辑，几乎零额外开销。
    """
    if limit <= 0:
        return []
    compact = normalize_for_spam(text or '')
    if not compact:
        return []
    with _spam_lock:
        pool = list(_current_spam_keywords or FALLBACK_SPAM_KEYWORDS)
    hit = []
    for kw in pool:
        term = normalize_for_spam(str(kw))
        if term and term in compact:
            hit.append(kw)
            if len(hit) >= limit:
                break
    return hit

def should_run_ai_check(score):
    if not ai_cls.enabled:
        return False
    return AI_ALWAYS_CHECK or score >= AI_MIN_SCORE

def classify_spam_text(text, profile_text='', run_ai=True):
    raw_input = text or ''
    raw = normalize_text(raw_input)
    compact = normalize_for_spam(raw)
    score = 0
    try:
        score = spam_risk_score(raw)
    except Exception as e:
        logging.warning(f"Spam risk scoring failed: {e}")
    reasons = []
    # 强特征词（U币等）即时封，其余交给加权分判定，避免长规则库子串误伤
    if has_hard_block_term(raw):
        reasons.append('命中强广告特征')
    elif score >= SPAM_BLOCK_SCORE:
        reasons.append(f'风险分 {score} >= {SPAM_BLOCK_SCORE}')
    blocked = bool(reasons)
    if not blocked and run_ai and should_run_ai_check(score):
        ai_result = get_ai_spam_result(raw_input, profile_text)
        if ai_result and ai_result.get('is_spam'):
            blocked = True
            reasons.append(f"AI判定：{ai_result.get('reason') or '广告'}")
    if not reasons:
        reasons.append(f'未命中，风险分 {score}')
    return blocked, score, compact, '；'.join(reasons)


def analyze_spam_message(message, run_ai=True):
    content = getattr(message, 'text', None) or getattr(message, 'caption', None) or ""
    blocked, content_score, compact, content_reason = classify_spam_text(content, run_ai=False)
    if blocked:
        return True, content_score, compact, content_reason
    user = getattr(message, 'from_user', None)
    if user:
        if is_spam_text(getattr(user, 'first_name', None)):
            return True, content_score, compact, '用户名命中广告关键词'
        if is_spam_text(getattr(user, 'last_name', None)):
            return True, content_score, compact, '用户名命中广告关键词'
        if is_spam_text(getattr(user, 'username', None)):
            return True, content_score, compact, '用户名命中广告关键词'
    profile_text = get_user_profile_text(user)
    profile_score = 0
    try:
        profile_score = spam_risk_score(profile_text)
        if profile_score >= SPAM_PROFILE_BLOCK_SCORE:
            return True, max(content_score, profile_score), compact, f'资料风险分 {profile_score} >= {SPAM_PROFILE_BLOCK_SCORE}'
    except Exception as e:
        logging.warning(f"Profile spam risk scoring failed: {e}")
    document = getattr(message, 'document', None)
    document_score = 0
    if document and hasattr(document, 'file_name'):
        if is_spam_text(document.file_name):
            return True, max(content_score, profile_score, document_score), compact, '文件名命中广告关键词'
        try:
            document_score = spam_risk_score(document.file_name)
            if document_score >= SPAM_PROFILE_BLOCK_SCORE:
                return True, max(content_score, profile_score, document_score), compact, f'文件名风险分 {document_score} >= {SPAM_PROFILE_BLOCK_SCORE}'
        except Exception as e:
            logging.warning(f"Document spam risk scoring failed: {e}")
    final_score = max(content_score, profile_score, document_score)
    if run_ai and should_run_ai_check(final_score):
        ai_result = get_ai_spam_result(content, profile_text)
        if ai_result and ai_result.get('is_spam'):
            return True, final_score, compact, f"AI判定：{ai_result.get('reason') or '广告'}"
    return False, final_score, compact, f'未命中，风险分 {final_score}'


def explain_spam_text(text, profile_text='', run_ai=True):
    return classify_spam_text(text, profile_text=profile_text, run_ai=run_ai)

def block_spam_message(message, user_id, delete_delay=MSG_AUTO_DELETE_DELAY, ban_user=True, analysis=None):
    if ban_user:
        db_ban_user(user_id, MAX_BAN_DURATION)
    notice = safe_send(bot.send_message, user_id, get_text('spam_ban', user_id))
    if notice:
        deleter.schedule(user_id, notice.message_id, MSG_AUTO_DELETE_DELAY)
    deleter.schedule(user_id, message.message_id, delete_delay)
    if analysis is None:
        content = getattr(message, 'text', None) or getattr(message, 'caption', None) or ''
        user = getattr(message, 'from_user', None)
        profile_text = get_user_profile_text(user)
        blocked, score, compact, reason = explain_spam_text(content, profile_text=profile_text, run_ai=True)
    else:
        blocked, score, compact, reason = analysis
    content = getattr(message, 'text', None) or getattr(message, 'caption', None) or ''
    try:
        action = "已封禁，广告内容不会转发给管理员。" if ban_user else "已拦截本条消息，广告内容不会转发给管理员。"
        alert_msg = f"🚫 <b>已拦截广告</b>\n用户: <code>{user_id}</code>\n原因: {html.escape(reason)}\n风险分: <code>{score}</code>\n操作: {action}"
        markup = None
        if not ban_user:
            markup = InlineKeyboardMarkup()
            markup.row(
                InlineKeyboardButton("封禁用户", callback_data=f"spam_ban:{user_id}"),
                InlineKeyboardButton("不封禁", callback_data=f"spam_keep:{user_id}")
            )
        content_hash = db_save_spam_feedback(content, 'block')
        if content_hash:
            if markup is None:
                markup = InlineKeyboardMarkup()
            markup.row(
                InlineKeyboardButton("学习规则", callback_data=f"spam_learn:{user_id}:{content_hash}"),
                InlineKeyboardButton("不学习", callback_data=f"spam_ignore:{user_id}:{content_hash}")
            )
        safe_send(bot.send_message, ADMIN_ID, alert_msg, parse_mode='HTML', reply_markup=markup)
    except Exception as e:
        logging.warning(f"Spam block notice failed for {user_id}: {e}")

def obfuscate_captcha_text(text):
    zw = ['\u200b', '\u200c', '\u2060']
    out = []
    for char in text:
        out.append(char)
        if char.strip() and random.random() < 0.45:
            out.append(random.choice(zw))
    return ''.join(out)

def captcha_num(n, lang):
    zh_nums = {
        0: '零', 1: '壹', 2: '贰', 3: '叁', 4: '肆', 5: '伍', 6: '陆', 7: '柒', 8: '捌', 9: '玖',
        10: '拾', 11: '拾壹', 12: '拾贰', 13: '拾叁', 14: '拾肆', 15: '拾伍', 16: '拾陆', 17: '拾柒', 18: '拾捌', 19: '拾玖', 20: '贰拾'
    }
    full_width = str(n).translate(str.maketrans('0123456789', '０１２３４５６７８９'))
    if lang == 'zh':
        choices = [str(n), full_width]
        if n in zh_nums:
            choices.append(zh_nums[n])
        return random.choice(choices)
    words = {
        0: 'zero', 1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six', 7: 'seven', 8: 'eight', 9: 'nine',
        10: 'ten', 11: 'eleven', 12: 'twelve', 13: 'thirteen', 14: 'fourteen', 15: 'fifteen', 16: 'sixteen', 17: 'seventeen', 18: 'eighteen', 19: 'nineteen', 20: 'twenty'
    }
    choices = [str(n), full_width]
    if n in words:
        choices.append(words[n])
    return random.choice(choices)

def captcha_option_text(n, lang):
    raw = str(n)
    if not raw.lstrip('-').isdigit():
        if random.random() < 0.4:
            return raw.translate(str.maketrans('0123456789.', '０１２３４５６７８９．'))
        return raw
    n = int(raw)
    if random.random() < 0.45:
        return captcha_num(n, lang)
    return raw

def get_text(key, user_id, **kwargs):
    stat = get_cached_user_status(user_id)
    lang = normalize_lang(stat['lang'])
    txt = STRINGS.get(key, {}).get(lang, STRINGS.get(key, {}).get('zh', ''))
    if kwargs: return txt.format(**kwargs)
    return txt

def get_user_lang(user_id):
    return normalize_lang(get_cached_user_status(user_id).get('lang'))

def get_menu_text(user_id):
    lang = get_user_lang(user_id)
    if user_id == ADMIN_ID:
        return "管理菜单已打开，请选择操作。" if lang == 'zh' else "Admin menu is open. Choose an action."
    return "菜单已打开，请选择功能或直接发送消息。" if lang == 'zh' else "Menu is open. Choose an option or send a message directly."

def get_user_faq(user_id):
    lang = get_user_lang(user_id)
    if lang == 'zh':
        return "💡 常见问题\n1. 验证通过后，可以直接发送消息给管理员。\n2. 违规、广告、刷屏内容会被自动拦截。\n3. 如需重新选择语言，请点击菜单里的“切换语言”。"
    return "💡 FAQ\n1. After verification, send a message directly to contact the admin.\n2. Spam, ads, and flooding are blocked automatically.\n3. To change language, tap Change Language in the menu."

def build_reply_menu(user_id, lang):
    try:
        placeholder = "选择菜单或直接发送消息" if lang == 'zh' else "Choose a menu item or send a message"
        markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2, one_time_keyboard=False, input_field_placeholder=placeholder)
    except TypeError:
        markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2, one_time_keyboard=False)
    if user_id == ADMIN_ID:
        markup.row(KeyboardButton(STRINGS['admin_menu_status'][lang]), KeyboardButton(STRINGS['admin_menu_reload_rules'][lang]))
        markup.row(KeyboardButton(STRINGS['admin_menu_ban_list'][lang]), KeyboardButton(STRINGS['admin_menu_wl'][lang]), KeyboardButton(STRINGS['admin_menu_bl'][lang]))
        markup.row(KeyboardButton(STRINGS['admin_menu_unban'][lang]), KeyboardButton(STRINGS['admin_menu_awl'][lang]), KeyboardButton(STRINGS['admin_menu_dwl'][lang]))
        markup.row(KeyboardButton(STRINGS['admin_menu_abl'][lang]), KeyboardButton(STRINGS['admin_menu_dbl'][lang]))
        markup.row(KeyboardButton(STRINGS['admin_menu_resetverify'][lang]), KeyboardButton(STRINGS['admin_menu_broadcast'][lang]), KeyboardButton(STRINGS['admin_menu_spamtest'][lang]))
        markup.row(KeyboardButton(STRINGS['admin_menu_id'][lang]), KeyboardButton(STRINGS['menu_help'][lang]), KeyboardButton(STRINGS['menu_lang'][lang]))
    else:
        markup.row(KeyboardButton(STRINGS['menu_contact'][lang]), KeyboardButton(STRINGS['menu_help'][lang]))
        markup.row(KeyboardButton(STRINGS['menu_lang'][lang]))
    return markup

def menu_values(key):
    return {STRINGS[key]['zh'], STRINGS[key]['en']}

def is_user_menu_text(text):
    return text in (menu_values('menu_contact') | menu_values('menu_help') | menu_values('menu_lang'))

def build_default_commands(lang):
    if lang == 'en':
        return [
            BotCommand('start', 'Open menu'),
            BotCommand('menu', 'Open menu'),
            BotCommand('help', 'Help'),
            BotCommand('id', 'Show Telegram ID'),
        ]
    return [
        BotCommand('start', '打开菜单'),
        BotCommand('menu', '打开菜单'),
        BotCommand('help', '帮助'),
        BotCommand('id', '查看 Telegram ID'),
    ]

def build_admin_commands(lang):
    commands = build_default_commands(lang)
    if lang == 'en':
        return commands + [
            BotCommand('status', 'Bot status'),
            BotCommand('reloadrules', 'Reload spam rules'),
            BotCommand('vlist', 'View list: /vlist wl|bl|ban'),
            BotCommand('unban', 'Unban user: /unban ID'),
            BotCommand('awl', 'Add whitelist: /awl ID'),
            BotCommand('dwl', 'Remove whitelist: /dwl ID'),
            BotCommand('abl', 'Add blacklist: /abl ID'),
            BotCommand('dbl', 'Remove blacklist: /dbl ID'),
            BotCommand('resetverify', 'Reset verification for all users'),
            BotCommand('gb', 'Broadcast: /gb text'),
            BotCommand('spamtest', 'Test spam rules: /spamtest text'),
        ]
    return commands + [
        BotCommand('status', '机器人状态'),
        BotCommand('reloadrules', '重载广告规则'),
        BotCommand('vlist', '查看名单: /vlist wl|bl|ban'),
        BotCommand('unban', '解除临时封禁: /unban ID'),
        BotCommand('awl', '加入白名单: /awl ID'),
        BotCommand('dwl', '移出白名单: /dwl ID'),
        BotCommand('abl', '加入黑名单: /abl ID'),
        BotCommand('dbl', '移出黑名单: /dbl ID'),
        BotCommand('resetverify', '清空验证状态，全部重新验证'),
        BotCommand('gb', '广播: /gb 内容'),
        BotCommand('spamtest', '测试广告规则: /spamtest 内容'),
    ]

def setup_bot_menus():
    try:
        safe_send(bot.set_my_commands, build_default_commands('zh'), scope=BotCommandScopeDefault(), language_code='zh')
        safe_send(bot.set_my_commands, build_default_commands('en'), scope=BotCommandScopeDefault(), language_code='en')
        safe_send(bot.set_my_commands, build_default_commands('zh'), scope=BotCommandScopeDefault())
        if ADMIN_ID is not None:
            safe_send(bot.set_my_commands, build_admin_commands('zh'), scope=BotCommandScopeChat(ADMIN_ID), language_code='zh')
            safe_send(bot.set_my_commands, build_admin_commands('en'), scope=BotCommandScopeChat(ADMIN_ID), language_code='en')
            safe_send(bot.set_my_commands, build_admin_commands('zh'), scope=BotCommandScopeChat(ADMIN_ID))
            safe_send(bot.set_chat_menu_button, chat_id=ADMIN_ID, menu_button=MenuButtonCommands())
        safe_send(bot.set_chat_menu_button, menu_button=MenuButtonCommands())
        logging.info("Telegram command menus configured.")
    except Exception as e:
        logging.warning(f"Configure Telegram command menus failed: {e}")

def send_menu(user_id, text=None):
    stat = get_cached_user_status(user_id)
    lang = normalize_lang(stat['lang'])
    markup = build_reply_menu(user_id, lang)
    msg = text if text else get_menu_text(user_id)
    try:
        safe_send(bot.send_message, user_id, msg, reply_markup=markup)
    except Exception as e: logging.warning(f"Send menu failed for {user_id}: {e}")

def ask_language(chat_id, force=False):
    if not force and not should_send_captcha_prompt(chat_id): return
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🇨🇳 中文", callback_data="set_lang:zh"), InlineKeyboardButton("🇺🇸 English", callback_data="set_lang:en"))
    try:
        m = safe_send(bot.send_message, chat_id, STRINGS['select_lang']['zh'], reply_markup=markup)
        deleter.schedule(chat_id, m.message_id, MSG_AUTO_DELETE_DELAY)
    except Exception as e: logging.warning(f"Ask language failed for {chat_id}: {e}")

def build_captcha_question(lang):
    mode = random.choice(['story_add', 'story_sub', 'group_total', 'order_steps', 'decimal_add'])
    if mode == 'group_total':
        n1 = random.randint(2, 6)
        n2 = random.randint(3, 8)
        n3 = random.randint(1, 7)
        ans = n1 * n2 + n3
        if lang == 'zh':
            q_raw = "\u6709 {a} \u7ec4\uff0c\u6bcf\u7ec4 {b} \u4e2a\uff0c\u53c8\u591a {c} \u4e2a\uff0c\u4e00\u5171\u591a\u5c11\u4e2a\uff1f".format(
                a=captcha_num(n1, lang), b=captcha_num(n2, lang), c=captcha_num(n3, lang)
            )
        else:
            q_raw = "There are {a} groups with {b} each, plus {c} more. What is the total?".format(
                a=captcha_num(n1, lang), b=captcha_num(n2, lang), c=captcha_num(n3, lang)
            )
    elif mode == 'story_sub':
        n1 = random.randint(12, 28)
        n2 = random.randint(3, 12)
        n3 = random.randint(1, 8)
        ans = n1 + n2 - n3
        if lang == 'zh':
            q_raw = "\u5148\u8bb0 {a}\uff0c\u518d\u52a0 {b}\uff0c\u7136\u540e\u62ff\u8d70 {c}\uff0c\u5269\u4e0b\u591a\u5c11\uff1f".format(
                a=captcha_num(n1, lang), b=captcha_num(n2, lang), c=captcha_num(n3, lang)
            )
        else:
            q_raw = "Start with {a}, add {b}, then remove {c}. What remains?".format(
                a=captcha_num(n1, lang), b=captcha_num(n2, lang), c=captcha_num(n3, lang)
            )
    elif mode == 'order_steps':
        n1 = random.randint(4, 16)
        n2 = random.randint(2, 9)
        n3 = random.randint(2, 9)
        ans = n1 - n2 + n3
        if ans < 1:
            n1, n2 = n2 + 8, n2
            ans = n1 - n2 + n3
        if lang == 'zh':
            q_raw = "\u628a {a} \u5148\u51cf {b}\uff0c\u518d\u52a0 {c}\uff0c\u6700\u540e\u5f97\u5230\u51e0\uff1f".format(
                a=captcha_num(n1, lang), b=captcha_num(n2, lang), c=captcha_num(n3, lang)
            )
        else:
            q_raw = "Take {a}, subtract {b}, then add {c}. What is the result?".format(
                a=captcha_num(n1, lang), b=captcha_num(n2, lang), c=captcha_num(n3, lang)
            )
    elif mode == 'decimal_add':
        n1 = random.randint(12, 58) / 10
        n2 = random.randint(3, 24) / 10
        ans = f"{n1 + n2:.1f}"
        n1_s = f"{n1:.1f}"
        n2_s = f"{n2:.1f}"
        if lang == 'zh':
            q_raw = "\u628a {a} \u548c {b} \u76f8\u52a0\uff0c\u7ed3\u679c\u662f\u591a\u5c11\uff1f".format(a=n1_s, b=n2_s)
        else:
            q_raw = "Add {a} and {b}. What is the result?".format(a=n1_s, b=n2_s)
    else:
        n1 = random.randint(7, 24)
        n2 = random.randint(2, 13)
        n3 = random.randint(1, 9)
        ans = n1 + n2 + n3
        if lang == 'zh':
            q_raw = "\u76d2\u5b50\u91cc\u6709 {a} \u679a\uff0c\u653e\u5165 {b} \u679a\uff0c\u518d\u653e\u5165 {c} \u679a\uff0c\u73b0\u5728\u662f\u51e0\u679a\uff1f".format(
                a=captcha_num(n1, lang), b=captcha_num(n2, lang), c=captcha_num(n3, lang)
            )
        else:
            q_raw = "A box has {a} items, then {b} and {c} are added. How many now?".format(
                a=captcha_num(n1, lang), b=captcha_num(n2, lang), c=captcha_num(n3, lang)
            )
    return obfuscate_captcha_text(q_raw), str(ans)

def build_captcha_markup(answer, token, lang=None):
    answer = str(answer)
    options = {answer}
    if '.' in answer:
        base = float(answer)
        offsets = [-1.2, -0.8, -0.5, -0.3, 0.2, 0.4, 0.7, 1.1]
        random.shuffle(offsets)
        for offset in offsets:
            if len(options) >= 4:
                break
            opt = base + offset
            if opt >= 0:
                options.add(f"{opt:.1f}")
        while len(options) < 4:
            options.add(f"{max(0, base + random.randint(-12, 12) / 10):.1f}")
    else:
        base = int(answer)
        offsets = [-11, -8, -5, -3, 2, 4, 6, 9, 12]
        random.shuffle(offsets)
        for offset in offsets:
            if len(options) >= 4:
                break
            opt = base + offset
            if opt >= 0:
                options.add(str(opt))
        while len(options) < 4:
            options.add(str(max(0, base + random.randint(-15, 15))))
    options = list(options)
    random.shuffle(options)
    lang = normalize_lang(lang)
    markup = InlineKeyboardMarkup()
    buttons = [InlineKeyboardButton(captcha_option_text(opt, lang), callback_data=f"captcha:{token}:{opt}") for opt in options]
    markup.row(buttons[0], buttons[1])
    markup.row(buttons[2], buttons[3])
    return markup

def generate_captcha(user_id):
    if db_check_captcha_exists(user_id): return get_text('wait_verify', user_id), None
    stat = get_cached_user_status(user_id)
    lang = normalize_lang(stat['lang'])
    q_noise, ans = build_captcha_question(lang)
    token = secrets.token_urlsafe(8)
    db_save_captcha(user_id, str(ans), token)
    return get_text('captcha_ask', user_id, q=q_noise), build_captcha_markup(ans, token, lang)

def get_help_message(is_admin, user_id):
    stat = get_cached_user_status(user_id)
    lang = normalize_lang(stat['lang'])
    help_msg = "📚 <b>机器人指令帮助</b>\n\n👉 <b>用户指令</b>\n• <code>/start</code> / <code>/help</code>: 打开菜单\n"
    if is_admin:
        help_msg += "\n👑 <b>管理员指令 (Admin)</b>\n• 回复用户转发消息 <code>/ban</code>: 封禁 30 天\n• 回复用户转发消息 <code>/unban</code>: 解封\n• 回复用户转发消息 <code>/awl</code>: 加白名单\n• 回复用户转发消息 <code>/abl</code>: 加黑名单\n• <code>/gb &lt;内容&gt;</code>: 广播\n• <code>/awl &lt;ID&gt;</code>: ID 加白\n• <code>/dwl &lt;ID&gt;</code>: ID 移出白名单\n• <code>/abl &lt;ID&gt;</code>: ID 加黑\n• <code>/dbl &lt;ID&gt;</code>: ID 移出黑名单\n• <code>/unban &lt;ID&gt;</code>: 按 ID 解封临时封禁\n• <code>/vlist wl</code>: 看白名单\n• <code>/vlist bl</code>: 看黑名单\n• <code>/vlist ban</code>: 看临时封禁名单\n• <code>/status</code>: 查看机器人和广告规则状态\n• <code>/reloadrules</code>: 手动重载第三方广告规则\n• <code>/spamtest &lt;内容&gt;</code>: 测试广告规则\n• <code>/id</code>: 查看当前 Telegram 数字 ID"
    return help_msg

def admin_reply_target(message):
    if not getattr(message, 'reply_to_message', None):
        return None
    return db_get_map(message.reply_to_message.message_id)

def admin_usage(message, text):
    m = safe_reply_to(message, text, parse_mode='HTML')
    if m:
        deleter.schedule(ADMIN_ID, m.message_id, 15)

def send_admin_menu_hint(message, command):
    lang = get_user_lang(message.from_user.id)
    examples = {
        'zh': {
            '/unban': '/unban 用户ID',
            '/awl': '/awl 用户ID',
            '/dwl': '/dwl 用户ID',
            '/abl': '/abl 用户ID',
            '/dbl': '/dbl 用户ID',
            '/gb': '/gb 广播内容',
            '/spamtest': '/spamtest 要测试的内容',
        },
        'en': {
            '/unban': '/unban user_id',
            '/awl': '/awl user_id',
            '/dwl': '/dwl user_id',
            '/abl': '/abl user_id',
            '/dbl': '/dbl user_id',
            '/gb': '/gb broadcast text',
            '/spamtest': '/spamtest text to test',
        },
    }
    example = examples[lang].get(command, command)
    if lang == 'en':
        text = f"Send directly: <code>{html.escape(example)}</code>"
        if command in ('/awl', '/dwl', '/abl', '/dbl', '/unban'):
            text += "\nYou can also reply to a forwarded user message and send this command."
    else:
        text = f"请直接发送：<code>{html.escape(example)}</code>"
        if command in ('/awl', '/dwl', '/abl', '/dbl', '/unban'):
            text += "\n也可以回复用户消息后发送对应命令。"
    admin_usage(message, text)

def send_reset_verify_prompt(message):
    lang = get_user_lang(message.from_user.id)
    if lang == 'en':
        confirm_text = "Confirm Reset"
        cancel_text = "Cancel"
        prompt = "⚠️ Reset verification status for all normal users?\nAfter confirmation, verified users must complete CAPTCHA again before sending messages."
    else:
        confirm_text = "确认清空"
        cancel_text = "取消"
        prompt = "⚠️ 确认清空所有普通用户的验证状态？\n确认后，已验证用户下次发消息需要重新完成人机验证。"
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton(confirm_text, callback_data="resetverify:confirm"),
        InlineKeyboardButton(cancel_text, callback_data="resetverify:cancel")
    )
    safe_reply_to(message, prompt, reply_markup=markup)

def send_admin_status(message):
    ai_state = f"{ai_cls.provider} 已启用" if ai_cls.enabled else '未启用'
    msg = (
        f"✅ <b>CodexBot 状态</b>\n"
        f"运行：<code>正常</code>\n"
        f"数据库：<code>SQLite</code>\n"
        f"AI 广告识别：<code>{ai_state}</code>\n"
        f"学习规则：<code>{len(_learned_keywords)} 条</code>，同步：<code>{html.escape(sync_status())}</code>\n"
        f"群聊管理：<code>{'启用' if GROUP_ENABLED else '未启用'}</code>\n"
        f"入口脚本：<code>{os.path.basename(__file__)}</code>\n\n"
        f"{html.escape(spam_rule_status_text())}"
    )
    quota_text = r2_quota_status()
    if quota_text:
        msg += f"\n\n{quota_text}"
    safe_reply_to(message, msg, parse_mode='HTML')

def send_admin_reload_rules(message):
    ok, detail = reload_spam_rules_once()
    title = "✅ 广告规则重载完成" if ok else "⚠️ 广告规则重载未成功"
    msg = f"{title}\n{html.escape(detail)}\n\n{html.escape(spam_rule_status_text())}"
    safe_reply_to(message, msg, parse_mode='HTML')

def send_admin_list(message, list_arg):
    if list_arg == 'ban':
        data = db_get_ban_list(50)
        if not data:
            safe_reply_to(message, "📋 临时封禁名单：空")
            return
        lines = []
        markup = InlineKeyboardMarkup()
        now = time.time()
        for user_id, ban_until in data:
            remain = max(0, int(ban_until - now))
            lines.append(f"• {user_id}，剩余 {remain // 60} 分钟")
            markup.add(InlineKeyboardButton(f"解封 {user_id}", callback_data=f"unban:{user_id}"))
        safe_reply_to(message, "📋 临时封禁名单:\n" + "\n".join(lines), reply_markup=markup)
        return
    list_name = 'whitelist' if list_arg == 'wl' else 'blacklist'
    data = db_get_list(list_name)
    rows = "\n".join([f"• {u[0]}" for u in data[:50]]) or "空"
    msg = f"📋 {list_name} ({len(data)}):\n" + rows
    safe_reply_to(message, msg)

def broadcast_thread(text):
    with _db_lock:
        conn = get_db_conn()
        cursor = db_execute(
            conn,
            "SELECT user_id FROM users "
            "WHERE user_id NOT IN (SELECT user_id FROM blacklist) "
            "AND (ban_until IS NULL OR ban_until <= ?) "
            "AND NOT (verified=0 AND (last_seen IS NULL OR last_seen <= 0))",
            (time.time(),),
        )
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

def spam_rule_status_text():
    with _spam_lock:
        source = SPAM_RULE_SOURCE
        total = SPAM_RULE_KEYWORD_COUNT
        remote = SPAM_RULE_REMOTE_COUNT
        updated_at = SPAM_RULE_UPDATED_AT
        last_error = SPAM_RULE_LAST_ERROR
    source_text = '第三方 URL 规则 + 内置兜底规则' if source == 'remote' else ('内置兜底规则' if source == 'fallback' else '未加载')
    updated_text = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(updated_at)) if updated_at else '未更新'
    auto_learn_text = '启用' if RULE_AUTO_LEARN_ENABLED else '关闭'
    text = (
        f"🛡️ 广告规则状态\n"
        f"来源：{source_text}\n"
        f"已生效关键词：{total}\n"
        f"第三方规则：{remote}\n"
        f"自动学习：{auto_learn_text}（同一特征 {RULE_AUTO_LEARN_THRESHOLD} 次自动确认）\n"
        f"学习特征：{len(_learned_keywords)} 条\n"
        f"更新时间：{updated_text}"
    )
    if last_error:
        text += f"\n说明：{html.escape(last_error)}"
    return text

def notify_admin_startup():
    try:
        msg = (
            f"✅ <b>CodexBot 已启动</b>\n"
            f"数据库：<code>SQLite</code>\n"
            f"入口脚本：<code>{os.path.basename(__file__)}</code>\n\n"
            f"{html.escape(spam_rule_status_text())}\n\n"
            f"第三方广告规则会在后台拉取；成功后会再通知一次。"
        )
        safe_send(bot.send_message, ADMIN_ID, msg, parse_mode='HTML')
    except Exception as e:
        logging.warning(f"Startup admin notice failed: {e}")

def notify_admin_remote_rules_loaded(remote_count, compiled_count):
    try:
        msg = (
            f"✅ <b>第三方广告规则已生效</b>\n"
            f"远程规则：<code>{remote_count}</code> 条\n"
            f"当前实际编译生效：<code>{compiled_count}</code> 条\n"
            f"规则地址：<code>{html.escape(REMOTE_SPAM_URL)}</code>"
        )
        safe_send(bot.send_message, ADMIN_ID, msg, parse_mode='HTML')
    except Exception as e:
        logging.warning(f"Remote spam rules notice failed: {e}")


def notify_admin_r2_limit(reason, class_a, class_b, account_id='1'):
    if ADMIN_ID is None:
        return
    account_tag = f"R2-{account_id}"
    recovery = rule_sync.r2_recovery_text(account_id)
    if reason == 'class_a':
        head = f"{account_tag} Class A 月配额已用满"
        body = (
            f"Class A：{class_a}，Class B：{class_b}\n已暂停该账户写入。"
            f"{f'预计 {recovery} 恢复。' if recovery else '次月 UTC 自然月自动恢复配额。'}\n"
            "本地广告判定和 GitHub 同步不受影响。"
        )
    elif reason == 'class_b':
        head = f"{account_tag} Class B 月配额已用满"
        body = (
            f"Class A：{class_a}，Class B：{class_b}\n已暂停该账户读取。"
            f"{f'预计 {recovery} 恢复。' if recovery else '次月 UTC 自然月自动恢复配额。'}\n"
            "本地广告判定和 GitHub 同步不受影响。"
        )
    elif reason == 'storage':
        head = f"{account_tag} R2 存储接近免费上限"
        body = (
            f"当前规则文本约 {class_a / 1024 / 1024:.1f} MB，已暂停 R2 写入。\n"
            "本地规则和广告判定不受影响，请清理重复或过期规则。"
        )
    else:
        head = f"{account_tag} 触发限流"
        if recovery:
            body = (
                f"已暂停该账户请求至 {recovery}。\n"
                "本地广告判定、GitHub 同步和规则缓存不受影响。"
            )
        else:
            body = "已暂停该账户请求 1 小时，期间本地广告判定、GitHub 同步和规则缓存不受影响。"
    try:
        safe_send(
            bot.send_message,
            ADMIN_ID,
            f"⚠️ {head}\n{body}",
        )
    except Exception as e:
        logging.warning(f"R2 limit admin notice failed: {e}")


def run_r2_mirror_loop():
    while True:
        try:
            sync_r2_mirrors()
        except Exception as e:
            logging.warning(f"R2 mirror sync failed: {e}")
        time.sleep(60)


@bot.message_handler(commands=['id'])
def handle_id_command(message):
    lang = get_user_lang(message.from_user.id)
    text = f"🆔 Your Telegram numeric ID is: <code>{message.from_user.id}</code>" if lang == 'en' else f"🆔 你的 Telegram 数字 ID 是：<code>{message.from_user.id}</code>"
    safe_reply_to(message, text, parse_mode='HTML')

@bot.message_handler(commands=['spamtest'])
def handle_spamtest_command(message):
    if message.chat.type == 'private' and message.from_user.id != ADMIN_ID: return
    if message.chat.type not in ('private', 'group', 'supergroup'): return
    lang = get_user_lang(message.from_user.id)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        admin_usage(message, "Usage: <code>/spamtest text to test</code>" if lang == 'en' else "用法：<code>/spamtest 要测试的内容</code>")
        return
    sample = parts[1].strip()
    blocked, score, compact, reason = explain_spam_text(sample)
    status = "会拦截" if blocked else "不会拦截"
    ai_line = "\nAI: 未启用"
    if ai_cls.enabled:
        ai_res = get_ai_spam_result(sample)
        if ai_res is None:
            ai_line = "\nAI: 无返回（超时或解析失败，看日志）"
        else:
            verdict = "广告" if ai_res.get('is_spam') else "正常"
            ai_line = f"\nAI: {verdict} - {html.escape(str(ai_res.get('reason') or ''))}"
    reply = (
        f"🧪 <b>广告规则测试</b>\n"
        f"结果：<b>{status}</b>\n"
        f"原因：{html.escape(reason)}\n"
        f"风险分：<code>{score}</code>"
        f"{ai_line}"
    )
    safe_reply_to(message, reply, parse_mode='HTML')

@bot.message_handler(commands=['status'])
def handle_status_command(message):
    if message.chat.type == 'private':
        if message.from_user.id != ADMIN_ID: return
    elif message.chat.type in ('group', 'supergroup'):
        if not can_manage_group(message.from_user.id, message.chat.id): return
    else:
        return
    send_admin_status(message)

def group_command_target(message):
    if message.chat.type not in ('group', 'supergroup'):
        return None, None
    parts = message.text.split()
    if len(parts) >= 2:
        try:
            return message.chat.id, int(parts[1])
        except (TypeError, ValueError):
            return message.chat.id, None
    reply_user = getattr(getattr(message, 'reply_to_message', None), 'from_user', None)
    return message.chat.id, getattr(reply_user, 'id', None)

@bot.message_handler(
    commands=['ban'],
    func=lambda m: m.chat.type in ('group', 'supergroup'),
)
def handle_group_ban_command(message):
    chat_id, user_id = group_command_target(message)
    if message.from_user.id != ADMIN_ID and not can_manage_group(message.from_user.id, chat_id):
        return
    if user_id is None:
        safe_reply_to(message, "用法：<code>/ban 用户ID</code>，或回复对方消息后发送 <code>/ban</code>", parse_mode='HTML')
        return
    try:
        safe_send(bot.ban_chat_member, chat_id, user_id)
        db_add_group_ban(chat_id, user_id)
        text = f"✅ ID {user_id} 已在当前群拉黑。"
    except Exception as e:
        logging.warning(f"Group manual ban failed for {user_id} in {chat_id}: {e}")
        text = "⚠️ 拉黑失败，请确认机器人有封禁成员权限。"
    safe_reply_to(message, text)

@bot.message_handler(commands=['unban'])
def handle_group_unban_command(message):
    if message.chat.type == 'private':
        if message.from_user.id != ADMIN_ID: return
        parts = message.text.split()
        target_uid = None
        if len(parts) >= 2:
            try: target_uid = int(parts[1].strip())
            except (TypeError, ValueError):
                admin_usage(message, "ID 必须是纯数字，例如：<code>/unban 123456789</code>")
                return
        else:
            target_uid = admin_reply_target(message)
        if not target_uid:
            admin_usage(message, "用法：<code>/unban 用户ID</code>，或回复用户转发消息发送 <code>/unban</code>")
            return
        db_unban_user(target_uid)
        safe_reply_to(message, f"✅ ID {target_uid} 已解除临时封禁。")
        return
    if message.chat.type not in ('group', 'supergroup'):
        return
    chat_id, user_id = group_command_target(message)
    if message.from_user.id != ADMIN_ID and not can_manage_group(message.from_user.id, chat_id):
        return
    if user_id is None:
        safe_reply_to(message, "用法：<code>/unban 用户ID</code>", parse_mode='HTML')
        return
    try:
        safe_send(bot.unban_chat_member, chat_id, user_id)
    except Exception as e:
        logging.warning(f"Group manual unban failed for {user_id} in {chat_id}: {e}")
    db_remove_group_ban(chat_id, user_id)
    safe_reply_to(message, f"✅ ID {user_id} 已解除当前群拉黑。")

@bot.message_handler(commands=['reloadrules'])
def handle_reload_rules_command(message):
    if message.chat.type == 'private':
        if message.from_user.id != ADMIN_ID: return
    elif message.chat.type in ('group', 'supergroup'):
        if not can_manage_group(message.from_user.id, message.chat.id): return
    else:
        return
    send_admin_reload_rules(message)

@bot.message_handler(commands=['resetverify'])
def handle_reset_verify_command(message):
    if message.chat.type != 'private': return
    if message.from_user.id != ADMIN_ID: return
    send_reset_verify_prompt(message)

@bot.message_handler(commands=['unban'])
def handle_unban_command(message):
    if message.chat.type != 'private': return
    if message.from_user.id != ADMIN_ID: return
    lang = get_user_lang(message.from_user.id)
    parts = message.text.split()
    target_uid = None
    if len(parts) >= 2:
        try: target_uid = int(parts[1].strip())
        except (TypeError, ValueError):
            admin_usage(message, "ID must be numeric, for example: <code>/unban 123456789</code>" if lang == 'en' else "ID 必须是纯数字，例如：<code>/unban 123456789</code>")
            return
    else:
        target_uid = admin_reply_target(message)
    if not target_uid:
        admin_usage(message, "Usage: <code>/unban user_id</code>, or reply to a forwarded user message with <code>/unban</code>" if lang == 'en' else "用法：<code>/unban 用户ID</code>，或回复用户转发消息发送 <code>/unban</code>")
        return
    db_unban_user(target_uid)
    safe_reply_to(message, f"✅ ID {target_uid} has been unbanned." if lang == 'en' else f"✅ ID {target_uid} 已解除临时封禁。")

@bot.message_handler(commands=['gb'])
def handle_broadcast_command(message):
    if message.chat.type != 'private': return
    if message.from_user.id != ADMIN_ID: return
    lang = get_user_lang(message.from_user.id)
    parts = message.text.split(maxsplit=1)
    msg_text = parts[1].strip() if len(parts) > 1 else ''
    if not msg_text:
        admin_usage(message, "Usage: <code>/gb broadcast text</code>" if lang == 'en' else "用法：<code>/gb 要广播的内容</code>")
        return
    safe_reply_to(message, "🚀 Broadcast started..." if lang == 'en' else "🚀 广播开始...")
    threading.Thread(target=broadcast_thread, args=(msg_text,), daemon=True).start()

@bot.message_handler(commands=['awl', 'dwl', 'abl', 'dbl', 'vlist'])
def handle_list_commands(message):
    if message.chat.type != 'private': return
    if message.from_user.id != ADMIN_ID: return
    lang = get_user_lang(message.from_user.id)
    cmd = message.text.split()[0].split('@', 1)[0].lower().replace('/', '')
    parts = message.text.split()
    if cmd in ['awl', 'dwl', 'abl', 'dbl']:
        target_uid = None
        if len(parts) >= 2:
            try: target_uid = int(parts[1].strip())
            except (TypeError, ValueError):
                admin_usage(message, "ID must be numeric, for example: <code>/awl 123456789</code>" if lang == 'en' else "ID 必须是纯数字，例如：<code>/awl 123456789</code>")
                return
        elif cmd in ['awl', 'abl']:
            target_uid = admin_reply_target(message)
        if not target_uid:
            if cmd in ['awl', 'abl']:
                admin_usage(message, f"Usage: <code>/{cmd} user_id</code>, or reply to a forwarded user message with <code>/{cmd}</code>" if lang == 'en' else f"用法：<code>/{cmd} 用户ID</code>，或回复用户转发消息发送 <code>/{cmd}</code>")
            else:
                admin_usage(message, f"Usage: <code>/{cmd} user_id</code>" if lang == 'en' else f"用法：<code>/{cmd} 用户ID</code>")
            return
        list_name = 'whitelist' if cmd.endswith('wl') else 'blacklist'
        if cmd.startswith('a'):
            if db_add_to_list(list_name, target_uid): safe_reply_to(message, f"✅ ID {target_uid} 已加入 {list_name}。")
            else: safe_reply_to(message, f"ℹ️ ID {target_uid} 已经在 {list_name} 中。")
        else:
            if db_remove_from_list(list_name, target_uid): safe_reply_to(message, f"✅ ID {target_uid} 已移出 {list_name}。")
            else: safe_reply_to(message, f"ℹ️ ID {target_uid} 不在 {list_name} 中。")
    elif cmd == 'vlist':
        list_arg = parts[1].lower() if len(parts) > 1 else ''
        if list_arg not in ['wl', 'bl', 'ban']:
            admin_usage(message, "Usage: <code>/vlist wl</code> for whitelist, <code>/vlist bl</code> for blacklist, <code>/vlist ban</code> for temporary bans" if lang == 'en' else "用法：<code>/vlist wl</code> 查看白名单，<code>/vlist bl</code> 查看黑名单，<code>/vlist ban</code> 查看临时封禁名单")
            return
        send_admin_list(message, list_arg)

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
        safe_delete(call.message.chat.id, call.message.message_id)
        send_menu(call.from_user.id, get_text('lang_set', call.from_user.id))
    except Exception as e: logging.warning(f"Language callback failed for {call.from_user.id}: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('captcha:'))
def handle_captcha_callback(call):
    user_id = call.from_user.id
    if not check_captcha_callback_limit(user_id):
        logging.info(f"Captcha callback rate-limited for {user_id}")
        return
    parts = call.data.split(':', 2)
    if len(parts) != 3:
        try: safe_send(bot.answer_callback_query, call.id, "Invalid")
        except Exception as e: logging.warning(f"Invalid captcha callback answer failed: {e}")
        return
    _, token, answer = parts
    if not db_has_captcha_token(user_id, token):
        try: safe_send(bot.answer_callback_query, call.id, get_text('captcha_stale', user_id))
        except Exception as e: logging.warning(f"Stale captcha callback answer failed for {user_id}: {e}")
        return
    if not claim_captcha_attempt(user_id, token):
        logging.info(f"Duplicate captcha attempt ignored for {user_id}")
        return
    result, data = db_check_and_verify(user_id, answer, token)
    try:
        if result == 'success':
            safe_send(bot.answer_callback_query, call.id, "OK")
            try: safe_delete(call.message.chat.id, call.message.message_id)
            except Exception as e: logging.debug(f"Captcha message delete failed: {e}")
            send_menu(user_id, VERIFIED_ZH if normalize_lang(get_cached_user_status(user_id).get('lang')) == 'zh' else VERIFIED_EN)
        elif result in ['timeout_ban', 'fail_ban']:
            key = 'captcha_timeout' if result == 'timeout_ban' else 'captcha_fail'
            safe_send(bot.answer_callback_query, call.id, get_text(key, user_id), show_alert=True)
        elif result == 'wrong_answer':
            try: safe_delete(call.message.chat.id, call.message.message_id)
            except Exception as e: logging.debug(f"Wrong captcha message delete failed: {e}")
            safe_send(bot.answer_callback_query, call.id, get_text('captcha_wrong', user_id))
            send_captcha_after_cooldown(user_id)
        elif result == 'stale_captcha':
            safe_send(bot.answer_callback_query, call.id, get_text('captcha_stale', user_id))
        else:
            safe_send(bot.answer_callback_query, call.id, get_text('wait_verify', user_id), show_alert=True)
    except Exception as e:
        logging.warning(f"Captcha callback handling failed for {user_id}: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('unban:'))
def handle_unban_callback(call):
    if call.from_user.id != ADMIN_ID:
        try: safe_send(bot.answer_callback_query, call.id, "Only admin")
        except Exception as e: logging.warning(f"Unban non-admin answer failed: {e}")
        return
    try:
        target_uid = int(call.data.split(':', 1)[1])
    except Exception:
        try: safe_send(bot.answer_callback_query, call.id, "Invalid")
        except Exception as e: logging.warning(f"Invalid unban callback answer failed: {e}")
        return
    db_unban_user(target_uid)
    try:
        safe_send(bot.answer_callback_query, call.id, "已解封")
        safe_send(bot.edit_message_text, f"✅ 已解除临时封禁\n用户: <code>{target_uid}</code>", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=None)
    except Exception as e:
        logging.warning(f"Unban callback failed for {target_uid}: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('resetverify:'))
def handle_reset_verify_callback(call):
    if call.from_user.id != ADMIN_ID:
        try: safe_send(bot.answer_callback_query, call.id, "Only admin")
        except Exception as e: logging.warning(f"Reset verify non-admin answer failed: {e}")
        return
    lang = get_user_lang(call.from_user.id)
    action = call.data.split(':', 1)[1]
    try:
        if action == 'confirm':
            changed = db_reset_all_verifications()
            if lang == 'en':
                text = f"✅ Verification status reset.\nAffected users: <code>{changed}</code>\nNormal users will need to complete CAPTCHA again before sending messages."
                answer = "Reset done"
            else:
                text = f"✅ 已清空验证状态。\n受影响用户数: <code>{changed}</code>\n普通用户下次发消息会重新进入验证流程。"
                answer = "已清空"
            safe_send(bot.answer_callback_query, call.id, answer)
            safe_send(bot.edit_message_text, text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=None)
        else:
            safe_send(bot.answer_callback_query, call.id, "Canceled" if lang == 'en' else "已取消")
            safe_send(bot.edit_message_text, "Verification reset canceled." if lang == 'en' else "已取消清空验证状态。", call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception as e:
        logging.warning(f"Reset verify callback failed: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('spam_ban:') or call.data.startswith('spam_keep:'))
def handle_spam_action_callback(call):
    if call.from_user.id != ADMIN_ID:
        try: safe_send(bot.answer_callback_query, call.id, "Only admin")
        except Exception as e: logging.warning(f"Spam action non-admin answer failed: {e}")
        return
    try:
        action, raw_uid = call.data.split(':', 1)
        target_uid = int(raw_uid)
    except Exception:
        try: safe_send(bot.answer_callback_query, call.id, "Invalid")
        except Exception as e: logging.warning(f"Invalid spam action answer failed: {e}")
        return

    if action == 'spam_ban':
        db_ban_user(target_uid, MAX_BAN_DURATION)
        text = f"🚫 <b>已封禁用户</b>\n用户: <code>{target_uid}</code>\n操作: 管理员确认封禁。"
        answer = "已封禁"
    else:
        text = f"✅ <b>已保留用户</b>\n用户: <code>{target_uid}</code>\n操作: 本次广告已拦截，不封禁用户。"
        answer = "不封禁"
    try:
        safe_send(bot.edit_message_text, text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=None)
        safe_send(bot.answer_callback_query, call.id, answer)
    except Exception as e:
        logging.warning(f"Spam action callback failed for {target_uid}: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith('spam_learn:') or call.data.startswith('spam_ignore:'))
def handle_spam_learn_callback(call):
    if call.from_user.id != ADMIN_ID:
        try: safe_send(bot.answer_callback_query, call.id, "Only admin")
        except Exception as e: logging.warning(f"Learn non-admin answer failed: {e}")
        return
    try:
        action, raw = call.data.split(':', 1)
        uid_str, content_hash = raw.split(':', 1)
        user_id = int(uid_str)
    except Exception:
        try: safe_send(bot.answer_callback_query, call.id, "Invalid")
        except Exception as e: logging.warning(f"Invalid learn callback answer failed: {e}")
        return
    try:
        if action == 'spam_learn':
            db_set_feedback_confirmed(content_hash, True)
            features = db_feedback_features(content_hash)
            refresh_learned_rules()
            if features:
                sync_pending_learned_rules_async()
            text = f"🧠 <b>已学习规则</b>\n用户: <code>{user_id}</code>\n特征数: <code>{len(features)}</code>"
            answer = "已学习"
        else:
            db_set_feedback_confirmed(content_hash, False)
            refresh_learned_rules()
            text = f"⚪ <b>已忽略样本</b>\n用户: <code>{user_id}</code>"
            answer = "已忽略"
        safe_send(bot.edit_message_text, text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=None)
        safe_send(bot.answer_callback_query, call.id, answer)
    except Exception as e:
        logging.warning(f"Learn callback failed for {user_id}: {e}")


@bot.message_handler(commands=['start', 'help', 'menu'])
def send_welcome_handler(message):
    user_id = message.from_user.id
    if message.chat.type in ('group', 'supergroup'):
        cmd = message.text.split()[0].split('@', 1)[0].lower()
        if cmd != '/help':
            return
        if get_user_lang(user_id) == 'en':
            help_msg = (
                "📚 <b>Group commands</b>\n"
                "• <code>/id</code>: Show Telegram ID\n"
                "• <code>/help</code>: This help\n"
                "• <code>/spamtest text</code>: Test spam rules\n\n"
                "Group admins: <code>/status</code>, <code>/reloadrules</code>, <code>/ban</code>, <code>/unban</code>"
            )
        else:
            help_msg = (
                "📚 <b>群内指令</b>\n"
                "• <code>/id</code>: 查看数字 ID\n"
                "• <code>/help</code>: 本帮助\n"
                "• <code>/spamtest 内容</code>: 测试广告规则\n\n"
                "群管理员：<code>/status</code>、<code>/reloadrules</code>、<code>/ban</code>、<code>/unban</code>"
            )
        safe_reply_to(message, help_msg, parse_mode='HTML')
        return
    if message.chat.type != 'private': return
    db_touch_user(user_id)
    user_status = get_cached_user_status(user_id)
    if user_status['bl']: return
    deleter.schedule(user_id, message.message_id, MSG_AUTO_DELETE_DELAY)
    if user_id != ADMIN_ID and check_flood(user_id):
        db_ban_user(user_id, FLOOD_PENALTY_TIME)
        return
    cmd = message.text.split()[0].split('@', 1)[0].lower()
    if cmd == '/help':
        m = send_long_message(user_id, get_help_message(user_id==ADMIN_ID, user_id), parse_mode='HTML')
        deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
        send_menu(user_id)
    elif cmd in ['/start', '/menu']:
        if user_status.get('lang'):
            send_menu(user_id)
        else: ask_language(user_id)

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id == ADMIN_ID and not getattr(m, 'reply_to_message', None), content_types=['text'])
def handle_admin_menu(message):
    user_id = message.from_user.id
    db_touch_user(user_id)
    user_status = get_cached_user_status(user_id)
    lang = normalize_lang(user_status.get('lang'))
    text = message.text or ''
    if text.startswith('/'):
        return
    menu_contact_values = {STRINGS['menu_contact']['zh'], STRINGS['menu_contact']['en']}
    menu_help_values = {STRINGS['menu_help']['zh'], STRINGS['menu_help']['en']}
    menu_lang_values = {STRINGS['menu_lang']['zh'], STRINGS['menu_lang']['en']}
    admin_status_values = {STRINGS['admin_menu_status']['zh'], STRINGS['admin_menu_status']['en']}
    admin_reload_values = {STRINGS['admin_menu_reload_rules']['zh'], STRINGS['admin_menu_reload_rules']['en']}
    admin_ban_values = {STRINGS['admin_menu_ban_list']['zh'], STRINGS['admin_menu_ban_list']['en']}
    admin_wl_values = {STRINGS['admin_menu_wl']['zh'], STRINGS['admin_menu_wl']['en']}
    admin_bl_values = {STRINGS['admin_menu_bl']['zh'], STRINGS['admin_menu_bl']['en']}
    admin_unban_values = {STRINGS['admin_menu_unban']['zh'], STRINGS['admin_menu_unban']['en']}
    admin_awl_values = {STRINGS['admin_menu_awl']['zh'], STRINGS['admin_menu_awl']['en']}
    admin_dwl_values = {STRINGS['admin_menu_dwl']['zh'], STRINGS['admin_menu_dwl']['en']}
    admin_abl_values = {STRINGS['admin_menu_abl']['zh'], STRINGS['admin_menu_abl']['en']}
    admin_dbl_values = {STRINGS['admin_menu_dbl']['zh'], STRINGS['admin_menu_dbl']['en']}
    admin_resetverify_values = {STRINGS['admin_menu_resetverify']['zh'], STRINGS['admin_menu_resetverify']['en']}
    admin_broadcast_values = {STRINGS['admin_menu_broadcast']['zh'], STRINGS['admin_menu_broadcast']['en']}
    admin_spamtest_values = {STRINGS['admin_menu_spamtest']['zh'], STRINGS['admin_menu_spamtest']['en']}
    admin_id_values = {STRINGS['admin_menu_id']['zh'], STRINGS['admin_menu_id']['en']}
    if text in menu_lang_values:
        ask_language(user_id, force=True)
    elif text in admin_status_values:
        send_admin_status(message)
    elif text in admin_reload_values:
        send_admin_reload_rules(message)
    elif text in admin_ban_values:
        send_admin_list(message, 'ban')
    elif text in admin_wl_values:
        send_admin_list(message, 'wl')
    elif text in admin_bl_values:
        send_admin_list(message, 'bl')
    elif text in admin_unban_values:
        send_admin_menu_hint(message, '/unban')
    elif text in admin_awl_values:
        send_admin_menu_hint(message, '/awl')
    elif text in admin_dwl_values:
        send_admin_menu_hint(message, '/dwl')
    elif text in admin_abl_values:
        send_admin_menu_hint(message, '/abl')
    elif text in admin_dbl_values:
        send_admin_menu_hint(message, '/dbl')
    elif text in admin_resetverify_values:
        send_reset_verify_prompt(message)
    elif text in admin_broadcast_values:
        send_admin_menu_hint(message, '/gb')
    elif text in admin_spamtest_values:
        send_admin_menu_hint(message, '/spamtest')
    elif text in admin_id_values:
        id_text = f"🆔 Your Telegram numeric ID is: <code>{user_id}</code>" if lang == 'en' else f"🆔 你的 Telegram 数字 ID 是：<code>{user_id}</code>"
        safe_reply_to(message, id_text, parse_mode='HTML')
    elif text in menu_help_values:
        m = send_long_message(user_id, get_help_message(True, user_id), parse_mode='HTML')
        deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
        send_menu(user_id)
    elif text in menu_contact_values:
        send_menu(user_id, get_menu_text(user_id))

def judge_join_request_spam(user, profile_text, bio=''):
    profile_fields = [
        getattr(user, 'first_name', None),
        getattr(user, 'last_name', None),
        getattr(user, 'username', None),
        bio,
    ]
    for field in profile_fields:
        if field and is_spam_text(field):
            return True, '用户名或资料命中本地广告规则'
    profile_score = 0
    try:
        profile_score = spam_risk_score(profile_text)
        if profile_score >= SPAM_PROFILE_BLOCK_SCORE:
            return True, f'资料风险分 {profile_score} >= {SPAM_PROFILE_BLOCK_SCORE}'
    except Exception as e:
        logging.warning(f"Join profile risk scoring failed: {e}")
    if AI_PROFILE_CHECK and should_run_ai_check(profile_score):
        ai_result = get_ai_spam_result(profile_text)
        if ai_result and ai_result.get('is_spam'):
            return True, f"AI判定：{ai_result.get('reason') or '广告号'}"
    return False, '未发现广告特征'


def user_follows_required_channel(user_id):
    if not GROUP_JOIN_REQUIRED_CHANNEL:
        return True
    cached = _channel_member_cache.get(user_id)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    follows = False
    try:
        member = bot.get_chat_member(GROUP_JOIN_REQUIRED_CHANNEL, user_id)
        follows = getattr(member, 'status', None) in ('creator', 'administrator', 'member')
    except Exception as e:
        logging.warning(f"Required channel member check failed for {user_id}: {e}")
    _channel_member_cache[user_id] = (time.monotonic() + CHANNEL_MEMBER_CACHE_TTL, follows)
    return follows


def reject_spam_join(chat_id, user_id):
    safe_send(bot.decline_chat_join_request, chat_id, user_id)
    try:
        safe_send(bot.ban_chat_member, chat_id, user_id)
        db_add_group_ban(chat_id, user_id)
    except Exception as e:
        logging.warning(f"Join spam ban failed for {user_id} in {chat_id}: {e}")
    try:
        lang = get_user_lang(user_id)
        appeal_text = (
            "入群申请被拒绝。如认为误判，可直接私聊机器人说明情况，内容会先经过广告审核再转给管理员。"
            if lang == 'zh' else
            "Your join request was declined. If you believe this is a mistake, message the bot directly; content is checked for spam before reaching the admin."
        )
        safe_send(bot.send_message, user_id, appeal_text, parse_mode='HTML')
    except Exception as e:
        logging.warning(f"Join appeal notice failed for {user_id}: {e}")


def record_group_join_pending(chat_id, user_id, is_spam, notice_message_id=None):
    key = (chat_id, user_id)
    with _group_join_lock:
        group_join_pending[key] = {
            'deadline': time.time() + GROUP_JOIN_REVIEW_TIMEOUT,
            'is_spam': bool(is_spam),
            'notice_message_id': notice_message_id,
        }


def remove_group_join_pending(chat_id, user_id):
    with _group_join_lock:
        group_join_pending.pop((chat_id, user_id), None)


def resolve_group_join_pending(chat_id, user_id, is_spam, notice_message_id=None):
    if is_spam:
        reject_spam_join(chat_id, user_id)
        text = (
            f"🚫 <b>已自动拒绝并拉黑</b>\n"
            f"群: <code>{chat_id}</code>\n"
            f"用户: <code>{user_id}</code>\n"
            f"处理: 广告判定，管理员超时自动执行"
        )
    else:
        safe_send(bot.approve_chat_join_request, chat_id, user_id)
        text = (
            f"✅ <b>已自动通过</b>\n"
            f"群: <code>{chat_id}</code>\n"
            f"用户: <code>{user_id}</code>\n"
            f"处理: 规则判定正常，管理员超时自动执行"
        )
    if notice_message_id:
        try:
            safe_send(bot.edit_message_text, text, chat_id, notice_message_id, parse_mode='HTML', reply_markup=None)
        except Exception as e:
            logging.warning(f"Group join timeout notice edit failed for {chat_id}: {e}")


def run_group_join_timeout_check():
    while True:
        time.sleep(10)
        now = time.time()
        due = []
        with _group_join_lock:
            for key, entry in list(group_join_pending.items()):
                if entry['deadline'] <= now:
                    due.append((key, entry))
            for key, _ in due:
                group_join_pending.pop(key, None)
        for (chat_id, user_id), entry in due:
            try:
                resolve_group_join_pending(chat_id, user_id, entry['is_spam'], entry.get('notice_message_id'))
            except Exception as e:
                logging.warning(f"Group join timeout resolve failed for {user_id} in {chat_id}: {e}")
                with _group_join_lock:
                    entry['deadline'] = time.time() + 60
                    group_join_pending[(chat_id, user_id)] = entry


def notify_group_join_admins(chat_id, user, is_spam, reason, action):
    user_id = user.id
    full_name = get_user_profile_text(user).strip() or 'User'
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("通过", callback_data=f"gj_approve:{chat_id}:{user_id}"),
        InlineKeyboardButton("拒绝", callback_data=f"gj_decline:{chat_id}:{user_id}"),
    )
    action_text = {
        'approved': '已自动通过',
        'declined': '已自动拒绝',
        'pending': '待管理员处理',
    }.get(action, action)
    msg = (
        f"👥 <b>入群申请审核</b>\n"
        f"群: <code>{chat_id}</code>\n"
        f"用户: <a href='tg://user?id={user_id}'>{html.escape(full_name)}</a>\n"
        f"ID: <code>{user_id}</code>\n"
        f"判定: {'广告号' if is_spam else '正常'}\n"
        f"原因: {html.escape(reason)}\n"
        f"操作: {action_text}"
    )
    group_notice_id = None
    try:
        sent = safe_send(bot.send_message, chat_id, msg, parse_mode='HTML', reply_markup=markup)
        group_notice_id = getattr(sent, 'message_id', None)
    except Exception as e:
        logging.warning(f"Group join notice to group {chat_id} failed: {e}")
    for admin_id in GROUP_ADMIN_IDS:
        try:
            safe_send(bot.send_message, admin_id, msg, parse_mode='HTML', reply_markup=markup)
        except Exception as e:
            logging.warning(f"Group join notice failed for admin {admin_id}: {e}")
    return group_notice_id


@bot.chat_join_request_handler()
def handle_chat_join_request(req):
    if not GROUP_ENABLED or not GROUP_JOIN_APPROVE:
        return
    chat = getattr(req, 'chat', None)
    user = getattr(req, 'from_user', None) or getattr(req, 'user', None)
    if not chat or not user:
        return
    chat_id = getattr(chat, 'id', None)
    if not group_enabled_for(chat_id):
        return
    user_id = user.id
    if GROUP_JOIN_REQUIRED_CHANNEL and not user_follows_required_channel(user_id):
        try:
            safe_send(bot.decline_chat_join_request, chat_id, user_id)
        except Exception as e:
            logging.warning(f"Join channel requirement decline failed for {user_id}: {e}")
        if str(GROUP_JOIN_REQUIRED_CHANNEL).lstrip('-').isdigit():
            channel_display = f"<code>{GROUP_JOIN_REQUIRED_CHANNEL}</code>"
        else:
            channel_display = f"@{GROUP_JOIN_REQUIRED_CHANNEL}"
        try:
            safe_send(
                bot.send_message,
                user_id,
                f"请先关注频道 {channel_display}，关注后重新点击加入申请，机器人会继续审核。",
                parse_mode='HTML',
            )
        except Exception as e:
            logging.warning(f"Join channel requirement notice failed for {user_id}: {e}")
        return
    profile_text = get_user_profile_text(user)
    bio = getattr(req, 'bio', None) or getattr(user, 'bio', None) or ''
    is_spam, reason = judge_join_request_spam(user, profile_text, bio)
    action = 'pending'
    if is_spam:
        try:
            reject_spam_join(chat_id, user_id)
            action = 'declined'
        except Exception as e:
            logging.warning(f"Group join auto reject failed for {user_id}: {e}")
            action = 'pending'
    elif GROUP_AUTO_APPROVE:
        try:
            safe_send(bot.approve_chat_join_request, chat_id, user_id)
            action = 'approved'
        except Exception as e:
            logging.warning(f"Group join auto approve failed for {user_id}: {e}")
            action = 'pending'
    notice_message_id = notify_group_join_admins(chat_id, user, is_spam, reason, action)
    if action == 'pending':
        record_group_join_pending(chat_id, user_id, is_spam, notice_message_id)


def notify_group_spam(chat_id, message, user_id, reason, score, actions):
    content = getattr(message, 'text', None) or getattr(message, 'caption', None) or ''
    action_text = '、'.join(actions)
    msg = (
        f"🚨 <b>群聊广告检测</b>\n"
        f"群: <code>{chat_id}</code>\n"
        f"用户: <code>{user_id}</code>\n"
        f"原因: {html.escape(reason)}\n"
        f"风险分: <code>{score}</code>\n"
        f"操作: {action_text}"
    )
    if content:
        msg += f"\n内容摘要: {html.escape(content[:200])}"
    content_hash = db_save_spam_feedback(content, 'group')
    markup = None
    if content_hash:
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("学习规则", callback_data=f"spam_learn:{user_id}:{content_hash}"),
            InlineKeyboardButton("不学习", callback_data=f"spam_ignore:{user_id}:{content_hash}")
        )
    for admin_id in GROUP_ADMIN_IDS:
        try:
            safe_send(bot.send_message, admin_id, msg, parse_mode='HTML', reply_markup=markup)
        except Exception as e:
            logging.warning(f"Group spam notice failed for admin {admin_id}: {e}")


def should_ban_group_spam(chat_id, user_id):
    """群内广告分级：返回 True 表示本次应永久封，False 表示仅警告。

    GROUP_SPAM_WARN_LIMIT<=0 时首次即封；否则先累计警告次数，
    达到限制后再封。强特征词不走这里，由调用方直接封。
    """
    limit = GROUP_SPAM_WARN_LIMIT
    if limit <= 0:
        return True
    with _group_spam_warn_lock:
        key = (chat_id, user_id)
        count = group_spam_warn_state.get(key, 0) + 1
        if count >= limit:
            group_spam_warn_state[key] = count
            return True
        group_spam_warn_state[key] = count
        return False


def get_group_spam_warn_count(chat_id, user_id):
    with _group_spam_warn_lock:
        return group_spam_warn_state.get((chat_id, user_id), 0)


def clear_group_spam_warn(chat_id, user_id):
    with _group_spam_warn_lock:
        group_spam_warn_state.pop((chat_id, user_id), None)


def process_group_spam_message(message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    if can_manage_group(user_id, message.chat.id):
        return
    if get_cached_user_status(user_id).get('bl'):
        return
    blocked, score, compact, reason = analyze_spam_message(message)
    if not blocked:
        return

    chat_id = message.chat.id
    actions = []
    if GROUP_DELETE_SPAM:
        try:
            safe_delete(chat_id, message.message_id)
            actions.append('删除消息')
        except Exception as e:
            logging.warning(f"Group spam delete failed: {e}")
    if GROUP_BAN_ON_SPAM:
        content = getattr(message, 'text', None) or getattr(message, 'caption', None) or ''
        # 强特征词（U币等）任何时候直接永久封，不吃警告
        hard_hit = has_hard_block_term(content)
        if hard_hit or should_ban_group_spam(chat_id, user_id):
            try:
                safe_send(bot.ban_chat_member, chat_id, user_id)
                db_add_group_ban(chat_id, user_id)
                actions.append('永久封禁')
                clear_group_spam_warn(chat_id, user_id)
            except Exception as e:
                logging.warning(f"Group spam ban failed for {user_id}: {e}")
        else:
            actions.append(f'警告（第 {get_group_spam_warn_count(chat_id, user_id)} 次，再犯永久封）')
    if not actions:
        actions.append('仅通知管理员')

    notify_group_spam(chat_id, message, user_id, reason, score, actions)


@bot.message_handler(
    func=lambda m: m.chat.type in ('group', 'supergroup') and group_enabled_for(getattr(m.chat, 'id', None)),
    content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation', 'video_note', 'location', 'contact', 'dice'],
)
def handle_group_message(message):
    process_group_spam_message(message)


@bot.edited_message_handler(func=lambda m: getattr(m, 'chat', None) and getattr(m.chat, 'type', None) in ('group', 'supergroup') and group_enabled_for(getattr(m.chat, 'id', None)))
def handle_group_edited_message(message):
    process_group_spam_message(message)


@bot.callback_query_handler(func=lambda call: call.data.startswith('gj_approve:') or call.data.startswith('gj_decline:'))
def handle_group_join_callback(call):
    try:
        action, raw_target = call.data.split(':', 1)
        chat_id_str, user_id_str = raw_target.split(':', 1)
        chat_id = int(chat_id_str)
        user_id = int(user_id_str)
    except Exception:
        try: safe_send(bot.answer_callback_query, call.id, "Invalid")
        except Exception as e: logging.warning(f"Invalid group join callback answer failed: {e}")
        return
    if not can_manage_group(call.from_user.id, chat_id):
        try: safe_send(bot.answer_callback_query, call.id, "Only admin")
        except Exception as e: logging.warning(f"Group join non-admin answer failed: {e}")
        return

    callback_message = getattr(call, 'message', None)
    with _group_join_lock:
        is_pending = (chat_id, user_id) in group_join_pending
    if not is_pending and callback_message is not None and getattr(callback_message, 'reply_markup', None) is None:
        try:
            safe_send(bot.answer_callback_query, call.id, "已处理")
        except Exception as e:
            logging.warning(f"Group join already handled answer failed: {e}")
        return

    try:
        if action == 'gj_approve':
            safe_send(bot.approve_chat_join_request, chat_id, user_id)
            text = f"✅ <b>已通过入群申请</b>\n群: <code>{chat_id}</code>\n用户: <code>{user_id}</code>"
            answer = "已通过"
        else:
            safe_send(bot.decline_chat_join_request, chat_id, user_id)
            text = f"🚫 <b>已拒绝入群申请</b>\n群: <code>{chat_id}</code>\n用户: <code>{user_id}</code>"
            answer = "已拒绝"
        remove_group_join_pending(chat_id, user_id)
        safe_send(bot.edit_message_text, text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=None)
        safe_send(bot.answer_callback_query, call.id, answer)
    except Exception as e:
        logging.warning(f"Group join callback failed for {user_id}: {e}")
        try: safe_send(bot.answer_callback_query, call.id, "操作失败，申请可能已处理")
        except Exception as answer_error:
            logging.warning(f"Group join callback answer failed: {answer_error}")


@bot.edited_message_handler(func=lambda m: getattr(m, 'chat', None) and getattr(m.chat, 'type', None) == 'private')
def handle_edited_message(message):
    if message.from_user.id == ADMIN_ID: return
    user_id = message.from_user.id
    user_status = get_cached_user_status(user_id)

    if user_status['bl']: return
    if user_status['ban_until'] > time.time(): return

    if not user_status['wl']:
        blocked, score, compact, reason = analyze_spam_message(message)
        if blocked:
            db_ban_user(user_id, MAX_BAN_DURATION)
            try:
                safe_delete(message.chat.id, message.message_id)
                m = safe_send(bot.send_message, user_id, get_text('spam_edit_ban', user_id), parse_mode='HTML')
                deleter.schedule(user_id, m.message_id, 30)
                content = getattr(message, 'text', None) or getattr(message, 'caption', None) or ''
                alert_msg = f"⚠️ <b>已拦截违规编辑</b>\n用户: <code>{user_id}</code>\n原因: {html.escape(reason)}\n风险分: <code>{score}</code>\n操作: 已封禁并删除消息。"
                content_hash = db_save_spam_feedback(content, 'edit')
                markup = None
                if content_hash:
                    markup = InlineKeyboardMarkup()
                    markup.row(
                        InlineKeyboardButton("学习规则", callback_data=f"spam_learn:{user_id}:{content_hash}"),
                        InlineKeyboardButton("不学习", callback_data=f"spam_ignore:{user_id}:{content_hash}")
                    )
                safe_send(bot.send_message, ADMIN_ID, alert_msg, parse_mode='HTML', reply_markup=markup)
            except Exception as e: logging.warning(f"Edited spam handling failed for {user_id}: {e}")
            return

    try:
        content = getattr(message, 'text', None) or getattr(message, 'caption', None) or ''
        if not content:
            content = f"[{message.content_type}]"
        user = message.from_user
        full_name = ((user.first_name or '') + ' ' + (user.last_name or '')).strip() or 'User'
        username = f"@{user.username}" if user.username else "No Username"
        edit_msg = (
            f"✏️ <b>用户编辑了消息</b>\n"
            f"用户: <a href='tg://user?id={user_id}'>{html.escape(full_name)}</a>\n"
            f"用户名: <code>{html.escape(username)}</code>\n"
            f"ID: <code>{user_id}</code>\n\n"
            f"<b>编辑后内容:</b>\n{html.escape(content[:3500])}"
        )
        sent = safe_send(bot.send_message, ADMIN_ID, edit_msg, parse_mode='HTML')
        if sent:
            db_save_map(sent.message_id, user_id)
    except Exception as e:
        logging.warning(f"Edited message notify failed for {user_id}: {e}")

def handle_captcha_text_answer(user_id, text, message):
    if not CAPTCHA_TEXT_FALLBACK or message.content_type != 'text':
        return False
    if not db_check_captcha_exists(user_id):
        return False
    result, data = db_check_and_verify(user_id, input_ans=text, token=None)
    try:
        deleter.schedule(user_id, message.message_id, MSG_AUTO_DELETE_DELAY)
        if result == 'success':
            lang = normalize_lang(get_cached_user_status(user_id).get('lang'))
            send_menu(user_id, VERIFIED_ZH if lang == 'zh' else VERIFIED_EN)
            return True
        if result in ('timeout_ban', 'fail_ban'):
            key = 'captcha_timeout' if result == 'timeout_ban' else 'captcha_fail'
            m = safe_send(bot.send_message, user_id, get_text(key, user_id))
            deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
            return True
        if result == 'wrong_answer':
            m = safe_send(bot.send_message, user_id, get_text('captcha_wrong', user_id))
            deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
            send_captcha_after_cooldown(user_id)
            return True
    except Exception as e:
        logging.warning(f"Captcha text answer failed for {user_id}: {e}")
    return False

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id != ADMIN_ID, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation', 'video_note', 'location', 'contact', 'dice'])
def handle_incoming(message):
    if not check_global_limit(): return
    user_id = message.from_user.id
    db_touch_user(user_id)
    user_status = get_cached_user_status(user_id)
    text = message.text or ''

    if user_status['bl']:
        try:
            m = safe_send(bot.send_message, user_id, get_text('blacklist_ban', user_id), parse_mode='HTML')
            deleter.schedule(user_id, message.message_id, 1)
            deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
        except Exception as e: logging.warning(f"Blacklist notice failed for {user_id}: {e}")
        return

    if message.content_type == 'text' and text in menu_values('menu_lang'):
        ask_language(user_id, force=True)
        deleter.schedule(user_id, message.message_id, MSG_AUTO_DELETE_DELAY)
        return

    is_whitelisted = user_status['wl']
    if user_status['ban_until'] > time.time():
        return

    if not is_whitelisted:
        if check_flood(user_id, getattr(message, 'media_group_id', None)):
            db_ban_user(user_id, FLOOD_PENALTY_TIME)
            m = safe_send(bot.send_message, user_id, get_text('flood_ban', user_id))
            deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
            deleter.schedule(user_id, message.message_id, MSG_AUTO_DELETE_DELAY)
            return

        spam_analysis = analyze_spam_message(message)
        if spam_analysis[0]:
            block_spam_message(message, user_id, analysis=spam_analysis)
            return

        if not user_status['verified']:
            if handle_captcha_text_answer(user_id, text, message):
                return
            deleter.schedule(user_id, message.message_id, MSG_AUTO_DELETE_DELAY)
            if should_send_captcha_prompt(user_id):
                q, markup = generate_captcha(user_id)
                m = safe_send(bot.send_message, user_id, q, parse_mode='HTML', reply_markup=markup)
                deleter.schedule(user_id, m.message_id, CAPTCHA_DELETE_DELAY)
            return

    lang = normalize_lang(user_status.get('lang'))
    if message.content_type == 'text':
        if is_user_menu_text(text):
            if text in menu_values('menu_lang'):
                ask_language(user_id, force=True)
            elif text in menu_values('menu_help'):
                m = safe_send(bot.send_message, user_id, get_user_faq(user_id))
                deleter.schedule(user_id, m.message_id, MSG_AUTO_DELETE_DELAY)
            else:
                send_menu(user_id, get_menu_text(user_id))
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
    
    if not getattr(message, 'media_group_id', None) and should_send_auto_reply(user_id):
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
        logging.info(f"Admin reply sent to {target_uid}")
    except Exception as e:
        logging.exception(f"Admin reply failed for {target_uid}: {e}")
        try:
            m = safe_reply_to(message, "❌ 发送失败 (用户可能屏蔽了机器人)")
            deleter.schedule(ADMIN_ID, m.message_id, 5)
        except Exception as notice_error:
            logging.warning(f"Admin failure notice failed: {notice_error}")

if __name__ == "__main__":
    init_db()
    load_fallback_spam_rules()
    load_learned_keywords()
    rule_sync.r2_limit_notify_handler = notify_admin_r2_limit
    threading.Thread(target=run_r2_mirror_loop, daemon=True).start()
    threading.Thread(target=update_spam_rules, daemon=True).start()
    threading.Thread(target=cleanup_dict, daemon=True).start()
    threading.Thread(target=run_group_join_timeout_check, daemon=True).start()
    sync_pending_learned_rules_async()
    setup_bot_menus()
    logging.info("Bot Started.")
    notify_admin_startup()
    while True:
        try: bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            logging.exception(f"Polling crashed, restarting in 5s: {e}")
            time.sleep(5)
