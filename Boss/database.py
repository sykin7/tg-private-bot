import aiosqlite
import time
import logging

logger = logging.getLogger(__name__)

DB_NAME = "defense.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
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
        await db.commit()

async def check_user_status(user_id: int, window: int, limit: int, ban_duration: int) -> str:
    now = time.time()
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT unban_time FROM blacklist WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                if now < row[0]:
                    return "BANNED"
                else:
                    await db.execute("DELETE FROM blacklist WHERE user_id = ?", (user_id,))
                    await db.commit()

        await db.execute("DELETE FROM request_logs WHERE timestamp < ?", (now - window,))
        
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

async def clean_old_logs(retention: int = 3600):
    now = time.time()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM request_logs WHERE timestamp < ?", (now - retention,))
        await db.execute("DELETE FROM blacklist WHERE unban_time < ?", (now,))
        await db.commit()
