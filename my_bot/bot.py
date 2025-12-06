# -*- coding: utf-8 -*-
import os
import logging
import re
import time
import asyncio
import sqlite3
import random
import unicodedata
from typing import Optional, List, Tuple
from telegram import Update, Message, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import RetryAfter, BadRequest
import httpx

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

OWNER_ID_STR = os.getenv('OWNER_ID')
OWNER_ID = 0
if not OWNER_ID_STR:
    logger.error("致命错误: 环境变量 OWNER_ID 未设置!")
    exit(1)
try:
    OWNER_ID = int(OWNER_ID_STR)
    logger.info(f"OWNER_ID = {OWNER_ID}")
except Exception:
    logger.error("OWNER_ID 不是有效整数")
    exit(1)

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("致命错误: 环境变量 BOT_TOKEN 未设置!")
    exit(1)

DEFAULT_SPAM_RULES_URL = "https://raw.githubusercontent.com/RGB-Outl4w/zapper-TGAB/main/spam_phrases.txt"
SPAM_RULES_URL = os.getenv('SPAM_RULES_URL', DEFAULT_SPAM_RULES_URL)
CUSTOM_SPAM_KEYWORDS = os.getenv('CUSTOM_SPAM_KEYWORDS', "")
PORT = int(os.getenv('PORT', 8080))
ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS', str(OWNER_ID)).split(',') if x.strip()]
ADMIN_GROUP_ID = int(os.getenv('ADMIN_GROUP_ID')) if os.getenv('ADMIN_GROUP_ID') else None
BACKUP_GROUP_ID = int(os.getenv('BACKUP_GROUP_ID')) if os.getenv('BACKUP_GROUP_ID') else None
DB_FILE = os.getenv('DB_FILE', 'bot_data.db')
VERIFICATION_TIMEOUT = int(os.getenv('VERIFICATION_TIMEOUT', '300'))
BLOCK_THRESHOLD = int(os.getenv('BLOCK_THRESHOLD', '5'))
RATE_LIMIT_WINDOW = int(os.getenv('RATE_LIMIT_WINDOW', '10'))
RATE_LIMIT_COUNT = int(os.getenv('RATE_LIMIT_COUNT', '8'))
CAPTCHA_MODE = os.getenv('CAPTCHA_MODE', 'math')

def normalize_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r'[\u200B-\u200F\uFEFF]', '', s)
    return s.lower()

def build_fuzzy_pattern(keyword: str) -> re.Pattern:
    kw = re.escape(keyword)
    if len(keyword) <= 2:
        pattern = rf'\b{kw}\b'
    else:
        parts = list(keyword)
        escaped_parts = [re.escape(p) for p in parts]
        spacer = r'[\s\W\u200B\u200C\u200D]*'
        pattern = ''.join(p + spacer for p in escaped_parts).rstrip(spacer)
    try:
        return re.compile(pattern, flags=re.IGNORECASE)
    except Exception:
        return re.compile(re.escape(keyword), flags=re.IGNORECASE)

