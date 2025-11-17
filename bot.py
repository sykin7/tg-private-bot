# -*- coding: utf-8 -*-

# --- V7.1 - 终极修正版 ---
# 1. 修正 V7.0 中错误的 v13 库导入语句 (ModuleNotFoundError)
# 2. 将 update_spam_rules 的类型提示改为 v20+ 兼容的 ContextTypes.DEFAULT_TYPE
# 3. 保留 V7.0 的所有动态环境变量功能

from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import os
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
import re
import httpx

# (V7.1 修正: 删除了错误的 "from telegram.ext.callbackcontext import CallbackContext" 这一行)

# --- V4版：日志记录配置 ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- V7.0 终极灵活版：从环境变量读取配置 ---

# 1. 机器人主人ID (必须)
OWNER_ID_STR = os.getenv('OWNER_ID')
OWNER_ID = 0  # 临时初始化
if not OWNER_ID_STR:
    logger.error("致命错误: 环境变量 OWNER_ID 未设置! 机器人无法启动。")
    exit(1) # 严重错误，退出程序
try:
    OWNER_ID = int(OWNER_ID_STR)
    logger.info(f"配置加载：机器人主人ID (OWNER_ID) 已设置为: {OWNER_ID}")
except ValueError:
    logger.error(f"致命错误: OWNER_ID '{OWNER_ID_STR}' 不是一个有效的数字 ID! 机器人无法启动。")
    exit(1) # 严重错误，退出程序

# 2. 公共规则URL (可选, 带默认值)
DEFAULT_SPAM_RULES_URL = "https://raw.githubusercontent.com/RGB-Outl4w/zapper-TGAB/main/spam_phrases.txt"
SPAM_RULES_URL = os.getenv('SPAM_RULES_URL', DEFAULT_SPAM_RULES_URL)
logger.info(f"配置加载：广告规则URL (SPAM_RULES_URL) 已设置为: {SPAM_RULES_URL}")

# 3. 备用规则 (硬编码)
FALLBACK_SPAM_KEYWORDS = [
    "t.me/+", "joinchat", "crypto", "bitcoin", "trx", "usdt", "eth", "binance",
    "外围", "嫩模", "空降", "约炮", "色情", "博彩", "赌博", "代发", "发单",
    "上门", "点券", "换汇", "担保", "公群"
]
# --- V7.0 配置加载结束 ---


# --- V6 终极版：自动更新 + 合并自定义规则 ---
# --- V7.1 修正: 将 "context: CallbackContext" 修改为 v20 兼容的 "context: ContextTypes.DEFAULT_TYPE" ---
async def update_spam_rules(context: ContextTypes.DEFAULT_TYPE):
    logger.info("正在尝试更新广告屏蔽规则...")
    
    # 1. 从 context 中获取自定义关键词列表 (在 main() 中设置的)
    custom_keywords = context.bot_data.get('custom_keywords', [])
    
    # 2. 准备一个集合，用于存放所有规则 (集合可以自动去重)
    final_rules_set = set(custom_keywords)
    if custom_keywords:
        logger.info(f"已加载 {len(custom_keywords)} 条自定义规则。")

    # 3. 尝试从 URL 拉取规则 (使用 V7 的 SPAM_RULES_URL 变量)
    base_keywords_from_url = []
    try:
        async with httpx.AsyncClient() as client:
            # SPAM_RULES_URL 是我们在 V7 顶部动态加载的
            response = await client.get(SPAM_RULES_URL, timeout=10.0) 
        
        if response.status_code == 200:
            for line in response.text.splitlines():
                line = line.strip().lower()
                if not line or line.startswith('#'):
                    continue
                
                # V5.1 智能解析格式
                if ':' in line:
                    keyword = line.split(':', 1)[-1].strip()
                else:
                    keyword = line
                
                if keyword:
                    base_keywords_from_url.append(keyword)
            
            # 4A. URL 成功：将URL规则添加到集合中
            final_rules_set.update(base_keywords_from_url)
            logger.info(f"成功从URL加载 {len(base_keywords_from_url)} 条公共规则。")
        
        else:
            logger.warning(f"拉取规则URL失败(URL: {SPAM_RULES_URL}), HTTP状态码: {response.status_code}。将使用备用规则。")
            final_rules_set.update([k.lower().strip() for k in FALLBACK_SPAM_KEYWORDS])
            logger.info(f"已加载 {len(FALLBACK_SPAM_KEYWORDS)} 条备用规则。")

    except Exception as e:
        logger.warning(f"从URL拉取广告规则时发生错误(URL: {SPAM_RULES_URL}): {e}。将使用备用规则。")
        # 4C. URL 异常：使用备用规则
        final_rules_set.update([k.lower().strip() for k in FALLBACK_SPAM_KEYWORDS])
        logger.info(f"已加载 {len(FALLBACK_SPAM_KEYWORDS)} 条备用规则。")

    # 5. 最终将集合转换回列表，并存储到 bot_data 中
    final_rules_list = list(final_rules_set)
    context.bot_data['spam_keywords'] = final_rules_list
    
    logger.info(f"规则更新完毕。总计生效的独特关键词共 {len(final_rules_list)} 条。")


# --- 用于平台健康检查的虚拟服务器 (V4) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

