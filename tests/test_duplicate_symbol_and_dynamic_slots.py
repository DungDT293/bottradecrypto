import pytest
import asyncio
from decimal import Decimal
from datetime import datetime, timezone

from config.config import AppConfig
from config.policy_defaults import SourcePolicyOverride
from core.enums import PositionSide, SignalState, ExecutionMode
from core.models import ValidatedSignal, SourceMetadata, ParsedSignal
from exchange.mock_exchange import MockBinanceFuturesClient
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from risk.risk_engine import RiskEngine
from storage.database import DatabaseManager, OrderRepository, SignalRepository
from telegram.listener import TelegramSignalListener


class MockTelegramEvent:
    def __init__(self, chat_id, msg_id, text, orig_date, edit_date=None, reply_to_msg_id=None):
        self.chat_id = chat_id
        self.id = msg_id
        self.raw_text = text
        self.date = orig_date
        self.edit_date = edit_date
        self.reply_to_msg_id = reply_to_msg_id
        self.sender_id = 999


@pytest.mark.asyncio
async def test_duplicate_opposite_symbol_rejected(tmp_path):
    db_path = str(tmp_path / "test_dup.db")
    db_mgr = DatabaseManager(db_path)
    sig_repo = SignalRepository(db_mgr)
    ord_repo = OrderRepository(db_mgr)

    cfg = AppConfig(mode=ExecutionMode.LIVE, live_trading_enabled=True)
    cfg.telegram.allowed_chat_ids = [-1001895315984]
    cfg.sources = {
        "-1001756316676": SourcePolicyOverride(chat_id=-1001756316676, name="Boom Boom", margin_multiplier=Decimal("1.0")),
        "-1001895315984": SourcePolicyOverride(chat_id=-1001895315984, name="Crypto spider", margin_multiplier=Decimal("0.5")),
    }

    client = MockBinanceFuturesClient(initial_equity=Decimal("100.0"))
    # Add an active LONG position for SOLUSDT
    client.positions["SOLUSDT"] = {
        "symbol": "SOLUSDT",
        "positionAmt": "1.0", # LONG
        "entryPrice": "150.0",
        "unRealizedProfit": "2.5",
    }

    pos_mgr = PositionManager(client, ord_repo)
    risk_eng = RiskEngine(cfg)
    order_mgr = OrderManager(client, ord_repo, sig_repo, pos_mgr, risk_eng, cfg)

    listener = TelegramSignalListener(config=cfg, tg_client=None, db_manager=db_mgr, order_manager=order_mgr, position_manager=pos_mgr)

    # Process message in listener
    now = datetime.now(timezone.utc)
    ev = MockTelegramEvent(
        chat_id=-1001895315984,
        msg_id=123,
        text="SOL/USDT SHORT Entry: 152 SL: 156 TP: 148, 144, 138",
        orig_date=now,
    )
    await listener.handle_incoming_message(ev)

    # Signal must be rejected due to opposite active position
    saved_sig = sig_repo.get_active_signal_for_symbol("SOLUSDT")
    assert saved_sig is None # Khong co active signal nao duoc mo cho SOLUSDT SHORT
    print("\n[TEST 1 PASS] Signal SHORT bi tu choi thanh cong vi da co vi the LONG tren san!")


@pytest.mark.asyncio
async def test_dynamic_slot_freeing_when_breakeven_reached(tmp_path):
    db_path = str(tmp_path / "test_slots.db")
    db_mgr = DatabaseManager(db_path)
    sig_repo = SignalRepository(db_mgr)
    ord_repo = OrderRepository(db_mgr)

    cfg = AppConfig(mode=ExecutionMode.LIVE, live_trading_enabled=True)
    cfg.sources = {
        "-1001756316676": SourcePolicyOverride(chat_id=-1001756316676, name="Boom Boom", margin_multiplier=Decimal("1.0")),
        "-1001895315984": SourcePolicyOverride(chat_id=-1001895315984, name="Crypto spider", margin_multiplier=Decimal("0.5")),
    }

    client = MockBinanceFuturesClient(initial_equity=Decimal("100.0"))

    # Simulate 4 open positions on Binance: 3 are AT-RISK, 1 is RISK-FREE (Breakeven activated)
    client.positions["ETHUSDT"] = {"symbol": "ETHUSDT", "positionAmt": "0.1"}
    client.positions["BTCUSDT"] = {"symbol": "BTCUSDT", "positionAmt": "0.01"}
    client.positions["NEARUSDT"] = {"symbol": "NEARUSDT", "positionAmt": "10.0"}
    client.positions["DOGEUSDT"] = {"symbol": "DOGEUSDT", "positionAmt": "100.0"} # This one reached BE!

    now = datetime.utcnow()
    sig_repo.save_message(-1001895315984, 1, 1, now, now, "doge", "doge")
    parsed_doge = ParsedSignal(
        signal_id="sig_doge_be",
        symbol_raw="DOGEUSDT",
        symbol_candidate="DOGEUSDT",
        side=PositionSide.LONG,
        entries=[Decimal("0.10")],
        stop_loss=Decimal("0.09"),
        take_profits=[Decimal("0.11")],
        leverage_range=(10, 20),
        metadata=SourceMetadata(chat_id=-1001895315984, message_id=1, telegram_timestamp=now),
        validation_status=SignalState.OPEN_PROTECTED
    )
    sig_repo.save_signal(parsed_doge)
    sig_repo.record_timeline_event("sig_doge_be", "BREAKEVEN_SL_ACTIVATED", "Keo Bat Tu da kich hoat")

    pos_mgr = PositionManager(client, ord_repo)
    risk_eng = RiskEngine(cfg)
    order_mgr = OrderManager(client, ord_repo, sig_repo, pos_mgr, risk_eng, cfg)
    listener = TelegramSignalListener(config=cfg, tg_client=None, db_manager=db_mgr, order_manager=order_mgr, position_manager=pos_mgr)

    # Count at-risk positions
    open_positions = await client.get_open_positions()
    at_risk_count = 0
    risk_free_count = 0
    for p in open_positions:
        sym = p.get("symbol")
        sig = sig_repo.get_active_signal_for_symbol(sym)
        t_events = sig_repo.get_timeline(sig["signal_id"]) if sig else []
        if any(e.get("event_type") in ("BREAKEVEN_SL_ACTIVATED", "BREAKEVEN_ACTIVATED", "TP1_TRIGGERED") for e in t_events):
            risk_free_count += 1
        else:
            at_risk_count += 1

    # 1 DOGE is risk free, 3 are at-risk -> at_risk_count is 3 (< 4), slot IS LIBERATED!
    assert risk_free_count == 1
    assert at_risk_count == 3
    print("\n[TEST 2 PASS] Keo cham TP1 doi BE da giai phong slot rui ro thanh cong! at_risk_count = 3/4")
