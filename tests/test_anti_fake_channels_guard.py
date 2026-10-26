import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock

from config.config import AppConfig, load_config, PERMANENT_BLACKLISTED_CHANNELS
from core.enums import PositionSide, SignalState
from core.models import SourceMetadata
from parser.signal_parser import SignalParser
from parser.validator import SignalValidator
from telegram.listener import TelegramSignalListener
from storage.database import DatabaseManager


def test_blacklist_purge_in_config():
    """Verify that load_config automatically purges any blacklisted channel from allowed_chat_ids."""
    cfg = load_config("config.yaml")
    allowed = set(cfg.telegram.allowed_chat_ids)
    blacklisted = set(cfg.telegram.blacklisted_chat_ids)
    permanent = set(PERMANENT_BLACKLISTED_CHANNELS.keys())

    # Ensure intersection is completely empty
    assert len(allowed.intersection(blacklisted)) == 0, f"Allowed contains blacklisted: {allowed.intersection(blacklisted)}"
    assert len(allowed.intersection(permanent)) == 0, f"Allowed contains permanent blacklisted: {allowed.intersection(permanent)}"

    # Ensure specific dangerous channels are blacklisted
    assert -1002266035358 in blacklisted  # THE MASTER
    assert -1001903052876 in blacklisted  # AISH CRYPTO
    assert -1001390568202 in blacklisted  # PRO TRADING
    assert -1001756316676 in blacklisted  # Boom_Boom_Billionaires
    assert -1001370457350 in blacklisted  # Crypto Neon


@pytest.mark.asyncio
async def test_listener_blocks_blacklisted_channel_messages():
    """Verify that TelegramSignalListener immediately drops messages from blacklisted channels."""
    cfg = load_config("config.yaml")
    db_mock = MagicMock(spec=DatabaseManager)
    listener = TelegramSignalListener(
        config=cfg,
        tg_client=MagicMock(),
        db_manager=db_mock,
        is_shadow=True
    )
    listener.signal_repo = MagicMock()

    # Event from THE MASTER
    event_master = MagicMock()
    event_master.chat_id = -1002266035358
    event_master.id = 1234
    event_master.raw_text = "BTC LONG 90000 TP 95000 SL 88000"

    await listener.handle_incoming_message(event_master)
    listener.signal_repo.save_message.assert_not_called()
    listener.signal_repo.save_signal.assert_not_called()

    # Event from AISH CRYPTO
    event_aish = MagicMock()
    event_aish.chat_id = -1001903052876
    event_aish.id = 1235
    event_aish.raw_text = "$BR/USDT LONG Entry 0.499 SL 0.43 TP 0.52"

    await listener.handle_incoming_message(event_aish)
    listener.signal_repo.save_message.assert_not_called()
    listener.signal_repo.save_signal.assert_not_called()


@pytest.mark.asyncio
async def test_listener_blocks_scam_commands_and_wallets():
    """Verify that dangerous admin instructions (remove SL, dca, crypto addresses) are dropped."""
    cfg = load_config("config.yaml")
    db_mock = MagicMock(spec=DatabaseManager)
    listener = TelegramSignalListener(
        config=cfg,
        tg_client=MagicMock(),
        db_manager=db_mock,
        is_shadow=True
    )
    listener.signal_repo = MagicMock()

    valid_chat_id = -1002191067035

    # 1. Dangerous command: Remove SL
    event_rem_sl = MagicMock()
    event_rem_sl.chat_id = valid_chat_id
    event_rem_sl.id = 2001
    event_rem_sl.raw_text = "Do dca on coin and Remove sl for a some time"

    await listener.handle_incoming_message(event_rem_sl)
    listener.signal_repo.save_message.assert_not_called()

    # 2. Dangerous command: Stoploss my instruction
    event_inst = MagicMock()
    event_inst.chat_id = valid_chat_id
    event_inst.id = 2002
    event_inst.raw_text = "BUY BTC ENTRY 90000 Stoploss : My Instruction"

    await listener.handle_incoming_message(event_inst)
    listener.signal_repo.save_message.assert_not_called()

    # 3. Scam: Wallet address
    event_wallet = MagicMock()
    event_wallet.chat_id = valid_chat_id
    event_wallet.id = 2003
    event_wallet.raw_text = "VIP DISCOUNT 59$ send to 0x844A45A9A974b7B44Fd959D00263257835F401cD"

    await listener.handle_incoming_message(event_wallet)
    listener.signal_repo.save_message.assert_not_called()


