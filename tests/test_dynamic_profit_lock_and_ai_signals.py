import pytest
from datetime import datetime, timezone
from decimal import Decimal

from config.config import AppConfig
from core.enums import ExecutionMode, OrderSide, OrderType, PositionSide, SignalState
from core.models import Order, ParsedSignal, SourceMetadata
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from execution.reconciliation import ReconciliationEngine
from exchange.mock_exchange import MockBinanceFuturesClient
from risk.risk_engine import RiskEngine
from storage.database import DatabaseManager, OrderRepository, SignalRepository


@pytest.fixture
def recon_setup(tmp_path):
    db_file = str(tmp_path / "test_dynamic_recon.db")
    db = DatabaseManager(db_file)
    mock_client = MockBinanceFuturesClient(initial_equity=Decimal("1000.0"))
    config = AppConfig(mode=ExecutionMode.TESTNET, live_trading_enabled=False)
    sig_repo = SignalRepository(db)
    ord_repo = OrderRepository(db)
    risk_eng = RiskEngine(config)
    pos_mgr = PositionManager(mock_client, sig_repo)
    order_mgr = OrderManager(
        client=mock_client,
        order_repo=ord_repo,
        signal_repo=sig_repo,
        position_manager=pos_mgr,
        risk_engine=risk_eng,
        config=config,
    )
    recon = ReconciliationEngine(mock_client, db, order_manager=order_mgr, config=config)
    return recon, mock_client, db


@pytest.mark.asyncio
async def test_dynamic_breakeven_activates_on_gain_without_tp1_filled(recon_setup):
    recon, client, db = recon_setup
    sig_repo = SignalRepository(db)
    ord_repo = OrderRepository(db)

    # 1. Setup Signal: Entry at 60000.0, distant TP1 at 66000.0, initial SL at 58000.0
    cid = -999001
    mid = 12345
    sig_repo.save_message(cid, mid, cid, datetime.utcnow(), datetime.utcnow(), "AI Signal", "AI Signal")
    meta = SourceMetadata(chat_id=cid, message_id=mid, telegram_timestamp=datetime.utcnow())
    parsed = ParsedSignal(
        signal_id="sig_dyn_1",
        metadata=meta,
        symbol_raw="BTC/USDT",
        symbol_candidate="BTCUSDT",
        side=PositionSide.LONG,
        entries=[Decimal("60000.0")],
        stop_loss=Decimal("58000.0"),
        take_profits=[Decimal("66000.0")],
        validation_status=SignalState.OPEN_PROTECTED,
    )
    sig_repo.save_signal(parsed)

    # Local orders
    sl_ord = Order(
        client_order_id="sl_dyn_1",
        signal_id="sig_dyn_1",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.STOP_MARKET,
        trigger_price=Decimal("58000.0"),
        quantity=Decimal("1.0"),
        is_reduce_only=True,
        is_algo=True,
        status="NEW",
    )
    ord_repo.save_order(sl_ord)

    # Mock Binance: Open position 1.0 BTC with entry 60000.0, mark price 61200.0 (+2.0% gain)
    client.positions["BTCUSDT"] = {
        "symbol": "BTCUSDT",
        "positionAmt": "1.0",
        "entryPrice": "60000.0",
        "markPrice": "61200.0",
        "leverage": 10,
    }
    await client.create_algo_order(
        "BTCUSDT", OrderSide.SELL, OrderType.STOP_MARKET,
        Decimal("58000.0"), Decimal("1.0"), client_algo_id="sl_dyn_1"
    )

    # Run reconciliation: Should detect +2.0% gain >= 1.5% and move SL to Breakeven
    report = await recon.reconcile_all()
    assert report["breakeven_activated"] >= 1
    assert any("KÈO BẤT TỬ CHỦ ĐỘNG" in d for d in report["discrepancies"])

    # Verify open algo order moved to ~60060.0 (entry + fee buffer)
    open_algos = await client.get_open_algo_orders("BTCUSDT")
    assert len(open_algos) == 1
    new_sl_price = Decimal(str(open_algos[0]["triggerPrice"]))
    assert new_sl_price >= Decimal("60050.0")