class DB:
    def __init__(self, path: str):
        self.path = path
        self._init_db()
    def _conn(self):
        return sqlite3.connect(self.path, timeout=30, check_same_thread=False)
    def _init_db(self):
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, topic_id TEXT, state TEXT, is_blocked INTEGER, block_count INTEGER, info_json TEXT, verified INTEGER, captcha_answer TEXT, last_seen INTEGER)")
        cur.execute("CREATE TABLE IF NOT EXISTS messages (user_id TEXT, user_message_id TEXT, forwarded_message_id TEXT, forwarded_chat_id TEXT, date INTEGER, PRIMARY KEY (user_id, user_message_id))")
        cur.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()
    def set_user(self, user_id: str, **kwargs):
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if cur.fetchone():
            keys = ", ".join(f"{k}=?" for k in kwargs.keys())
            vals = list(kwargs.values())
            vals.append(user_id)
            cur.execute(f"UPDATE users SET {keys} WHERE user_id=?", vals)
        else:
            fields = ["user_id"] + list(kwargs.keys())
            placeholders = ",".join("?" for _ in fields)
            vals = [user_id] + list(kwargs.values())
            cur.execute(f"INSERT INTO users ({','.join(fields)}) VALUES ({placeholders})", vals)
        conn.commit()
        conn.close()
    def get_user(self, user_id: str):
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("SELECT user_id,topic_id,state,is_blocked,block_count,info_json,verified,captcha_answer,last_seen FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "user_id": row[0],
            "topic_id": row[1],
            "state": row[2],
            "is_blocked": bool(row[3]),
            "block_count": row[4] or 0,
            "info_json": row[5],
            "verified": bool(row[6]),
            "captcha_answer": row[7],
            "last_seen": row[8]
        }
    def add_message_mapping(self, user_id: str, user_message_id: str, forwarded_message_id: str, forwarded_chat_id: str, date: int):
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO messages (user_id,user_message_id,forwarded_message_id,forwarded_chat_id,date) VALUES (?,?,?,?,?)",
                    (user_id, user_message_id, forwarded_message_id, str(forwarded_chat_id), date))
        conn.commit()
        conn.close()
    def find_user_by_forwarded(self, chat_id: str, forwarded_message_id: str):
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("SELECT user_id,user_message_id FROM messages WHERE forwarded_chat_id=? AND forwarded_message_id=?", (str(chat_id), str(forwarded_message_id)))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {"user_id": row[0], "user_message_id": row[1]}
    def set_config(self, key: str, value: str):
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO config (key,value) VALUES (?,?)", (key, value))
        conn.commit()
        conn.close()
    def get_config(self, key: str) -> Optional[str]:
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("SELECT value FROM config WHERE key=?", (key,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    def increment_block(self, user_id: str):
        u = self.get_user(user_id)
        if not u:
            self.set_user(user_id, topic_id=None, state=None, is_blocked=0, block_count=1, info_json=None, verified=0, captcha_answer=None, last_seen=int(time.time()))
            return 1
        newcount = (u.get("block_count", 0) or 0) + 1
        is_blocked = 1 if newcount >= BLOCK_THRESHOLD else 0
        self.set_user(user_id, block_count=newcount, is_blocked=is_blocked, last_seen=int(time.time()))
        return newcount
    def set_verified(self, user_id: str, verified: int):
        self.set_user(user_id, verified=verified, captcha_answer=None, last_seen=int(time.time()))
    def set_topic(self, user_id: str, topic_id: str):
        self.set_user(user_id, topic_id=str(topic_id), last_seen=int(time.time()))
    def set_captcha(self, user_id: str, answer: str):
        self.set_user(user_id, captcha_answer=str(answer), last_seen=int(time.time()))
    def set_state(self, user_id: str, state: str):
        self.set_user(user_id, state=state, last_seen=int(time.time()))
    def set_blocked(self, user_id: str, blocked: int):
        self.set_user(user_id, is_blocked=blocked, last_seen=int(time.time()))

db = DB(DB_FILE)

final_rules = []
final_patterns = []

async def update_spam_rules_job(context: ContextTypes.DEFAULT_TYPE):
    custom_keywords = [k.strip().lower() for k in CUSTOM_SPAM_KEYWORDS.split(',') if k.strip()]
    final_set = set(custom_keywords)
    url_list = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(SPAM_RULES_URL)
        if resp.status_code == 200 and resp.text:
            for line in resp.text.splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if ':' in line:
                    keyword = line.split(':', 1)[-1].strip()
                else:
                    keyword = line
                if keyword:
                    url_list.append(keyword.lower())
            final_set.update(url_list)
        else:
            final_set.update([k.lower().strip() for k in ["t.me/+", "joinchat", "crypto", "bitcoin", "trx", "usdt", "eth", "binance", "外围", "嫩模", "空降", "约炮", "色情", "博彩", "赌博", "代发", "发单", "上门", "点券", "换汇", "担保", "公群"]])
    except Exception as e:
        logger.warning(f"更新规则异常: {e}")
        final_set.update([k.lower().strip() for k in ["t.me/+", "joinchat", "crypto", "bitcoin", "trx", "usdt", "eth", "binance", "外围", "嫩模", "空降", "约炮", "色情", "博彩", "赌博", "代发", "发单", "上门", "点券", "换汇", "担保", "公群"]])
    global final_rules, final_patterns
    final_rules = [k for k in final_set if k]
    final_patterns = [build_fuzzy_pattern(k) for k in final_rules]
    context.bot_data['spam_keywords'] = final_rules
    context.bot_data['spam_patterns'] = final_patterns
    logger.info(f"规则更新完成, total={len(final_rules)}")

def is_spam_text(text: str, patterns: List[re.Pattern]) -> bool:
    if not text:
        return False
    t = normalize_text(text)
    for p in patterns:
        try:
            if p.search(t):
                return True
        except Exception:
            try:
                if re.search(p.pattern, t, flags=re.IGNORECASE):
                    return True
            except Exception:
                continue
    return False

user_rate_times = {}

def check_rate_limit(user_id: int) -> bool:
    now = time.time()
    times = user_rate_times.get(user_id, [])
    times = [t for t in times if now - t <= RATE_LIMIT_WINDOW]
    times.append(now)
    user_rate_times[user_id] = times
    return len(times) > RATE_LIMIT_COUNT

def gen_captcha():
    if CAPTCHA_MODE == 'math':
        a = random.randint(2, 9)
        b = random.randint(2, 9)
        op = random.choice(['+', '-'])
        q = f"{a} {op} {b} = ?"
        ans = str(a + b) if op == '+' else str(a - b)
        return q, ans
    else:
        token = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))
        return f"请输入验证码: {token}", token

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    uid = str(update.message.from_user.id)
    u = db.get_user(uid)
    if u and u.get("verified"):
        await update.message.reply_text("您已通过验证。")
        return
    q, a = gen_captcha()
    db.set_captcha(uid, a)
    db.set_state(uid, 'pending_verification')
    await update.message.reply_text(f"为了防止滥用，请回答验证问题：{q}")

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.message.from_user
    uid = str(user.id)
    if check_rate_limit(user.id):
        try:
            await update.message.reply_text("发送过于频繁，请稍后再试。")
        except Exception:
            pass
        return
    u = db.get_user(uid) or {}
    if u.get("is_blocked"):
        try:
            await update.message.reply_text("您已被封禁，无法发送消息。")
        except Exception:
            pass
        return
    state = u.get("state")
    if state == 'pending_verification':
        text = (update.message.text or "").strip()
        if not text:
            try:
                await update.message.reply_text("请直接回复验证码。")
            except Exception:
                pass
            return
        expected = u.get("captcha_answer")
        if expected and text == str(expected):
            db.set_verified(uid, 1)
            db.set_state(uid, None)
            await update.message.reply_text("验证通过，您的消息已发送给管理员。")
        else:
            cnt = db.increment_block(uid)
            if cnt >= BLOCK_THRESHOLD:
                await update.message.reply_text("验证失败次数过多，您已被封禁。")
                return
            else:
                await update.message.reply_text("验证错误，请重试。")
                return
    msg_parts = []
    if update.message.text:
        msg_parts.append(update.message.text)
    if update.message.caption:
        msg_parts.append(update.message.caption)
    if update.message.document and getattr(update.message.document, 'file_name', None):
        msg_parts.append(update.message.document.file_name)
    msg_text = "\n".join(msg_parts).strip()
    patterns = context.bot_data.get('spam_patterns', final_patterns)
    try:
        if is_spam_text(msg_text, patterns):
            cnt = db.increment_block(uid)
            await update.message.reply_text("您的消息被检测为广告/违规，已被拦截。")
            logger.info(f"用户 {uid} 命中广告规则, block_count={cnt}")
            return
    except Exception as e:
        logger.warning(f"检测异常: {e}")
    if not ADMIN_GROUP_ID:
        try:
            await update.message.reply_text("系统尚未配置管理员群组，暂时无法转发。")
        except Exception:
            pass
        return
    topic_id = None
    user_record = db.get_user(uid)
    if user_record and user_record.get("topic_id"):
        topic_id = user_record.get("topic_id")
    else:
        topic_name = f"{user.first_name}_{uid}"
        try:
            created = await context.bot.create_forum_topic(chat_id=ADMIN_GROUP_ID, name=topic_name)
            if created and getattr(created, 'message_thread_id', None):
                topic_id = created.message_thread_id
        except Exception:
            topic_id = None
    if not topic_id:
        try:
            sent = await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=f"来自 {user.first_name} (ID:{uid}) 的新会话")
            topic_id = getattr(sent, 'message_thread_id', None)
        except Exception as e:
            logger.error(f"无法发送到管理员群: {e}")
            try:
                await update.message.reply_text("转发失败，请稍后再试。")
            except Exception:
                pass
            return
    db.set_topic(uid, topic_id)
    try:
        forwarded = await update.message.forward(chat_id=ADMIN_GROUP_ID, message_thread_id=topic_id)
    except BadRequest:
        forwarded = None
        try:
            forwarded = await update.message.forward(chat_id=ADMIN_GROUP_ID)
        except Exception as e:
            logger.error(f"forward again failed: {e}")
    if forwarded:
        db.add_message_mapping(uid, str(update.message.message_id), str(forwarded.message_id), str(forwarded.chat_id), int(time.time()))
    try:
        await update.message.reply_text("您的消息已转发给管理员。")
    except Exception:
        pass
    if BACKUP_GROUP_ID:
        try:
            await update.message.copy(chat_id=BACKUP_GROUP_ID)
        except Exception:
            pass

