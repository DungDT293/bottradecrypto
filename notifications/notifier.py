"""
notifications/notifier.py
=============================================================================
ISOLATED SYSTEM NOTIFIER MODULE
=============================================================================
Sends alerts to personal Telegram chat or Bot channel without coupling to order flow.
Supports:
1. Standard Telegram Bot API (via token & chat_id).
2. Direct user client Saved Messages ('me') via Telethon when user is logged in.
3. Full Telegram HTML parse_mode with auto-sanitization & auto-closed tags.
4. Quantum Council AI Debate Broadcast support.
Failure to send notification never rolls back an executed order.
=============================================================================
"""

import aiohttp
import logging
from typing import Any, Callable, Optional
from config.config import NotificationsConfig
from telegram.telegram_notifier import (
    TelegramNotifier,
    sanitize_telegram_html,
    ensure_closed_tags,
    strip_html,
)

logger = logging.getLogger(__name__)


class SystemNotifier:
    """
    Isolated notification module.
    Sends alerts to personal Telegram chat or Bot channel without coupling to order flow.
    Supports:
    1. Standard Telegram Bot API (via token & chat_id) with parse_mode=HTML.
    2. Direct user client Saved Messages ('me') via Telethon with parse_mode=html.
    3. Quantum Council AI Debate broadcasting.
    Failure to send notification never rolls back an executed order.
    """

    def __init__(
        self,
        config: Optional[NotificationsConfig] = None,
        telegram_client_getter: Optional[Callable[[], Any]] = None,
    ):
        self.config = config
        self.telegram_client_getter = telegram_client_getter
        self._engine = TelegramNotifier(
            config=config,
            telegram_client_getter=telegram_client_getter,
        )

    async def notify(self, message: str, parse_mode: str = "html") -> bool:
        """
        Sends formatted message to Telegram (Bot API or Personal Saved Messages).
        Guarantees that HTML tags <b>, <i>, <code> are rendered properly,
        preventing raw tags from appearing in user chat.
        """
        return await self._engine.notify(message, parse_mode=parse_mode)

    async def send_debate(self, deliberation_or_html: Any) -> bool:
        """Broadcasts Quantum Council AI Debate to Telegram."""
        return await self._engine.send_council_debate(deliberation_or_html)


__all__ = [
    "SystemNotifier",
    "TelegramNotifier",
    "sanitize_telegram_html",
    "ensure_closed_tags",
    "strip_html",
]
