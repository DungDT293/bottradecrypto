import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath("."))
from telethon import TelegramClient

async def test_auth():
    from config.config import load_config
    config = load_config()
    if not config.telegram.api_id or not config.telegram.api_hash:
        raise RuntimeError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in local .env")
    client = TelegramClient("data/telegram_user", config.telegram.api_id, config.telegram.api_hash)
    await client.connect()
    is_auth = await client.is_user_authorized()
    print("Telegram client authorized:", is_auth)
    if is_auth:
        me = await client.get_me()
        print("Logged in as:", me.first_name, me.username, me.phone)
    await client.disconnect()

asyncio.run(test_auth())

