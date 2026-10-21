import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath("."))
from telethon import TelegramClient

async def test_auth():
    client = TelegramClient("data/telegram_user", 28680296, "927e2da6e7d0ec3d97a79d11cc794e46")
    await client.connect()
    is_auth = await client.is_user_authorized()
    print("Telegram client authorized:", is_auth)
    if is_auth:
        me = await client.get_me()
        print("Logged in as:", me.first_name, me.username, me.phone)
    await client.disconnect()

asyncio.run(test_auth())

