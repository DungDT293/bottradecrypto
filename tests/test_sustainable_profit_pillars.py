import sqlite3
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from config.config import AppConfig
from core.enums import MarginMode, PositionSide
from core.models import SourceMetadata, ValidatedSignal
from parser.validator import SignalValidator
from risk.risk_engine import RiskEngine
from services.channel_analytics_service import ChannelAnalyticsService


def test_pillar_5_funding_and_liquidity_filter():
    # 1. Normal funding and high volume -> Allowed
    ok, err = SignalValidator.validate_funding_and_liquidity(
        funding_rate=0.0005,  # +0.05%
        quote_volume_24h=50_000_000.0,
    )
    assert ok
    assert err is None

    # 2. Dangerous positive funding (+0.20% > +0.15%) -> Blocked
    ok, err = SignalValidator.validate_funding_and_liquidity(
        funding_rate=0.0020,  # +0.20%
        quote_volume_24h=50_000_000.0,
    )
    assert not ok
    assert "Funding rate" in err

    # 3. Dangerous negative funding (-0.18% < -0.15%) -> Blocked
    ok, err = SignalValidator.validate_funding_and_liquidity(
        funding_rate=-0.0018,
        quote_volume_24h=50_000_000.0,
    )
    assert not ok
    assert "Funding rate" in err

    # 4. Low liquidity (< 15,000,000 USDT) -> Blocked
    ok, err = SignalValidator.validate_funding_and_liquidity(
        funding_rate=0.0001,
        quote_volume_24h=8_500_000.0,
    )
    assert not ok
    assert "Thanh khoản 24h" in err


def test_pillar_4_atr_volatility_adjusted_sizing():
    config = AppConfig()
    engine = RiskEngine(config)

    meta = SourceMetadata(
        chat_id=-1001520053536,
        message_id=101,
        telegram_timestamp=datetime.now(timezone.utc),
    )
    signal = ValidatedSignal(
        signal_id="sig_atr_test",
        symbol="SOLUSDT",
        side=PositionSide.LONG,
        entries=[(Decimal("100.0"), Decimal("1.0"))],
        stop_loss=Decimal("99.0"),  # 1.0 USDT SL distance
        take_profits=[(Decimal("105.0"), Decimal("1.0"))],
        leverage=20,
        margin_mode=MarginMode.ISOLATED,
        is_breakeven_after_tp1=True,
        risk_pct=Decimal("1.5"),
        metadata=meta,
    )

    # High volatility coin: ATR = 6.0 USDT on 100.0 price (6.0% > 5.0%)
    # Tight SL: 1.0 USDT < 1.5 * 6.0 = 9.0 USDT
    adjusted = engine.apply_atr_volatility_sizing(
        signal=signal,
        atr_1h=Decimal("6.0"),
        current_price=Decimal("100.0"),
    )

    # 1. Risk must be lowered to 1.0% NAV
    assert adjusted.risk_pct == Decimal("1.0")

    # 2. Stop loss must be safely widened to ref_entry - 1.5 * ATR = 100.0 - 9.0 = 91.0
    assert adjusted.stop_loss == Decimal("91.0")
    assert len(adjusted.warnings) >= 2


