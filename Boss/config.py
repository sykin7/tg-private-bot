from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    BOT_TOKEN: str = Field(..., min_length=10)
    OWNER_ID: int
    PORT: int = 8080
    
    SPAM_RULES_URL: str = "https://raw.githubusercontent.com/RGB-Outl4w/zapper-TGAB/main/spam_phrases.txt"
    FALLBACK_KEYWORDS: list = [
        "t.me/+", "joinchat", "crypto", "bitcoin", "trx", "usdt", "eth", "binance",
        "外围", "嫩模", "空降", "约炮", "色情", "博彩", "赌博", "代发", "发单",
        "上门", "点券", "换汇", "担保", "公群", "跑分", "网赚", "兼职"
    ]
    
    FLOOD_WINDOW: int = 10
    MAX_MSGS: int = 5
    BAN_TIME: int = 600

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'

settings = Settings()
