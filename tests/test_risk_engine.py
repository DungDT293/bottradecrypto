from datetime import datetime
from decimal import Decimal
import pytest

from config.config import load_config
from core.enums import MarginMode, PositionSide
from core.exceptions import RiskCheckError
from core.models import SourceMetadata, ValidatedSignal
from risk.risk_engine import RiskEngine


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def risk_engine(config):
    return RiskEngine(config)


def create_sample_validated_signal(entries, sl, risk_pct=Decimal("0.5")) -> ValidatedSignal:
    meta = SourceMetadata(chat_id=100, message_id=1, telegram_timestamp=datetime.utcnow())
    return ValidatedSignal(
        signal_id="sig_test_risk_1",
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        entries=entries,
        stop_loss=sl,
        take_profits=[(Decimal("70000"), Decimal("1.0"))],
        leverage=5,
        margin_mode=MarginMode.ISOLATED,
        is_breakeven_after_tp1=False,
        risk_pct=risk_pct,
        metadata=meta,
    )


def test_calculate_position_size_single_entry(risk_engine):
    # Entry: 60000, SL: 58000 (distance = 2000)
    # Equity = 10000 USDT, Risk 0.5% = 50 USDT
    # Buffer factor = 1 + (0.1 + 0.1)% = 1.002
    signal = create_sample_validated_signal([(Decimal("60000"), Decimal("1.0"))], Decimal("58000"))
    sizes = risk_engine.calculate_position_sizes(
        signal=signal,
        current_equity=Decimal("10000"),
        open_risk_amount=Decimal("0"),
        step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        min_notional=Decimal("5.0"),
        current_market_price=Decimal("60000"),
    )

    assert len(sizes) == 1
    price, qty = sizes[0]
    assert price == Decimal("60000")
    # Expected qty ~ 50 / 2000 = 0.025
    assert Decimal("0.024") <= qty <= Decimal("0.025")
    # Verify strict risk limit
    risk = qty * abs(price - signal.stop_loss)
    assert risk <= Decimal("50.0")


def test_calculate_position_size_multi_entry_worst_case(risk_engine):
    # 2 entries: 60000 (50%), 59000 (50%), SL: 58000
    signal = create_sample_validated_signal(
        [(Decimal("60000"), Decimal("0.5")), (Decimal("59000"), Decimal("0.5"))],
        Decimal("58000"),
    )
    sizes = risk_engine.calculate_position_sizes(
        signal=signal,
        current_equity=Decimal("10000"),
        open_risk_amount=Decimal("0"),
        step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        min_notional=Decimal("5.0"),
        current_market_price=Decimal("60000"),
    )

    assert len(sizes) == 2
    total_risk = sum(qty * abs(p - signal.stop_loss) for p, qty in sizes)
    # Total risk across ALL pending entries must not exceed 50 USDT
    assert total_risk <= Decimal("50.0")


def test_reject_when_exceeds_max_total_open_risk(risk_engine):
    signal = create_sample_validated_signal([(Decimal("60000"), Decimal("1.0"))], Decimal("58000"))
    # Max open risk is 2% of 10000 = 200 USDT.
    # If existing open risk is already 190 USDT, new trade wants 50 USDT -> total 240 > 200 -> REJECT!
    with pytest.raises(RiskCheckError) as exc:
        risk_engine.calculate_position_sizes(
            signal=signal,
            current_equity=Decimal("10000"),
            open_risk_amount=Decimal("190"),
            step_size=Decimal("0.001"),
            min_qty=Decimal("0.001"),
            min_notional=Decimal("5.0"),
            current_market_price=Decimal("60000"),
        )
    assert "Vuot qua han muc tong rui ro dang mo" in str(exc.value)


def test_reject_when_notional_below_min_notional(risk_engine):
    # Entry: 2000, SL: 1000 (distance = 1000)
    # Equity = 500 USDT, Risk 0.5% = 2.5 USDT
    # Qty = 2.5 / 1000 = 0.0025, rounded to step_size 0.001 -> qty = 0.002
    # minQty = 0.001 -> qty (0.002) >= minQty (0.001) passes qty check!
    # Notional = 0.002 * 2000 = 4.0 USDT < minNotional (5.0 USDT) -> triggers minNotional rejection!
    signal = create_sample_validated_signal([(Decimal("2000"), Decimal("1.0"))], Decimal("1000"))
    with pytest.raises(RiskCheckError) as exc:
        risk_engine.calculate_position_sizes(
            signal=signal,
            current_equity=Decimal("500"),
            open_risk_amount=Decimal("0"),
            step_size=Decimal("0.001"),
            min_qty=Decimal("0.001"),
            min_notional=Decimal("5.0"),
            current_market_price=Decimal("2000"),
        )
    assert "nho hon minNotional" in str(exc.value)


def test_daily_loss_limit(risk_engine):
    # Max daily loss is 3%
    starting_equity = Decimal("10000")
    # Loss of 200 USDT (2%) -> not halted
    assert risk_engine.check_daily_loss_limit(starting_equity, Decimal("200")) is False
    # Loss of 300 USDT (3%) -> HALTED!
    assert risk_engine.check_daily_loss_limit(starting_equity, Decimal("300")) is True
    # Loss of 350 USDT (3.5%) -> HALTED!
    assert risk_engine.check_daily_loss_limit(starting_equity, Decimal("350")) is True
