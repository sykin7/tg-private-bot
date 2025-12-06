# -*- coding: utf-8 -*-

from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import Forbidden, BadRequest
import os
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
import re
import httpx
import unicodedata
import time
import socket # 新增：用于设置网络超时
from collections import defaultdict

# --- 配置日志 ---
# V15.0 优化: 仅记录警告及以上级别，防止常规信息刷屏
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.WARNING 
)
logger = logging.getLogger(__name__)
# 强制将本脚本日志级别设为 INFO，以便看到启动信息
logger.setLevel(logging.INFO)

# --- 环境变量检查 ---
OWNER_ID_STR = os.getenv('OWNER_ID')
if not OWNER_ID_STR:
    logger.error("致命错误: 环境变量 OWNER_ID 未设置!")
    exit(1)
try:
    OWNER_ID = int(OWNER_ID_STR)
except ValueError:
    exit(1)

# --- 供应链安全配置 ---
# 建议：如果你担心 GitHub 仓库被投毒，可以将此 URL 留空，脚本将只使用本地规则
SPAM_RULES_URL = os.getenv('SPAM_RULES_URL', "https://raw.githubusercontent.com/RGB-Outl4w/zapper-TGAB/main/spam_phrases.txt")

# V15.0 增强: 本地硬编码规则库 (作为最后一道防线)
FALLBACK_SPAM_KEYWORDS = [
    "t.me/+", "joinchat", "crypto", "bitcoin", "trx", "usdt", "eth", "binance",
    "外围", "嫩模", "空降", "约炮", "色情", "博彩", "赌博", "代发", "发单",
    "上门", "点券", "换汇", "担保", "公群", "跑分", "网赚", "兼职"
]

# 全局变量
FLOOD_WINDOW = 10
MAX_MSGS_PER_WINDOW = 5
user_flood_control = defaultdict(list)

# --- 功能函数 ---

async def update_spam_rules(context: ContextTypes.DEFAULT_TYPE):
    """ 定时任务：更新在线广告规则 """
    # V15.0: 降低日志级别，只有失败才警告
    custom_keywords = context.bot_data.get('custom_keywords', [])
    final_rules_set = set(custom_keywords)
    
    if SPAM_RULES_URL:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(SPAM_RULES_URL, timeout=10.0)
            if response.status_code == 200:
                for line in response.text.splitlines():
                    line = line.strip().lower()
                    if not line or line.startswith('#'): continue
                    keyword = line.split(':', 1)[-1].strip() if ':' in line else line
                    if keyword: final_rules_set.add(keyword)
            else:
                final_rules_set.update(FALLBACK_SPAM_KEYWORDS)
        except Exception:
            # 网络错误时静默使用兜底规则
            final_rules_set.update(FALLBACK_SPAM_KEYWORDS)
    else:
        final_rules_set.update(FALLBACK_SPAM_KEYWORDS)
        
    context.bot_data['spam_keywords'] = list(final_rules_set)
    # logger.info(f"规则库已更新，当前关键词数: {len(final_rules_set)}") # 调试时可开启

async def garbage_collect(context: ContextTypes.DEFAULT_TYPE):
    """ 异步 GC """
    now = time.time()
    keys_to_remove = []
    
    for uid, timestamps in user_flood_control.items():
        if timestamps and (now - timestamps[-1] > FLOOD_WINDOW):
            keys_to_remove.append(uid)
        elif not timestamps:
            keys_to_remove.append(uid)
            
    if keys_to_remove:
        # V15.0: 静默清理，不再打印日志
        for uid in keys_to_remove:
            del user_flood_control[uid]

class HealthCheckHandler(BaseHTTPRequestHandler):
    # V15.0 修复: 屏蔽日志输出，防止健康检查请求刷屏
    def log_message(self, format, *args):
        pass 

    def do_GET(self):
        self.send_response(200)
        self.wfile.write(b'OK')

