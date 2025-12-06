import aiosqlite
import time
import os

DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_NAME = os.path.join(DATA_DIR, "defense.db")

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute("PRAGMA wal_autocheckpoint=1000;")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS request_logs (
                user_id INTEGER,
                timestamp REAL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                user_id INTEGER PRIMARY KEY,
                unban_time REAL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_logs_user ON request_logs(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_logs_time ON request_logs(timestamp)")
        await db.commit()

async def check_user_status(user_id: int, window: int, limit: int, ban_duration: int) -> str:
    now = time.time()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("BEGIN IMMEDIATE")
        
        try:
            async with db.execute("SELECT unban_time FROM blacklist WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    if now < row[0]:
                        return "BANNED"
                    else:
                        await db.execute("DELETE FROM blacklist WHERE user_id = ?", (user_id,))

            await db.execute("DELETE FROM request_logs WHERE user_id = ? AND timestamp < ?", (user_id, now - window))
            
            async with db.execute("SELECT COUNT(*) FROM request_logs WHERE user_id = ?", (user_id,)) as cursor:
                count = (await cursor.fetchone())[0]

            if count >= limit:
                unban_time = now + ban_duration
                await db.execute("INSERT OR REPLACE INTO blacklist (user_id, unban_time) VALUES (?, ?)", (user_id, unban_time))
                await db.commit()
                return "BANNED_NOW"

            await db.execute("INSERT INTO request_logs (user_id, timestamp) VALUES (?, ?)", (user_id, now))
            await db.commit()
            return "OK"
            
        except Exception:
            await db.rollback()
            return "ERROR"

async def clean_old_logs(retention: int = 3600):
    now = time.time()
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("DELETE FROM request_logs WHERE timestamp < ?", (now - retention,))
            await db.execute("DELETE FROM blacklist WHERE unban_time < ?", (now,))
            await db.commit()
            await db.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception:
        pass
