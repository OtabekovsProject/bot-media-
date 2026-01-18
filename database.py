import aiosqlite
from config import DB_NAME

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                full_name TEXT,
                username TEXT,
                is_admin BOOLEAN DEFAULT 0,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE,
                channel_url TEXT
            )
        """)
        
        # Migration: Check if is_admin column exists, if not add it
        try:
            await db.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0")
        except:
            pass # Column likely exists
            
        try:
            await db.execute("ALTER TABLE users ADD COLUMN username TEXT")
        except:
            pass

        await db.commit()

async def add_user(telegram_id, full_name, username=None):
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute(
                "INSERT OR IGNORE INTO users (telegram_id, full_name, username) VALUES (?, ?, ?)",
                (telegram_id, full_name, username)
            )
            # Update username if it changed
            await db.execute("UPDATE users SET username = ? WHERE telegram_id = ?", (username, telegram_id))
            await db.commit()
        except Exception as e:
            print(f"DB Error: {e}")

async def get_stats():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            count = await cursor.fetchone()
            return count[0] if count else 0

async def get_all_users():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT telegram_id, full_name, username, is_admin FROM users") as cursor:
            return await cursor.fetchall()

async def check_admin(telegram_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT is_admin FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            res = await cursor.fetchone()
            return res[0] == 1 if res else False

async def set_admin(telegram_id, is_admin):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET is_admin = ? WHERE telegram_id = ?", (1 if is_admin else 0, telegram_id))
        await db.commit()

async def add_channel(channel_id, channel_url):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO channels (channel_id, channel_url) VALUES (?, ?)",
            (channel_id, channel_url)
        )
        await db.commit()

async def get_channels():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT channel_id, channel_url FROM channels") as cursor:
            return await cursor.fetchall()

async def remove_channel(channel_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
        await db.commit()