def test_pillar_2_circuit_breaker_3_consecutive_sls(tmp_path):
    db_file = str(tmp_path / "test_cb.db")
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE signals (
            signal_id TEXT PRIMARY KEY,
            chat_id INTEGER,
            message_id INTEGER,
            symbol TEXT
        )
    """)
    c.execute("""
        CREATE TABLE signal_timeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT,
            event_type TEXT,
            description TEXT,
            timestamp TEXT
        )
    """)

    # Populate 3 consecutive Stop Losses within last 48 hours for chat_id -1001700314832
    chat_id = -1001700314832
    now = datetime.now(timezone.utc)
    for i in range(3):
        sig_id = f"sig_{i}"
        t_str = (now - timedelta(hours=i * 2 + 1)).isoformat()
        c.execute("INSERT INTO signals VALUES (?, ?, ?, ?)", (sig_id, chat_id, 1000 + i, f"COIN{i}USDT"))
        c.execute("INSERT INTO signal_timeline (signal_id, event_type, description, timestamp) VALUES (?, ?, ?, ?)",
                  (sig_id, "EXCHANGE_SL_FILLED", "Hit Stop Loss", t_str))
    conn.commit()
    conn.close()

    svc = ChannelAnalyticsService(db_path=db_file)
    is_tripped, reason = svc.check_circuit_breaker(chat_id)
    assert is_tripped
    assert "dính 3 Stop Loss liên tiếp" in reason
    assert "MUTED_TEMPORARY" in reason


def test_pillar_6_smart_queue_enqueuing():
    from services.signal_queue_service import SignalQueueService
    from core.models import SourceMetadata, ValidatedSignal
    from core.enums import PositionSide, MarginMode

    queue = SignalQueueService(default_ttl_seconds=1200)

    meta = SourceMetadata(
        chat_id=-1001520053536,
        message_id=201,
        telegram_timestamp=datetime.now(timezone.utc),
    )
    sig = ValidatedSignal(
        signal_id="sig_queue_test_1",
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        entries=[(Decimal("90000.0"), Decimal("1.0"))],
        stop_loss=Decimal("88000.0"),
        take_profits=[(Decimal("95000.0"), Decimal("1.0"))],
        leverage=20,
        margin_mode=MarginMode.ISOLATED,
        is_breakeven_after_tp1=True,
        risk_pct=Decimal("1.5"),
        metadata=meta,
    )

    # 1. Enqueue Tier 1 signal
    res = queue.enqueue(signal=sig, chat_id=-1001520053536, channel_name="Coin Chief", priority=1)
    assert res is True
    assert len(queue._queue) == 1

    # 2. Duplicate symbol rejected
    res_dup = queue.enqueue(signal=sig, chat_id=-1001520053536, channel_name="Coin Chief", priority=1)
    assert res_dup is False
    assert len(queue._queue) == 1

    # 3. Dequeue next returns correct item
    dequeued = queue.dequeue_next()
    assert dequeued is not None
    assert dequeued.signal.symbol == "BTCUSDT"
    assert len(queue._queue) == 0


def test_pillar_3_trailing_tp_moonbag_calculation():
    from execution.trailing_tp_manager import TrailingTakeProfitManager
    from core.enums import PositionSide

    mgr = TrailingTakeProfitManager(
        pump_threshold_pct=Decimal("2.0"),
        trail_distance_pct=Decimal("1.5"),
    )

    # Long scenario: Ref TP2 = 100, Current SL = 98
    # Price hits 104 (+4% gain) -> Should update SL to 104 * 0.985 = 102.44
    update, new_sl, reason = mgr.calculate_trailing_stop(
        side=PositionSide.LONG,
        reference_price=Decimal("100.0"),
        current_mark_price=Decimal("104.0"),
        current_sl=Decimal("98.0"),
        key="sig_moon_1",
    )
    assert update is True
    assert new_sl == Decimal("102.44")
    assert "LONG Moonbag trailing" in reason


def test_pillar_7_compounding_capital_stages():
    # Stage 1: $127.05 -> Stage 1, target 150.0
    stage1 = RiskEngine.get_compounding_stage(Decimal("127.05"))
    assert stage1["stage"] == 1
    assert stage1["max_positions"] == 4
    assert stage1["recommended_risk_pct"] == 1.5
    assert stage1["target_equity"] == 150.0
    assert 60.0 < stage1["progress_pct"] < 75.0

    # Stage 2: $300.0 -> Stage 2, target 500.0
    stage2 = RiskEngine.get_compounding_stage(Decimal("300.0"))
    assert stage2["stage"] == 2
    assert stage2["max_positions"] == 6

    # Stage 3: $1200.0 -> Stage 3
    stage3 = RiskEngine.get_compounding_stage(Decimal("1200.0"))
    assert stage3["stage"] == 3
    assert stage3["recommended_risk_pct"] == 1.2

    # Stage 4: $5000.0 -> Stage 4
    stage4 = RiskEngine.get_compounding_stage(Decimal("5000.0"))
    assert stage4["stage"] == 4
    assert stage4["recommended_risk_pct"] == 1.0


@pytest.mark.asyncio
async def test_pillar_6_auto_slot_freed_notification():
    from unittest.mock import AsyncMock, MagicMock
    from execution.reconciliation import ReconciliationEngine

    mock_client = AsyncMock()
    mock_db = MagicMock()
    freed_called = False

    async def on_freed():
        nonlocal freed_called
        freed_called = True

    recon = ReconciliationEngine(
        exchange_client=mock_client,
        db=mock_db,
        on_slot_freed_callback=on_freed,
    )
    await recon._notify_slot_freed()
    assert freed_called is True
