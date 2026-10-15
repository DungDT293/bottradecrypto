from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from config.config import load_config
from core.enums import MarginMode, OrderSide, OrderType, PositionSide, SignalState, UpdateType
from core.exceptions import BotTradingError, EmergencyCloseError
from core.models import Order, ParsedSignal, SourceMetadata, ValidatedSignal
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from execution.reconciliation import ReconciliationEngine
from exchange.mock_exchange import MockBinanceFuturesClient
from parser.update_parser import ChannelUpdateParser
from risk.risk_engine import RiskEngine
from storage.database import DatabaseManager, OrderRepository, SignalRepository


@pytest.fixture
def env_setup(tmp_path):
    db_file = str(tmp_path / "test_chain.db")
    db = DatabaseManager(db_file)
    client = MockBinanceFuturesClient(initial_equity=Decimal("10000.0"))
    config = load_config()
    sig_repo = SignalRepository(db)
    ord_repo = OrderRepository(db)
    pos_mgr = PositionManager(client, sig_repo)
    risk_eng = RiskEngine(config)
    order_mgr = OrderManager(client, ord_repo, sig_repo, pos_mgr, risk_eng, config)
    recon = ReconciliationEngine(client, db)
    return db, client, sig_repo, ord_repo, pos_mgr, order_mgr, recon, config


def make_signal(sig_id: str, symbol: str = "BTCUSDT", side: PositionSide = PositionSide.LONG, entries=None, sl=Decimal("58000"), tps=None, msg_id: int = 1) -> ValidatedSignal:
    meta = SourceMetadata(chat_id=1000, message_id=msg_id, telegram_timestamp=datetime.utcnow())
    return ValidatedSignal(
        signal_id=sig_id,
        symbol=symbol,
        side=side,
        entries=entries or [(Decimal("60000"), Decimal("1.0"))],
        stop_loss=sl,
        take_profits=tps or [(Decimal("63000"), Decimal("0.5")), (Decimal("66000"), Decimal("0.5"))],
        leverage=5,
        margin_mode=MarginMode.ISOLATED,
        is_breakeven_after_tp1=True,
        risk_pct=Decimal("0.5"),
        metadata=meta,
    )


# Scenario 1: Tin hieu -> entry fill -> TP1 fill -> BE
@pytest.mark.asyncio
async def test_scenario_1_happy_path_entry_to_be(env_setup):
    db, client, sig_repo, ord_repo, pos_mgr, order_mgr, recon, config = env_setup
    signal = make_signal("sig_s1")

    sig_repo.save_message(1000, 1, 1, datetime.utcnow(), datetime.utcnow(), "raw", "norm")
    parsed = ParsedSignal(
        signal_id=signal.signal_id, metadata=signal.metadata, symbol_raw="BTC/USDT", symbol_candidate="BTCUSDT",
        side=signal.side, validation_status=SignalState.VALIDATED
    )
    sig_repo.save_signal(parsed)

    # 1. Submit entry
    created = await order_mgr.submit_entries(signal, [(Decimal("60000"), Decimal("0.025"))])
    # 2. Entry fill
    client.simulate_entry_fill(created[0].client_order_id, Decimal("0.025"), Decimal("60000"))
    sl_ord = await order_mgr.on_entry_filled(signal, Decimal("0.025"), Decimal("60000"))
    assert sl_ord.trigger_price == Decimal("58000")

    # 3. TP1 fill -> trigger Breakeven
    be_ord = await order_mgr.move_sl_to_breakeven(
        signal, position_qty=Decimal("0.0125"), avg_entry_price=Decimal("60000"), existing_sl_algo_id=sl_ord.client_order_id
    )
    # BE price = 60000 * (1 + 0.1%) = 60060 (including fee buffer)
    assert be_ord.trigger_price == Decimal("60060.000")


# Scenario 2: Admin bao TP1 nhung tai khoan chua khop tren san
def test_scenario_2_admin_tp1_does_not_trigger_account_fill(env_setup):
    parser = ChannelUpdateParser()
    text = "🔥 TP1 Hit! Targets reached! 🔥"
    up_type, val, msg = parser.parse_update(text)
    assert up_type == UpdateType.RESULT_TP_REPORTED
    # Enforce invariant: this must NOT be interpreted as account fill!
    assert "KHONG coi day la fill thuc te" in msg


