from datetime import datetime
from decimal import Decimal
import pytest

from config.config import load_config
from core.enums import MarginMode, OrderSide, OrderType, PositionSide, SignalState
from core.exceptions import EmergencyCloseError
from core.models import SourceMetadata, ValidatedSignal
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from exchange.mock_exchange import MockBinanceFuturesClient
from risk.risk_engine import RiskEngine
from storage.database import DatabaseManager, OrderRepository, SignalRepository


@pytest.fixture
def test_setup(tmp_path):
    db_file = str(tmp_path / "test_orders.db")
    db = DatabaseManager(db_file)
    signal_repo = SignalRepository(db)
    order_repo = OrderRepository(db)

    config = load_config()
    mock_client = MockBinanceFuturesClient(initial_equity=Decimal("10000.0"))
    pos_manager = PositionManager(mock_client, signal_repo)
    risk_eng = RiskEngine(config)

    order_mgr = OrderManager(
        client=mock_client,
        order_repo=order_repo,
        signal_repo=signal_repo,
        position_manager=pos_manager,
        risk_engine=risk_eng,
        config=config,
    )

    return order_mgr, mock_client, signal_repo, order_repo


def make_validated_signal():
    meta = SourceMetadata(chat_id=101, message_id=1, telegram_timestamp=datetime.utcnow())
    return ValidatedSignal(
        signal_id="sig_ord_1",
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        entries=[(Decimal("60000"), Decimal("0.5")), (Decimal("59000"), Decimal("0.5"))],
        stop_loss=Decimal("58000"),
        take_profits=[(Decimal("62000"), Decimal("0.5")), (Decimal("65000"), Decimal("0.5"))],
        leverage=5,
        margin_mode=MarginMode.ISOLATED,
        is_breakeven_after_tp1=True,
        risk_pct=Decimal("0.5"),
        metadata=meta,
    )


@pytest.mark.asyncio
async def test_submit_entries_and_on_fill_sl_success(test_setup):
    order_mgr, client, signal_repo, order_repo = test_setup
    signal = make_validated_signal()

    # Save initial message & signal to DB
    signal_repo.save_message(101, 1, 1, datetime.utcnow(), datetime.utcnow(), "msg", "msg")
    from core.models import ParsedSignal
    parsed = ParsedSignal(
        signal_id=signal.signal_id,
        metadata=signal.metadata,
        symbol_raw="BTC/USDT",
        symbol_candidate="BTCUSDT",
        side=signal.side,
        validation_status=SignalState.VALIDATED,
    )
    signal_repo.save_signal(parsed)

    # 1. Submit entries
    entry_sizes = [(Decimal("60000"), Decimal("0.025")), (Decimal("59000"), Decimal("0.025"))]
    created = await order_mgr.submit_entries(signal, entry_sizes)
    assert len(created) == 2
    assert len(client.open_orders) == 2

    # 2. Simulate Entry 1 fill
    client.simulate_entry_fill(created[0].client_order_id, Decimal("0.025"), Decimal("60000"))

    # 3. Call on_entry_filled
    sl_order = await order_mgr.on_entry_filled(signal, Decimal("0.025"), Decimal("60000"))
    assert sl_order is not None
    assert sl_order.order_type == OrderType.STOP_MARKET
    assert sl_order.trigger_price == Decimal("58000")
    # Verify placed in mock algo orders
    assert len(client.open_algo_orders) == 1


@pytest.mark.asyncio
async def test_failsafe_emergency_close_when_sl_fails(test_setup):
    order_mgr, client, signal_repo, order_repo = test_setup
    signal = make_validated_signal()

    signal_repo.save_message(101, 1, 1, datetime.utcnow(), datetime.utcnow(), "msg", "msg")
    from core.models import ParsedSignal
    parsed = ParsedSignal(
        signal_id=signal.signal_id,
        metadata=signal.metadata,
        symbol_raw="BTC/USDT",
        symbol_candidate="BTCUSDT",
        side=signal.side,
        validation_status=SignalState.VALIDATED,
    )
    signal_repo.save_signal(parsed)

    entry_sizes = [(Decimal("60000"), Decimal("0.025")), (Decimal("59000"), Decimal("0.025"))]
    created = await order_mgr.submit_entries(signal, entry_sizes)

    # Simulate Entry 1 fill
    client.simulate_entry_fill(created[0].client_order_id, Decimal("0.025"), Decimal("60000"))

    # CONFIGURE MOCK TO FAIL SL PLACEMENT PERSISTENTLY
    client.always_fail_algo_order = True

    # on_entry_filled should trigger FAIL-SAFE emergency close!
    with pytest.raises(EmergencyCloseError):
        await order_mgr.on_entry_filled(signal, Decimal("0.025"), Decimal("60000"))

    # Verify that remaining pending entry was canceled
    assert created[1].client_order_id not in client.open_orders
    # Verify that the position was emergency closed to 0
    pos = await client.get_position("BTCUSDT")
    assert Decimal(str(pos["positionAmt"])) == Decimal("0")
    # Verify signal state is CLOSED with fail-safe reason
    sig_db = signal_repo.get_signal(signal.signal_id)
    assert sig_db["state"] == SignalState.CLOSED.value
    assert "SL THAT BAI - DA DONG KHAN CAP VI THE" in sig_db["blocking_reason"]


@pytest.mark.asyncio
async def test_submit_breakout_entries(test_setup):
    order_mgr, client, signal_repo, order_repo = test_setup
    signal = make_validated_signal()

    signal_repo.save_message(101, 1, 1, datetime.utcnow(), datetime.utcnow(), "msg", "msg")
    from core.models import ParsedSignal
    parsed = ParsedSignal(
        signal_id=signal.signal_id,
        metadata=signal.metadata,
        symbol_raw="BTC/USDT",
        symbol_candidate="BTCUSDT",
        side=signal.side,
        validation_status=SignalState.VALIDATED,
    )
    signal_repo.save_signal(parsed)

    # Current market price is 55000, while entries are 60000 and 59000 (Breakout LONG)
    entry_sizes = [(Decimal("60000"), Decimal("0.025")), (Decimal("59000"), Decimal("0.025"))]
    created = await order_mgr.submit_entries(signal, entry_sizes, current_market_price=Decimal("55000"))

    assert len(created) == 2
    assert created[0].is_algo is True
    assert created[0].order_type == OrderType.STOP_MARKET
    assert created[0].trigger_price == Decimal("60000")
    assert len(client.open_algo_orders) == 2
    assert len(client.open_orders) == 0

    # Test cancelling pending breakout entries
    await order_mgr.cancel_pending_entries_for_signal(signal.signal_id, signal.symbol)
    assert len(client.open_algo_orders) == 0