async def handle_edited_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.edited_message:
        return
    em = update.edited_message
    orig = db.find_user_by_forwarded(str(em.chat_id), str(em.message_id))
    if not orig:
        return
    user_id = orig['user_id']
    try:
        await context.bot.send_message(chat_id=ADMIN_GROUP_ID, message_thread_id=db.get_user(user_id).get("topic_id"), text=f"已编辑的消息来自用户 {user_id}, 管理员注意查看。")
    except Exception:
        pass

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.message.from_user.id not in ADMIN_IDS:
        return
    if not update.message.reply_to_message:
        return
    ref = update.message.reply_to_message
    mapping = db.find_user_by_forwarded(str(ref.chat_id), str(ref.message_id))
    if not mapping:
        return
    target_user = mapping.get("user_id")
    if not target_user:
        return
    try:
        if update.message.text:
            await update.message.copy(chat_id=int(target_user))
        elif update.message.photo or update.message.document or update.message.video or update.message.voice or update.message.sticker:
            await update.message.copy(chat_id=int(target_user))
        else:
            await update.message.copy(chat_id=int(target_user))
        try:
            await update.message.reply_text("已将您的回复转发给用户。")
        except Exception:
            pass
    except RetryAfter as ra:
        await asyncio.sleep(ra.retry_after)
        try:
            await update.message.copy(chat_id=int(target_user))
        except Exception as e:
            logger.error(f"转发回复失败: {e}")
            try:
                await update.message.reply_text(f"转发失败: {e}")
            except Exception:
                pass
    except Exception as e:
        logger.error(f"转发回复失败: {e}")
        try:
            await update.message.reply_text(f"转发失败: {e}")
        except Exception:
            pass