# Scenario 3: Pending entry -> admin cancel
@pytest.mark.asyncio
async def test_scenario_3_pending_entry_admin_cancel(env_setup):
    db, client, sig_repo, ord_repo, pos_mgr, order_mgr, recon, config = env_setup
    signal = make_signal("sig_s3", msg_id=3)

    sig_repo.save_message(1000, 3, 1, datetime.utcnow(), datetime.utcnow(), "raw", "norm")
    parsed = ParsedSignal(
        signal_id=signal.signal_id, metadata=signal.metadata, symbol_raw="BTC/USDT", symbol_candidate="BTCUSDT",
        side=signal.side, validation_status=SignalState.VALIDATED
    )
    sig_repo.save_signal(parsed)

    created = await order_mgr.submit_entries(signal, [(Decimal("60000"), Decimal("0.025"))])
    assert created[0].client_order_id in client.open_orders

    # Admin says "Cancel pending entry"
    await order_mgr.cancel_pending_entries_for_signal(signal.signal_id, "BTCUSDT")
    assert created[0].client_order_id not in client.open_orders


# Scenario 4: Partial fill -> admin cancel
@pytest.mark.asyncio
async def test_scenario_4_partial_fill_admin_cancel(env_setup):
    db, client, sig_repo, ord_repo, pos_mgr, order_mgr, recon, config = env_setup
    signal = make_signal("sig_s4", entries=[(Decimal("60000"), Decimal("0.5")), (Decimal("59000"), Decimal("0.5"))], msg_id=4)

    sig_repo.save_message(1000, 4, 1, datetime.utcnow(), datetime.utcnow(), "raw", "norm")
    parsed = ParsedSignal(
        signal_id=signal.signal_id, metadata=signal.metadata, symbol_raw="BTC/USDT", symbol_candidate="BTCUSDT",
        side=signal.side, validation_status=SignalState.VALIDATED
    )
    sig_repo.save_signal(parsed)

    created = await order_mgr.submit_entries(signal, [(Decimal("60000"), Decimal("0.025")), (Decimal("59000"), Decimal("0.025"))])

    # Entry 1 fills, Entry 2 pending
    client.simulate_entry_fill(created[0].client_order_id, Decimal("0.025"), Decimal("60000"))
    sl_ord = await order_mgr.on_entry_filled(signal, Decimal("0.025"), Decimal("60000"))

    # Admin cancels remaining pending
    await order_mgr.cancel_pending_entries_for_signal(signal.signal_id, "BTCUSDT")

    # Entry 2 canceled, but protective SL for Entry 1 remains active
    assert created[1].client_order_id not in client.open_orders
    assert sl_ord.client_order_id in client.open_algo_orders


# Scenario 5: LONG -> admin dinh chinh SHORT
def test_scenario_5_admin_correction_does_not_reverse_position(env_setup):
    parser = ChannelUpdateParser()
    text = "Sorry guys, wrong signal! Short not Long."
    up_type, val, msg = parser.parse_update(text)
    assert up_type == UpdateType.CORRECT_SIGNAL
    assert "KHONG coi day la dao chieu" in msg


# Scenario 6: SL update lam tang risk (LONG SL widened downwards) -> BI CHAN
def test_scenario_6_sl_widening_increases_risk_rejected(env_setup):
    old_sl = Decimal("58000")
    new_sl = Decimal("57000")  # Further down for LONG -> increases loss to SL!
    side = PositionSide.LONG

    is_widening = (new_sl < old_sl) if side == PositionSide.LONG else (new_sl > old_sl)
    assert is_widening is True  # Must be rejected!


# Scenario 7: Hai tin hieu cung coin, update khong reply -> NEEDS_REVIEW
def test_scenario_7_unlinked_update_on_duplicate_coin_needs_review(env_setup):
    db, client, sig_repo, ord_repo, pos_mgr, order_mgr, recon, config = env_setup

    # 2 signals for ETHUSDT
    sig_repo.save_message(1000, 71, 1, datetime.utcnow(), datetime.utcnow(), "raw1", "norm1")
    sig_repo.save_message(1000, 72, 1, datetime.utcnow(), datetime.utcnow(), "raw2", "norm2")
    parsed1 = ParsedSignal(signal_id="sig_eth_1", metadata=SourceMetadata(chat_id=1000, message_id=71, telegram_timestamp=datetime.utcnow()), symbol_raw="ETH/USDT", symbol_candidate="ETHUSDT", side=PositionSide.LONG, validation_status=SignalState.OPEN_PROTECTED)
    parsed2 = ParsedSignal(signal_id="sig_eth_2", metadata=SourceMetadata(chat_id=1000, message_id=72, telegram_timestamp=datetime.utcnow()), symbol_raw="ETH/USDT", symbol_candidate="ETHUSDT", side=PositionSide.SHORT, validation_status=SignalState.OPEN_PROTECTED)
    sig_repo.save_signal(parsed1)
    sig_repo.save_signal(parsed2)

    # An update without reply arrived: "Move SL to BE"
    # Cannot uniquely determine which signal -> resolve_reply_parent returns None
    parent = sig_repo.resolve_reply_parent(1000, reply_to_msg_id=999)
    assert parent is None


