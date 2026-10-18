import asyncio
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
            sess_path = self.session_path
            sess_ext = f"{sess_path}.session" if not sess_path.endswith(".session") else sess_path
            if not os.path.exists(sess_ext):
                candidates = []
                if hasattr(self.config, "data_dir") and self.config.data_dir:
                    candidates.append(os.path.join(self.config.data_dir, "telegram_user.session"))
                    candidates.append(os.path.join(self.config.data_dir, "data", "telegram_user.session"))
                if "APPDATA" in os.environ:
                    candidates.append(os.path.join(os.environ["APPDATA"], "telegram_binance_signal_executor", "telegram_user.session"))
                    candidates.append(os.path.join(os.environ["APPDATA"], "telegram_binance_signal_executor", "data", "telegram_user.session"))
                if "LOCALAPPDATA" in os.environ:
                    candidates.append(os.path.join(os.environ["LOCALAPPDATA"], "telegram-binance-signal-executor", "telegram_user.session"))
                    candidates.append(os.path.join(os.environ["LOCALAPPDATA"], "telegram-binance-signal-executor", "data", "telegram_user.session"))
                candidates.append(r"e:\TOOL DUNG CODE\bottradecrypto\data\telegram_user.session")
                for cand in candidates:
                    if cand and os.path.exists(cand):
                        sess_path = cand[:-8] if cand.endswith(".session") else cand
                        break
            self.client = TelegramClient(sess_path, self.api_id, self.api_hash)
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

    async def collect_channel_history(
        self,
        chat_id: int,
        limit: int = 1000,
        max_days: int = 7,
        min_id: int = 0,
        checkpoint_callback=None,
    ) -> List[dict]:
        """
        Collects historical messages from a single specified channel/group:
        - Strictly read-only, does not download media.
        - Limits to max_days (default 7 days) and limit (default 1000 messages).
        - Handles FloodWaitError gracefully with backoff sleep.
        - Supports checkpoint callback for resuming interrupted fetches.
        """
        from datetime import datetime, timezone, timedelta
        from telethon.errors import FloodWaitError

        client = self.get_client()
        await client.connect()
        if not await client.is_user_authorized():
            raise BotTradingError("Chua dang nhap Telegram. Vui long chay lenh `python -m cli.main telegram-login`")

        entity = await client.get_entity(chat_id)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=max_days)

        messages = []
        try:
            async for msg in client.iter_messages(entity, limit=limit, min_id=min_id):
                if msg.date and msg.date < cutoff_date:
                    break

                raw_text = msg.raw_text or ""
                reply_id = None
                if msg.reply_to:
                    reply_id = getattr(msg.reply_to, "reply_to_msg_id", None)

                msg_dict = {
                    "chat_id": chat_id,
                    "message_id": msg.id,
                    "sender_id": msg.sender_id,
                    "date": msg.date.isoformat() if msg.date else None,
                    "edit_date": msg.edit_date.isoformat() if msg.edit_date else None,
                    "reply_to_msg_id": reply_id,
                    "raw_text": raw_text,
                }
                messages.append(msg_dict)

                if checkpoint_callback and len(messages) % 25 == 0:
                    checkpoint_callback(msg.id, len(messages))

        except FloodWaitError as e:
            print(f"[CANH BAO FLOODWAIT] Telegram yeu cau tam dung {e.seconds} giay...")
            await asyncio.sleep(e.seconds)

        if checkpoint_callback and messages:
            checkpoint_callback(messages[-1]["message_id"], len(messages))

        return messages