@pytest.mark.asyncio
async def test_listener_anti_revenge_cooloff():
    """Verify that an SL HIT announcement freezes the channel for 90 minutes."""
    cfg = load_config("config.yaml")
    db_mock = MagicMock(spec=DatabaseManager)
    listener = TelegramSignalListener(
        config=cfg,
        tg_client=MagicMock(),
        db_manager=db_mock,
        is_shadow=True
    )
    listener.signal_repo = MagicMock()
    listener.signal_repo.save_message_version.return_value = (1, True, "OK")

    valid_chat_id = -1001700314832  # Whales Circle

    # 1. Announce SL HIT
    event_sl = MagicMock()
    event_sl.chat_id = valid_chat_id
    event_sl.id = 3001
    event_sl.raw_text = "#KITE SL HIT"
    event_sl.date = datetime.now(timezone.utc)
    event_sl.edit_date = None
    event_sl.media = None
    event_sl.reply_to_msg_id = None
    await listener.handle_incoming_message(event_sl)

    assert valid_chat_id in listener._last_sl_timestamp_by_chat

    # 2. Try to post revenge trade 2 minutes later
    event_revenge = MagicMock()
    event_revenge.chat_id = valid_chat_id
    event_revenge.id = 3002
    event_revenge.date = datetime.now(timezone.utc)
    event_revenge.edit_date = None
    event_revenge.media = None
    event_revenge.reply_to_msg_id = None
    event_revenge.raw_text = """🐳 #ONE/USDT LONG 🐳
✳️ ENTRY :- 0.0028 - 0.0029
💢 LEVERAGE :- 20X
🔖 TARGET :- 0.003
⛔️ STOP-LOSS :- 0.0024"""

    await listener.handle_incoming_message(event_revenge)
    # The signal parser must not be saved to signals table
    listener.signal_repo.save_signal.assert_not_called()


def test_validator_rejects_sl_distance_over_threshold():
    """Verify that SignalValidator rejects signals with excessive SL distance (> 8.0%)."""
    cfg = load_config("config.yaml")
    cfg.execution.max_sl_distance_pct = Decimal("8.0")
    validator = SignalValidator(cfg)
    parser = SignalParser()

    # Signal with 14% SL distance (like Aish Crypto)
    text = """#BR/USDT LONG
Entry: 0.5000
TP1: 0.5300
Stoploss: 0.4300"""
    meta = SourceMetadata(
        chat_id=-1002191067035,
        message_id=101,
        telegram_timestamp=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc)
    )
    parsed = parser.parse(text, meta)
    parsed_res, val_res = validator.validate_and_resolve(parsed)
    assert val_res is None
    assert parsed_res.validation_status == SignalState.REJECTED
    assert "Khoang cach SL qua xa" in (parsed_res.blocking_reason or "")


def test_validator_rejects_poor_risk_reward_ratio():
    """Verify that SignalValidator rejects signals with terrible R:R (< 0.5)."""
    cfg = load_config("config.yaml")
    validator = SignalValidator(cfg)
    parser = SignalParser()

    # Entry 100, SL 95 (loss 5%), TP1 101 (gain 1%) -> R:R = 1/5 = 0.20
    text = """#BTC/USDT LONG
Entry: 100.0
TP1: 101.0
Stoploss: 95.0"""
    meta = SourceMetadata(
        chat_id=-1002191067035,
        message_id=102,
        telegram_timestamp=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc)
    )
    parsed = parser.parse(text, meta)
    parsed_res, val_res = validator.validate_and_resolve(parsed)
    assert val_res is None
    assert parsed_res.validation_status == SignalState.REJECTED
    assert "Ty le R:R qua thap" in (parsed_res.blocking_reason or "")
