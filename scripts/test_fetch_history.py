import asyncio
from datetime import datetime, timedelta, timezone
import sys
import os

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from telethon import TelegramClient

async def test():
    from config.config import load_config
    config = load_config()
    if not config.telegram.api_id or not config.telegram.api_hash:
        raise RuntimeError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in local .env")
    client = TelegramClient('data/telegram_user', config.telegram.api_id, config.telegram.api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print('Not authorized')
        return
    six_months_ago = datetime.now(timezone.utc) - timedelta(days=180)
    print('Target date (6 months ago):', six_months_ago.isoformat())
    
    cid = -1001370457350 # Crypto Neon
    count = 0
    async for msg in client.iter_messages(cid, offset_date=six_months_ago, limit=5, reverse=True):
        txt = (msg.text[:50] if msg.text else "").replace("\n", " ")
        print(f"Msg ID: {msg.id}, Date: {msg.date}, Text: {txt}")
        count += 1
    print('Fetched count:', count)
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(test())

