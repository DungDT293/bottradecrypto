import aiohttp
import logging
from typing import Any, Callable, Optional
from config.config import NotificationsConfig

logger = logging.getLogger(__name__)


class SystemNotifier:
    """
    Isolated notification module.
    Sends alerts to personal Telegram chat or Bot channel without coupling to order flow.
    Supports:
    1. Standard Telegram Bot API (via token & chat_id).
    2. Direct user client Saved Messages ('me') via Telethon when user is logged in.
    Failure to send notification never rolls back an executed order.
    """

    def __init__(
        self,
        config: Optional[NotificationsConfig] = None,
        telegram_client_getter: Optional[Callable[[], Any]] = None,
    ):
        self.config = config
        self.telegram_client_getter = telegram_client_getter

    async def notify(self, message: str) -> bool:
        if self.config and self.config.console_logging:
            print(f"[NOTIF] {message}")

        sent = False

        # 1. Try Telegram Bot if token and chat_id are configured
        if self.config and self.config.telegram_notification_enabled:
            token = self.config.notification_bot_token
            chat_id = self.config.notification_chat_id
            if token and chat_id:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                            if resp.status == 200:
                                sent = True
                except Exception as exc:
                    logger.debug(f"Bot notification failed: {exc}")

        # 2. Try direct personal Telegram (Saved Messages 'me') if user client is connected
        if not sent and self.telegram_client_getter:
            try:
                client = self.telegram_client_getter()
                if client and hasattr(client, "is_connected") and client.is_connected():
                    await client.send_message("me", message)
                    sent = True
            except Exception as exc:
                logger.debug(f"Personal Telegram notification to 'me' failed: {exc}")

        return sent

