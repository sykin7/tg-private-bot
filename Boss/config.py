import os
import requests

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
TARGET_CHAT_ID = int(os.getenv("TARGET_CHAT_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8080"))
REMOTE_RULES_URL = os.getenv("REMOTE_RULES_URL", "https://raw.githubusercontent.com/sykin7/my-telegram-spam-rules/refs/heads/main/spam.txt")

SPAM_KEYWORDS = [
    "加群", "免费", "领钱", "福利", "点击", "http", "https", 
    "t.me", "群组", "频道", "兼职", "日结", "加密", "货币", 
    "USDT", "BTC", "投资", "理财", "裸聊", "约炮"
]

if REMOTE_RULES_URL:
    try:
        response = requests.get(REMOTE_RULES_URL, timeout=10)
        if response.status_code == 200:
            remote_words = [line.strip() for line in response.text.splitlines() if len(line.strip()) > 1]
            SPAM_KEYWORDS.extend(remote_words)
    except Exception:
        pass

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_COUNT = 5
BAN_DURATION = 300
LOG_RETENTION = 3600
