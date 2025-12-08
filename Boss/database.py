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
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                status TEXT DEFAULT 'UNVERIFIED',
                last_seen REAL
            )
        """)
        
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
        async with db.execute("SELECT status FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user_row = await cursor.fetchone()
            
        if user_row and user_row[0] == 'BANNED':
            return "BANNED"

        async with db.execute("SELECT unban_time FROM blacklist WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                if now < row[0]:
                    return "FLOOD_BANNED"
                else:
                    await db.execute("DELETE FROM blacklist WHERE user_id = ?", (user_id,))

        if not user_row:
            await db.execute("INSERT OR IGNORE INTO users (user_id, status, last_seen) VALUES (?, 'UNVERIFIED', ?)", (user_id, now))
        else:
            await db.execute("UPDATE users SET last_seen = ? WHERE user_id = ?", (now, user_id))

        await db.execute("DELETE FROM request_logs WHERE user_id = ? AND timestamp < ?", (user_id, now - window))
        
        async with db.execute("SELECT COUNT(*) FROM request_logs WHERE user_id = ?", (user_id,)) as cursor:
            count = (await cursor.fetchone())[0]

        if count >= limit:
            unban_time = now + ban_duration
            await db.execute("INSERT OR REPLACE INTO blacklist (user_id, unban_time) VALUES (?, ?)", (user_id, unban_time))
            await db.commit()
            return "FLOOD_BANNED_NOW"

        await db.execute("INSERT INTO request_logs (user_id, timestamp) VALUES (?, ?)", (user_id, now))
        await db.commit()
        
        return user_row[0] if user_row else "UNVERIFIED"

async def update_user_status(user_id: int, status: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET status = ? WHERE user_id = ?", (status, user_id))
        await db.commit()

async def get_all_users():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users WHERE status != 'BANNED'") as cursor:
            return await cursor.fetchall()

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
