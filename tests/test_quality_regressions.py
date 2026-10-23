from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from config.config import AppConfig
from core.enums import ExecutionMode, MarginMode, OrderSide, OrderType, PositionSide, SignalState
from core.exceptions import ExchangeAdapterError, EmergencyCloseError
from core.models import ParsedSignal, SourceMetadata
from exchange.binance_client import BinanceFuturesClient
from exchange.mock_exchange import MockBinanceFuturesClient
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from execution.reconciliation import ReconciliationEngine
from risk.risk_engine import RiskEngine
from services.binance_service import BinanceService
from services.gemini_autonomous_trader import GeminiAutonomousTrader
from services.stats_service import StatsService, VN_TZ
from storage.database import DatabaseManager, OrderRepository, SignalRepository


@pytest.mark.asyncio
async def test_account_sync_fails_closed_without_fabricating_balances(monkeypatch):
    config = AppConfig(mode=ExecutionMode.TESTNET)
    config.binance.testnet_api_key = "test-key"
    config.binance.testnet_api_secret = "test-secret"
    service = BinanceService(config)

    async def offline_request(self, method, endpoint, params=None, signed=False, _retry_count=0):
        raise ExchangeAdapterError("offline test exchange")

    monkeypatch.setattr(BinanceFuturesClient, "_request", offline_request)

    snapshot = await service.sync_account(force=True)

    assert snapshot.is_connected is False
    assert snapshot.can_trade is False
    assert snapshot.wallet_balance is None
    assert snapshot.equity is None
    assert "offline test exchange" in (snapshot.error_message or "")


class _FailTakeProfitClient(MockBinanceFuturesClient):
    async def create_standard_order(self, *args, **kwargs):
        if kwargs.get("order_type") == OrderType.LIMIT and kwargs.get("reduce_only"):
            raise ExchangeAdapterError("simulated TP rejection")
        return await super().create_standard_order(*args, **kwargs)


@pytest.mark.asyncio
async def test_take_profit_failure_emergency_closes_filled_position(tmp_path):
    db = DatabaseManager(str(tmp_path / "tp_failure.db"))
    signal_repo = SignalRepository(db)
    order_repo = OrderRepository(db)
    config = AppConfig(mode=ExecutionMode.TESTNET)
    client = _FailTakeProfitClient(initial_equity=Decimal("10000"))
    position_manager = PositionManager(client, signal_repo)
    order_manager = OrderManager(
        client=client,
        order_repo=order_repo,
        signal_repo=signal_repo,
        position_manager=position_manager,
        risk_engine=RiskEngine(config),
        config=config,
    )

    now = datetime.utcnow()
    signal_repo.save_message(1, 1, 1, now, now, "signal", "signal")
    signal = ParsedSignal(
        signal_id="sig_tp_failure",
        metadata=SourceMetadata(chat_id=1, message_id=1, telegram_timestamp=now),
        symbol_raw="BTC/USDT",
        symbol_candidate="BTCUSDT",
        side=PositionSide.LONG,
        validation_status=SignalState.ENTRY_PENDING,
    )
    signal_repo.save_signal(signal)

    await MockBinanceFuturesClient.create_standard_order(
        client,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.025"),
        price=Decimal("60000"),
    )

    validated = type("Validated", (), {
        "signal_id": "sig_tp_failure",
        "symbol": "BTCUSDT",
        "side": PositionSide.LONG,
        "stop_loss": Decimal("58000"),
        "take_profits": [(Decimal("62000"), Decimal("0.5")), (Decimal("65000"), Decimal("0.5"))],
    })()

    with pytest.raises(EmergencyCloseError, match="TP1|Emergency close"):
        await order_manager.on_entry_filled(validated, Decimal("0.025"), Decimal("60000"))

    position = await client.get_position("BTCUSDT")
    assert Decimal(str(position["positionAmt"])) == Decimal("0")
    assert signal_repo.get_signal("sig_tp_failure")["state"] == SignalState.CLOSED.value