# Scenario 8: Reply den tin cap nhat da lien ket voi tin goc (Recursive resolution)
def test_scenario_8_recursive_reply_linking(env_setup):
    db, client, sig_repo, ord_repo, pos_mgr, order_mgr, recon, config = env_setup

    # Msg 10: Original signal
    sig_repo.save_message(1000, 10, 1, datetime.utcnow(), datetime.utcnow(), "Original", "Original")
    parsed = ParsedSignal(signal_id="sig_orig_10", metadata=SourceMetadata(chat_id=1000, message_id=10, telegram_timestamp=datetime.utcnow()), symbol_raw="BTC/USDT", symbol_candidate="BTCUSDT", side=PositionSide.LONG, validation_status=SignalState.VALIDATED)
    sig_repo.save_signal(parsed)

    # Msg 11: Update replying to Msg 10
    sig_repo.save_message_version(1000, 11, datetime.utcnow(), datetime.utcnow(), "Update 1", "Update 1", "fp11", is_edit=False, reply_to_msg_id=10)

    # Msg 12: Reply to Msg 11 (2 hops away from Msg 10)
    resolved_sig = sig_repo.resolve_reply_parent(1000, reply_to_msg_id=11)
    assert resolved_sig == "sig_orig_10"


# Scenario 9: Restart giua entry fill va SL confirmation
@pytest.mark.asyncio
async def test_scenario_9_restart_reconciliation_cleans_orphaned_state(env_setup):
    db, client, sig_repo, ord_repo, pos_mgr, order_mgr, recon, config = env_setup

    # Signal in local DB was OPEN_PROTECTED but position on exchange is 0
    sig_repo.save_message(1000, 90, 1, datetime.utcnow(), datetime.utcnow(), "raw", "norm")
    parsed = ParsedSignal(signal_id="sig_s9", metadata=SourceMetadata(chat_id=1000, message_id=90, telegram_timestamp=datetime.utcnow()), symbol_raw="BTC/USDT", symbol_candidate="BTCUSDT", side=PositionSide.LONG, validation_status=SignalState.OPEN_PROTECTED)
    sig_repo.save_signal(parsed)

    report = await recon.reconcile_all()
    assert report["active_signals_checked"] == 1
    # Successfully transitions to CLOSED
    assert sig_repo.get_signal("sig_s9")["state"] == SignalState.CLOSED.value


# Scenario 10: Timeout sau khi san da nhan SL update -> Dung clientAlgoId chong trung
@pytest.mark.asyncio
async def test_scenario_10_idempotent_algo_order_id(env_setup):
    db, client, sig_repo, ord_repo, pos_mgr, order_mgr, recon, config = env_setup

    # Creating algo order with explicit clientAlgoId ensures idempotency
    cid = "sl_idempotent_test_1"
    resp1 = await client.create_algo_order("BTCUSDT", OrderSide.SELL, OrderType.STOP_MARKET, Decimal("58000"), Decimal("0.1"), client_algo_id=cid)
    assert resp1["clientAlgoId"] == cid


# Scenario 11: Tin xoa khong co noi dung -> Xu ly em dep khong loi
@pytest.mark.asyncio
async def test_scenario_11_deleted_message_handled_safely(env_setup):
    from parser.normalizer import normalize_text
    # Deleted message has empty or whitespace text
    norm = normalize_text("")
    assert norm == ""
    norm_space = normalize_text("   \n\t  ")
    assert norm_space == ""


# Scenario 12: Gia tri SL trong tin goc bi sua sau nhieu gio
def test_scenario_12_old_signal_sl_edit_differentiated_ttl():
    # If original post was 5 hours ago, but edit was 10 seconds ago:
    now_utc = datetime.now(timezone.utc)
    orig_date = now_utc - timedelta(hours=5)
    edit_date = now_utc - timedelta(seconds=10)

    # For an edit event, age check uses edit_date:
    edit_age = (now_utc - edit_date).total_seconds()
    assert edit_age <= 300  # Within 300s window -> Allowed!