def run_server():
    port = int(os.getenv('PORT', 8080))
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    logger.info(f"Health check server on port {port} is running...")
    httpd.serve_forever()

# --- /start 命令的处理器 (V4) ---
async def start(update, context):
    welcome_message = '欢迎！您发送的任何消息都将被转发给管理员。'
    await update.message.reply_text(welcome_message)

# --- V7.1 修正: 检查关键词是否为空 ---
async def forward_to_owner(update, context):
    user = update.message.from_user
    message = update.message
    
    message_text = message.text or message.caption

    if message_text:
        spam_keywords = context.bot_data.get('spam_keywords', [])
        text_lower = message_text.lower()
        
        is_spam_flag = False
        for keyword in spam_keywords:
            if keyword: # V7.1 增加检查: 确保关键词不是空字符串
                if keyword in text_lower:
                    is_spam_flag = True
                    break
        
        if is_spam_flag:
            logger.info(f"检测到广告! 来自 {user.first_name} (ID: {user.id}). 消息已自动拦截。")
            try:
                await message.reply_text("您的消息被系统检测为垃圾信息，已被自动拦截，请勿发送广告。")
            except Exception as e:
                logger.warning(f"回复被拦截用户 {user.id} 时失败: {e}")
            return

    # (如果不是广告，则执行V4的转发逻辑)
    info_text = f"👇 收到来自 {user.first_name} (ID: {user.id}) 的一条新消息:"
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=info_text)
    except Exception as e:
        logger.error(f"Error sending notification to owner (ID: {OWNER_ID}): {e}")

    try:
        await message.forward(chat_id=OWNER_ID)
        confirmation_message = '您的消息已成功发送！'
        await update.message.reply_text(confirmation_message) # V7.1 修正: 使用 update.message.reply_text
        logger.info(f"Successfully forwarded message from user {user.id} to owner {OWNER_ID}")
    except Exception as e:
        logger.error(f"Error forwarding message: {e}")
        error_message = '抱歉，发送消息时遇到错误。'
        await update.message.reply_text(error_message) # V7.1 修正: 使用 update.message.reply_text

# --- 核心功能2 (V4终极版): 处理主人的回复，兼容隐私模式 ---
async def reply_to_user(update, context):
    if update.message.reply_to_message:
        original_message = update.message.reply_to_message
        target_user_id = None
        
        if original_message.forward_from:
            target_user_id = original_message.forward_from.id
        
        elif original_message.from_user.id == context.bot.id and original_message.text:
            match = re.search(r"\(ID: (\d+)\)", original_message.text)
            if match:
                target_user_id = int(match.group(1))

        if target_user_id:
            try:
                await update.message.copy(chat_id=target_user_id)
                await update.message.reply_text(f"✅ 已成功回复给用户 (ID: {target_user_id})")
                logger.info(f"Successfully replied to user {target_user_id}")
            except Exception as e:
                logger.error(f"Failed to reply to user {target_user_id}: {e}")
                await update.message.reply_text(f"❌ 回复失败！错误: {e}")
        else:
            await update.message.reply_text("⚠️ 无法回复：请确保您“回复”到用户的转发消息，或者我发送的 `(ID:...)` 提示上。")

# --- 主函数 ---
def main():
    VERSION = "V7.1 - 终极修正版 (修正v20库导入错误)"
    logger.info(f"==========================================")
    logger.info(f"机器人正在启动... 版本: {VERSION}")
    logger.info(f"==========================================")
    
    # V7.0: BOT_TOKEN 是唯一在 main() 中检查的环境变量
    token = os.getenv('BOT_TOKEN')
    if not token:
        logger.error("致命错误: 环境变量 BOT_TOKEN 未设置!")
        return

    # --- V6 新增：读取自定义广告词 ---
    custom_words_env = os.getenv('CUSTOM_SPAM_KEYWORDS', "") # 默认为空字符串
    custom_keywords_list = []
    if custom_words_env:
        custom_keywords_list = [
            word.strip().lower() 
            for word in custom_words_env.split(',') 
            if word.strip()
        ]
        logger.info(f"配置加载：已从环境变量加载 {len(custom_keywords_list)} 个自定义关键词。")
    else:
        logger.info("配置加载：未在环境变量中找到 CUSTOM_SPAM_KEYWORDS，跳过自定义关键词。")
    # --- V6 新增结束 ---

    app = Application.builder().token(token).build()

    # --- V6 新增：将自定义列表存入 bot_data ---
    app.bot_data['custom_keywords'] = custom_keywords_list
    # --- V6 新增结束 ---

    # --- V5 新增：启动并调度广告规则更新任务 ---
    job_queue = app.job_queue
    job_queue.run_once(update_spam_rules, when=0) # 启动时立刻执行一次
    job_queue.run_repeating(update_spam_rules, interval=3600) # 之后每小时执行一次
    # --- V5 任务调度结束 ---

    # --- V7.0 处理器注册 ---
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.User(user_id=OWNER_ID) & filters.REPLY & ~filters.COMMAND, reply_to_user))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.User(user_id=OWNER_ID), forward_to_owner))
    # --- V7.0 注册结束 ---

    # 启动V4的健康检查服务器
    server_thread = Thread(target=run_server, daemon=True)
    server_thread.start()

    # 启动机器人
    app.run_polling()

if __name__ == '__main__':
    main()