@pytest.mark.asyncio
async def test_reconciliation_does_not_adopt_unowned_exchange_position(tmp_path):
    db = DatabaseManager(str(tmp_path / "unknown_owner.db"))
    repo = SignalRepository(db)
    config = AppConfig(mode=ExecutionMode.TESTNET)
    client = MockBinanceFuturesClient()
    client.positions["BTCUSDT"] = {
        "symbol": "BTCUSDT",
        "positionAmt": "0.1",
        "entryPrice": "60000",
        "markPrice": "60100",
    }
    recon = ReconciliationEngine(client, db, config=config)

    now = datetime.utcnow()
    repo.save_message(2, 2, 2, now, now, "signal", "signal")
    repo.save_signal(ParsedSignal(
        signal_id="sig_unknown_owner",
        metadata=SourceMetadata(chat_id=2, message_id=2, telegram_timestamp=now),
        symbol_raw="BTC/USDT",
        symbol_candidate="BTCUSDT",
        side=PositionSide.LONG,
        entries=[Decimal("60000")],
        stop_loss=Decimal("58000"),
        take_profits=[Decimal("62000"), Decimal("64000")],
        validation_status=SignalState.ENTRY_PENDING,
        leverage_requested=5,
        margin_mode_requested=MarginMode.ISOLATED,
    ))

    report = await recon.reconcile_all()

    assert report["positions_protected"] == 0
    assert any("không chứng minh được quyền sở hữu" in item for item in report["discrepancies"])
    assert repo.get_signal("sig_unknown_owner")["state"] == SignalState.ENTRY_PENDING.value
    assert client.open_algo_orders == {}


def test_pnl_signs_and_local_day_period_filter(tmp_path):
    db = DatabaseManager(str(tmp_path / "pnl.db"))
    service = StatsService(db, AppConfig())
    today = datetime.now(VN_TZ).date()
    yesterday = today - timedelta(days=1)

    with db.get_connection() as conn:
        for date_str, realized, fees, net in (
            (yesterday.isoformat(), "99", "9", "90"),
            (today.isoformat(), "10", "2", "9"),
        ):
            conn.execute(
                """
                INSERT INTO daily_pnl
                (date_str, starting_equity, realized_pnl, fees_paid, net_pnl, deposits_withdrawals, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (date_str, "1000", realized, fees, net, "0", datetime.utcnow().isoformat()),
            )

    summary = service.get_pnl_summary(days_back=0)

    assert summary["realized_pnl"] == "10.00"
    assert summary["commission"] == "2.00"
    assert summary["funding_fee"] == "1.00"
    assert summary["net_pnl"] == "9.00"


@pytest.mark.asyncio
async def test_ai_execution_mode_gate_stops_before_client_calls():
    config = AppConfig(mode=ExecutionMode.READ_ONLY, live_trading_enabled=False)

    class NoCallClient:
        def __getattr__(self, name):
            raise AssertionError(f"client called: {name}")

    trader = GeminiAutonomousTrader(config=config, binance_client=NoCallClient())

    result = await trader.execute_setup({})

    assert result["status"] == "SKIPPED"
    assert "READ_ONLY" in result["reason"]


@pytest.mark.asyncio
async def test_ai_execution_requires_active_lifecycle_even_when_exchange_writes_enabled():
    config = AppConfig(mode=ExecutionMode.TESTNET)

    class NoCallClient:
        def __getattr__(self, name):
            raise AssertionError(f"client called: {name}")

    trader = GeminiAutonomousTrader(
        config=config,
        binance_client=NoCallClient(),
        entry_enabled_provider=lambda: True,
        engine_status_provider=lambda: "STOPPED",
    )
    result = await trader.execute_setup({})
    assert result["status"] == "SKIPPED"
    assert "protected engine lifecycle" in result["reason"]


def test_ai_setup_requires_fresh_scan_match():
    config = AppConfig(mode=ExecutionMode.TESTNET)
    trader = GeminiAutonomousTrader(config=config, binance_client=None)
    setup = {
        "has_setup": True,
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "confidence": 80,
        "risk_verdict": "APPROVED",
        "source": "Quant Engine Fallback",
        "entry_price": 100,
        "stop_loss": 98,
        "take_profit_1": 103,
        "take_profit_2": 105,
        "take_profit_3": 108,
    }
    assert trader._setup_is_current(setup) is False
