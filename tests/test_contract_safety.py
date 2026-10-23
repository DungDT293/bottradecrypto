from datetime import datetime
from decimal import Decimal

import pytest

from config.config import AppConfig, TelegramConfig
from core.enums import ExecutionMode, MarginMode, SignalState
from core.models import ParsedSignal, SourceMetadata
from storage.database import DatabaseManager, SignalRepository
from telegram.listener import TelegramSignalListener


class _Event:
    chat_id = 1000
    id = 7
    raw_text = "Cancel pending"
    date = datetime.utcnow()
    edit_date = None
    reply_to_msg_id = None
    sender_id = 999


@pytest.mark.asyncio
async def test_unauthorized_admin_update_is_ignored(tmp_path):
    db = DatabaseManager(str(tmp_path / "listener.db"))
    cfg = AppConfig(
        mode=ExecutionMode.TESTNET,
        telegram=TelegramConfig(allowed_chat_ids=[1000], admin_sender_ids=[123]),
    )
    listener = TelegramSignalListener(cfg, None, db)
    await listener.handle_incoming_message(_Event())
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 0


def test_signal_id_is_canonical_for_message(tmp_path):
    db = DatabaseManager(str(tmp_path / "signals.db"))
    repo = SignalRepository(db)
    now = datetime.utcnow()
    repo.save_message(1000, 7, 123, now, now, "signal", "signal")
    meta = SourceMetadata(chat_id=1000, message_id=7, telegram_timestamp=now)
    signal = ParsedSignal(
        signal_id="sig_1000_7",
        metadata=meta,
        symbol_raw="BTC/USDT",
        symbol_candidate="BTCUSDT",
        validation_status=SignalState.PARSED,
    )
    repo.save_signal(signal)
    repo.save_signal(signal)
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 1


def test_margin_mode_wire_value():
    assert MarginMode.CROSS.value == "CROSSED"