def run_server():
    # V15.0 修复: 设置全局 Socket 超时，防止 HTTP 慢速攻击 (Slowloris)
    socket.setdefaulttimeout(10) 
    
    port = int(os.getenv('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    
    # 启动服务器线程
    Thread(target=server.serve_forever, daemon=True).start()

async def start(update, context):
    await update.message.reply_text('欢迎！请直接发送消息，我会转发给管理员。')

def safe_cut_utf16(text, limit):
    if text is None: return ""
    if len(text) > limit:
        return text[:limit] + "..."
    return text

def is_spam(text, keywords):
    if not text: return False
    
    # NFKC 标准化
    text_normalized = unicodedata.normalize('NFKC', text)
    text_lower = text_normalized.lower()
    
    # 1. 基础匹配
    for keyword in keywords:
        if keyword in text_lower: return True

    # 2. 深度去噪匹配
    text_cleaned = re.sub(r'[\W_]+', '', text_lower)
    for keyword in keywords:
        if keyword.isalnum() and keyword in text_cleaned:
            return True
            
    return False

def clean_user_name(name):
    if not name: return "Unknown"
    name = name.replace("(ID:", "").replace(")", "")
    return "".join(ch for ch in name if unicodedata.category(ch) not in ['Cf', 'Cc'])

def check_flood(user_id):
    now = time.time()
    timestamps = user_flood_control[user_id]
    
    valid_timestamps = [t for t in timestamps if now - t < FLOOD_WINDOW]
    
    if len(valid_timestamps) < MAX_MSGS_PER_WINDOW:
        valid_timestamps.append(now)
        user_flood_control[user_id] = valid_timestamps
        return False 
    else:
        user_flood_control[user_id] = valid_timestamps
        return True 

async def forward_to_owner(update, context):
    user = update.message.from_user
    
    if check_flood(user.id):
        # V15.0: 触发熔断时完全静默，不打印任何日志
        return 

    message = update.message
    message_text = message.text or message.caption or ""

    spam_keywords = context.bot_data.get('spam_keywords', [])
    if is_spam(message_text, spam_keywords):
        # V15.0 修复: 拦截广告时不再写日志，防止日志炸弹
        try: await message.reply_text("已拦截疑似广告信息。")
        except: pass
        return

    clean_name = clean_user_name(user.first_name)
    user_header = f"📩 来自 {clean_name} (ID: {user.id}):\n\n"
    header_len = len(user_header)
    safe_limit = 4096 - header_len - 100

    try:
        if message.text:
            safe_text = safe_cut_utf16(message.text, safe_limit)
            await context.bot.send_message(chat_id=OWNER_ID, text=user_header + safe_text)
        
        elif message.photo or message.video or message.document or message.voice or message.audio or message.animation:
            original_caption = message.caption or ""
            caption_limit = 1024 - header_len - 50
            safe_caption = user_header + safe_cut_utf16(original_caption, caption_limit)
            await message.copy(chat_id=OWNER_ID, caption=safe_caption)

        else:
            await message.forward(chat_id=OWNER_ID)

    except Exception as e:
        logger.warning(f"转发异常: {e}")
        try: await message.forward(chat_id=OWNER_ID)
        except: pass

async def reply_to_user(update, context):
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ 请回复消息进行操作。")
        return

    original_message = update.message.reply_to_message
    target_user_id = None
    
    if original_message.forward_from:
        target_user_id = original_message.forward_from.id
    elif original_message.text or original_message.caption:
        content = original_message.text or original_message.caption
        match = re.search(r"^📩 来自 .*? \(ID: (\d+)\):\n\n", content, re.DOTALL)
        if match:
            target_user_id = int(match.group(1))

    if target_user_id:
        try:
            await update.message.copy(chat_id=target_user_id)
            await update.message.reply_text(f"✅ 已回复")
        except Forbidden:
            await update.message.reply_text(f"⚠️ 发送失败: 用户已屏蔽机器人。")
        except BadRequest as e:
            await update.message.reply_text(f"⚠️ 发送失败: {e}")
        except Exception as e:
            await update.message.reply_text(f"❌ 未知错误: {e}")
    else:
        await update.message.reply_text("⚠️ 无法获取ID，请引用带ID头的消息。")

def main():
    logger.info("启动 V15.0 终极硬核防御版...")
    token = os.getenv('BOT_TOKEN')
    if not token: return

    custom_words = [w.strip().lower() for w in os.getenv('CUSTOM_SPAM_KEYWORDS', "").split(',') if w.strip()]
    app = Application.builder().token(token).build()
    app.bot_data['custom_keywords'] = custom_words

    # 任务队列
    app.job_queue.run_once(update_spam_rules, 1)
    app.job_queue.run_repeating(update_spam_rules, interval=3600, first=10)
    app.job_queue.run_repeating(garbage_collect, interval=600, first=600)

    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler('start', start, filters=private))
    app.add_handler(MessageHandler(private & filters.User(user_id=OWNER_ID) & filters.REPLY & ~filters.COMMAND, reply_to_user))
    app.add_handler(MessageHandler(private & ~filters.COMMAND & ~filters.User(user_id=OWNER_ID), forward_to_owner))

    run_server()
    app.run_polling()

if __name__ == '__main__':
    main()
