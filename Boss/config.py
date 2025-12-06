import os

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
TARGET_CHAT_ID = int(os.getenv("TARGET_CHAT_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8080"))

SPAM_KEYWORDS = [
    "加群", "免费", "领钱", "福利", "点击", "http", "https", 
    "t.me", "群组", "频道", "兼职", "日结", "加密", "货币", 
    "USDT", "BTC", "投资", "理财", "裸聊", "约炮"
]

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_COUNT = 5
BAN_DURATION = 300
LOG_RETENTION = 3600
