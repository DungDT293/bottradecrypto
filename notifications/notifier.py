import aiohttp
from typing import Optional
from config.config import NotificationsConfig


class SystemNotifier:
    """
    Isolated notification module.
    Sends alerts to personal Telegram chat if configured, without coupling to order flow.
    Failure to send notification never rolls back an executed order.
    """

    def __init__(self, config: NotificationsConfig):
        self.config = config

    async def notify(self, message: str) -> bool:
        if self.config.console_logging:
            print(f"[NOTIF] {message}")

        if not self.config.telegram_notification_enabled:
            return True

        token = self.config.notification_bot_token
        chat_id = self.config.notification_chat_id
        if not token or not chat_id:
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return resp.status == 200
        except Exception:
            # Never raise or break trading flow on notification failure
            return False