async def command_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.message.from_user.id not in ADMIN_IDS:
        return
    args = context.args
    if not args:
        await update.message.reply_text("请提供要封禁的用户ID")
        return
    target = args[0]
    db.set_blocked(str(target), 1)
    await update.message.reply_text("已封禁")

async def command_unblock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.message.from_user.id not in ADMIN_IDS:
        return
    args = context.args
    if not args:
        await update.message.reply_text("请提供要解禁的用户ID")
        return
    target = args[0]
    db.set_blocked(str(target), 0)
    await update.message.reply_text("已解禁")

async def health_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("OK")

def run_health_server():
    try:
        from http.server import HTTPServer, BaseHTTPRequestHandler
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")
        port = PORT
        server = HTTPServer(('0.0.0.0', port), H)
        logger.info(f"Health server running on {port}")
        server.serve_forever()
    except Exception as e:
        logger.warning(f"Health server error: {e}")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.job_queue.run_once(update_spam_rules_job, when=0)
    app.job_queue.run_repeating(update_spam_rules_job, interval=3600)
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('block', command_block))
    app.add_handler(CommandHandler('unblock', command_unblock))
    app.add_handler(MessageHandler(filters.StatusUpdate.ALL, lambda u,c: None))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, handle_edited_message))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.DOCUMENT | filters.VIDEO | filters.AUDIO | filters.VOICE | filters.STICKER, handle_user_message))
    app.add_handler(MessageHandler(filters.User(user_id=ADMIN_IDS) & filters.REPLY & ~filters.COMMAND, handle_admin_reply))
    try:
        import threading
        t = threading.Thread(target=run_health_server, daemon=True)
        t.start()
    except Exception:
        pass
    app.run_polling()

if __name__ == '__main__':
    main()
