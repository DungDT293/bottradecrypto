import os
from typing import Any, List, Optional
from telethon import TelegramClient
from telethon.tl.custom import Dialog

from config.config import AppConfig
from core.exceptions import BotTradingError


class TelegramUserClient:
    """
    Manages Telethon connection for reading channels and listing dialogs.
    Strictly READ-ONLY:
    - Never sends messages into monitored channels
    - Never automatically joins groups
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.api_id = config.telegram.api_id
        self.api_hash = config.telegram.api_hash
        self.session_path = config.telegram.session_name
        self.client: Optional[TelegramClient] = None

    def get_client(self) -> TelegramClient:
        if not self.api_id or not self.api_hash:
            raise BotTradingError("Thieu TELEGRAM_API_ID hoac TELEGRAM_API_HASH trong file .env")
        if self.client is None:
            self.client = TelegramClient(self.session_path, self.api_id, self.api_hash)
        return self.client

    async def list_dialogs(self) -> List[dict]:
        """
        Retrieves user's accessible channels/groups with name and ID for allowlist selection.
        """
        client = self.get_client()
        await client.connect()
        if not await client.is_user_authorized():
            raise BotTradingError("Chua dang nhap Telegram. Vui long chay lenh `python -m cli.main telegram-login`")

        dialogs = await client.get_dialogs()
        result = []
        for d in dialogs:
            if d.is_channel or d.is_group:
                result.append({
                    "id": d.id,
                    "title": d.title,
                    "is_channel": d.is_channel,
                    "is_group": d.is_group,
                    "unread_count": d.unread_count,
                })
        return result