@pytest.mark.asyncio
async def test_dynamic_profit_lock_activates_on_large_gain(recon_setup):
    recon, client, db = recon_setup
    sig_repo = SignalRepository(db)
    ord_repo = OrderRepository(db)

    # Setup Signal already at Breakeven (1.0020), but price surges to 1.0700 (+7.0% gain)
    cid = -999001
    mid = 12346
    sig_repo.save_message(cid, mid, cid, datetime.utcnow(), datetime.utcnow(), "AI Signal", "AI Signal")
    meta = SourceMetadata(chat_id=cid, message_id=mid, telegram_timestamp=datetime.utcnow())
    parsed = ParsedSignal(
        signal_id="sig_dyn_2",
        metadata=meta,
        symbol_raw="DOOD/USDT",
        symbol_candidate="DOODUSDT",
        side=PositionSide.LONG,
        entries=[Decimal("1.0000")],
        stop_loss=Decimal("1.0020"),
        take_profits=[Decimal("1.2000")],
        validation_status=SignalState.OPEN_PROTECTED,
    )
    sig_repo.save_signal(parsed)

    sl_ord = Order(
        client_order_id="be_sig_dyn_2",
        signal_id="sig_dyn_2",
        symbol="DOODUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.STOP_MARKET,
        trigger_price=Decimal("1.0020"),
        quantity=Decimal("500.0"),
        is_reduce_only=True,
        is_algo=True,
        status="NEW",
    )
    ord_repo.save_order(sl_ord)

    # Mock Binance: position at 1.0000, mark price 1.0700 (+7% gain)
    client.positions["DOODUSDT"] = {
        "symbol": "DOODUSDT",
        "positionAmt": "500.0",
        "entryPrice": "1.0000",
        "markPrice": "1.0700",
        "leverage": 10,
    }
    await client.create_algo_order(
        "DOODUSDT", OrderSide.SELL, OrderType.STOP_MARKET,
        Decimal("1.0020"), Decimal("500.0"), client_algo_id="be_sig_dyn_2"
    )

    # Run reconciliation: +7% gain >= 6% tier -> Locks in at least +3.2% profit!
    report = await recon.reconcile_all()
    assert any("KHÓA LÃI TỰ ĐỘNG" in d for d in report["discrepancies"])

    open_algos = await client.get_open_algo_orders("DOODUSDT")
    assert len(open_algos) == 1
    new_sl_price = Decimal(str(open_algos[0]["triggerPrice"]))
    # Must lock in at least 3.2% profit: 1.0000 * 1.032 = 1.032
    assert new_sl_price >= Decimal("1.0300")


@pytest.mark.asyncio
async def test_ai_trader_accepts_quantum_ai_sources_and_executes_safely(tmp_path):
    from services.gemini_autonomous_trader import GeminiAutonomousTrader
    from exchange.mock_exchange import MockBinanceFuturesClient

    config = AppConfig(mode=ExecutionMode.TESTNET, live_trading_enabled=False)
    config.data_dir = str(tmp_path / "data")
    mock_client = MockBinanceFuturesClient(initial_equity=Decimal("500.0"))
    from exchange.exchange_info import SymbolFilterInfo
    mock_client.symbols_info["BMTUSDT"] = SymbolFilterInfo("BMTUSDT", Decimal("0.0001"), Decimal("1.0"), Decimal("1.0"), Decimal("100000"), Decimal("5.0"), True)
    mock_client.symbols_info["BTRUSDT"] = SymbolFilterInfo("BTRUSDT", Decimal("0.0001"), Decimal("1.0"), Decimal("1.0"), Decimal("100000"), Decimal("5.0"), True)

    ai_trader = GeminiAutonomousTrader(
        config=config,
        binance_client=mock_client,
        entry_enabled_provider=lambda: True,
        engine_status_provider=lambda: "RUNNING_LISTEN",
    )

    quantum_setup = {
        "has_setup": True,
        "symbol": "BMTUSDT",
        "direction": "SHORT",
        "archetype": "QUANTUM_SMC_TOP_HUNT",
        "confidence": 88,
        "rationale": "Quantum AI 2.0 4 confluences",
        "entry_price": 0.03700,
        "stop_loss": 0.03790,
        "take_profit_1": 0.03600,
        "take_profit_2": 0.03500,
        "take_profit_3": 0.03400,
        "estimated_rr": 2.8,
        "leverage": 35,
        "risk_verdict": "APPROVED",
        "source": "Quantum AI 2.0 (85%+ Top Hunter - 4 Confluences)",
    }

    whales_setup = {
        "has_setup": True,
        "symbol": "BTRUSDT",
        "direction": "LONG",
        "archetype": "WHALES_CIRCLE_PULLBACK",
        "confidence": 84,
        "rationale": "Whales Circle pullback",
        "entry_price": 0.05470,
        "stop_loss": 0.04928,
        "take_profit_1": 0.06000,
        "take_profit_2": 0.07000,
        "take_profit_3": 0.08000,
        "estimated_rr": 2.8,
        "leverage": 20,
        "risk_verdict": "APPROVED",
        "source": "Quantum AI (WHALES_CIRCLE)",
    }

    # Simulate recent successful scan containing both setups
    ai_trader.last_scan_time = datetime.now(timezone.utc).isoformat()
    ai_trader.last_scan_results = [quantum_setup, whales_setup]

    # Verify _setup_is_current accepts it
    assert ai_trader._setup_is_current(quantum_setup) is True
    assert ai_trader._setup_is_current(whales_setup) is True

    # Execute setup through execute_setup - must not fail with 'AI setup không xuất phát'
    res = await ai_trader.execute_setup(quantum_setup)
    assert res.get("status") == "SUCCESS", f"Execution failed: {res}"
    assert res.get("symbol") == "BMTUSDT"
    assert res.get("side") == "SHORT"

