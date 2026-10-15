from datetime import datetime
from decimal import Decimal
import pytest

from core.enums import OrderSide, OrderType, PositionSide, SignalState
from core.exceptions import AccountStateBlockedError, ExchangeAdapterError
from execution.reconciliation import ReconciliationEngine
from exchange.mock_exchange import MockBinanceFuturesClient
from storage.database import DatabaseManager, OrderRepository, SignalRepository


@pytest.fixture
def test_setup(tmp_path):
    db_file = str(tmp_path / "test_recon.db")
    db = DatabaseManager(db_file)
    mock_client = MockBinanceFuturesClient(initial_equity=Decimal("10000.0"))
    recon = ReconciliationEngine(mock_client, db)
    return recon, mock_client, db


@pytest.mark.asyncio
async def test_reconciliation_detects_external_close_and_cleans_orders(test_setup):
    recon, client, db = test_setup
    sig_repo = SignalRepository(db)
    ord_repo = OrderRepository(db)

    # Setup an active signal in local DB that was OPEN_PROTECTED
    sig_repo.save_message(101, 1, 1, datetime.utcnow(), datetime.utcnow(), "msg", "msg")
    from core.models import Order, ParsedSignal, SourceMetadata
    meta = SourceMetadata(chat_id=101, message_id=1, telegram_timestamp=datetime.utcnow())
    parsed = ParsedSignal(
        signal_id="sig_recon_1",
        metadata=meta,
        symbol_raw="ETH/USDT",
        symbol_candidate="ETHUSDT",
        side=PositionSide.SHORT,
        validation_status=SignalState.OPEN_PROTECTED,
    )
    sig_repo.save_signal(parsed)

    # Add an open TP limit order and an open SL algo order
    tp_ord = Order(
        client_order_id="tp_1",
        signal_id="sig_recon_1",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("2200"),
        quantity=Decimal("1.0"),
        is_reduce_only=True,
        is_algo=False,
    )
    sl_ord = Order(
        client_order_id="sl_1",
        signal_id="sig_recon_1",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.STOP_MARKET,
        trigger_price=Decimal("2600"),
        quantity=Decimal("1.0"),
        is_reduce_only=True,
        is_algo=True,
    )
    ord_repo.save_order(tp_ord)
    ord_repo.save_order(sl_ord)

    # Place in mock exchange
    await client.create_standard_order("ETHUSDT", OrderSide.BUY, OrderType.LIMIT, Decimal("1.0"), Decimal("2200"), client_order_id="tp_1", reduce_only=True)
    await client.create_algo_order("ETHUSDT", OrderSide.BUY, OrderType.STOP_MARKET, Decimal("2600"), Decimal("1.0"), client_algo_id="sl_1")

    # Exchange position is 0 (closed outside)
    report = await recon.reconcile_all()

    assert report["account_one_way"] is True
    assert report["active_signals_checked"] == 1
    assert report["orphaned_cleaned"] == 2
    # Local state transitioned to CLOSED
    sig_db = sig_repo.get_signal("sig_recon_1")
    assert sig_db["state"] == SignalState.CLOSED.value


@pytest.mark.asyncio
async def test_reconciliation_blocks_if_hedge_mode(tmp_path):
    db = DatabaseManager(str(tmp_path / "test_hedge.db"))
    # Client in Hedge Mode (dualSidePosition=True)
    hedge_client = MockBinanceFuturesClient(is_dual_side=True)
    recon = ReconciliationEngine(hedge_client, db)

    with pytest.raises(AccountStateBlockedError):
        await recon.reconcile_all()

