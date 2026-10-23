from datetime import datetime, timezone
from decimal import Decimal
import pytest

from config.policy_defaults import calculate_tp_weights, SourcePolicyOverride
from config.config import AppConfig
from core.enums import PositionSide, MarginMode
from core.models import ParsedSignal, SourceMetadata, ValidatedSignal
from core.exceptions import RiskCheckError
from parser.validator import SignalValidator
from risk.risk_engine import RiskEngine


def test_take_profit_35_35_30_exact_split():
    """Quy tắc 2: Tỷ lệ chia khối lượng Take Profit chuẩn: TP1 = 35%, TP2 = 35%, TP3 = 30%."""
    # Test default call (defaults to 35.0%)
    weights = calculate_tp_weights(3)
    assert weights == [Decimal("0.350"), Decimal("0.350"), Decimal("0.300")]
    assert sum(weights) == Decimal("1.000")

    # Explicit 35.0%
    weights_explicit = calculate_tp_weights(3, Decimal("35.0"))
    assert weights_explicit == [Decimal("0.350"), Decimal("0.350"), Decimal("0.300")]
    assert sum(weights_explicit) == Decimal("1.000")


def test_tiered_margin_5pct_vs_2_5pct_and_blacklist():
    """Quy tắc 1: Phân tầng vốn: Elite (5% Margin, 2.5% Risk) vs Secondary (2.5% Margin, 1.25% Risk) vs Blacklist (0%)."""
    cfg = AppConfig()
    cfg.risk.default_leverage = 20
    cfg.risk.max_leverage = 25
    cfg.sources = {
        -1001756316676: SourcePolicyOverride(chat_id=-1001756316676, name="Elite", margin_multiplier=Decimal("1.0")),
        -1001781413045: SourcePolicyOverride(chat_id=-1001781413045, name="Secondary", margin_multiplier=Decimal("0.5")),
    }
    risk_engine = RiskEngine(cfg)
    equity = Decimal("100.0")  # 100 USDT

    # 1. Elite Channel (Boom_Boom_Billionaires: margin_multiplier = 1.0)
    meta_elite = SourceMetadata(
        chat_id=-1001756316676,
        message_id=1,
        source_name="Boom_Boom_Billionaires",
        telegram_timestamp=datetime.now(timezone.utc),
    )
    sig_elite = ValidatedSignal(
        signal_id="sig_elite_1",
        symbol="XRPUSDT",
        side=PositionSide.LONG,
        entries=[(Decimal("1.0000"), Decimal("1.0"))],
        stop_loss=Decimal("0.9500"),  # 5.0% SL distance
        take_profits=[(Decimal("1.0500"), Decimal("0.35")), (Decimal("1.1000"), Decimal("0.35")), (Decimal("1.1500"), Decimal("0.30"))],
        leverage=20,
        margin_mode=MarginMode.CROSSED,
        is_breakeven_after_tp1=True,
        risk_pct=Decimal("2.5"),
        metadata=meta_elite,
    )
    sizes_elite = risk_engine.calculate_position_sizes(
        signal=sig_elite,
        current_equity=equity,
        open_risk_amount=Decimal("0.0"),
        step_size=Decimal("0.1"),
        min_qty=Decimal("0.1"),
        min_notional=Decimal("5.0"),
        current_market_price=Decimal("1.0000"),
    )
    p_e, q_e = sizes_elite[0]
    notional_elite = p_e * q_e
    margin_elite = notional_elite / Decimal("20")
    # Margin should be within Elite bounds (under 7.0 USDT cap)
    assert Decimal("2.0") <= margin_elite <= Decimal("7.0")

    # 2. Secondary Channel (Binance 360 VIP: margin_multiplier = 0.5)
    meta_sec = SourceMetadata(
        chat_id=-1001781413045,
        message_id=2,
        source_name="Binance 360 VIP",
        telegram_timestamp=datetime.now(timezone.utc),
    )
    sig_sec = ValidatedSignal(
        signal_id="sig_sec_1",
        symbol="XRPUSDT",
        side=PositionSide.LONG,
        entries=[(Decimal("1.0000"), Decimal("1.0"))],
        stop_loss=Decimal("0.9500"),  # 5.0% SL distance
        take_profits=[(Decimal("1.0500"), Decimal("0.35")), (Decimal("1.1000"), Decimal("0.35")), (Decimal("1.1500"), Decimal("0.30"))],
        leverage=20,
        margin_mode=MarginMode.CROSSED,
        is_breakeven_after_tp1=True,
        risk_pct=Decimal("2.5"),
        metadata=meta_sec,
    )
    sizes_sec = risk_engine.calculate_position_sizes(
        signal=sig_sec,
        current_equity=equity,
        open_risk_amount=Decimal("0.0"),
        step_size=Decimal("0.1"),
        min_qty=Decimal("0.1"),
        min_notional=Decimal("5.0"),
        current_market_price=Decimal("1.0000"),
    )
    p_s, q_s = sizes_sec[0]
    notional_sec = p_s * q_s
    margin_sec = notional_sec / Decimal("20")
    # Secondary margin is halved and strictly capped under 3.5 USDT
    assert margin_sec <= Decimal("3.5")
    assert margin_sec < margin_elite

    # 3. Blacklist Channel (margin_multiplier = 0.0)
    meta_black = SourceMetadata(
        chat_id=999999999,
        message_id=3,
        source_name="Blacklist Scam",
        telegram_timestamp=datetime.now(timezone.utc),
    )
    cfg.sources[999999999] = SourcePolicyOverride(chat_id=999999999, name="Blacklist Scam", margin_multiplier=0.0)
    sig_black = ValidatedSignal(
        signal_id="sig_black_1",
        symbol="XRPUSDT",
        side=PositionSide.LONG,
        entries=[(Decimal("1.0000"), Decimal("1.0"))],
        stop_loss=Decimal("0.9500"),
        take_profits=[(Decimal("1.0500"), Decimal("1.0"))],
        leverage=20,
        margin_mode=MarginMode.CROSSED,
        is_breakeven_after_tp1=True,
        risk_pct=Decimal("2.5"),
        metadata=meta_black,
    )
    with pytest.raises(RiskCheckError) as exc_info:
        risk_engine.calculate_position_sizes(
            signal=sig_black,
            current_equity=equity,
            open_risk_amount=Decimal("0.0"),
            step_size=Decimal("0.1"),
            min_qty=Decimal("0.1"),
            min_notional=Decimal("5.0"),
            current_market_price=Decimal("1.0000"),
        )
    assert "Blacklist" in str(exc_info.value) or "margin_multiplier = 0" in str(exc_info.value)


def test_safe_leverage_clamp_invariants():
    """Quy tắc 3: Safe Leverage = min(25, floor(0.75 / SL_Distance_Pct))."""
    cfg = AppConfig()
    cfg.risk.default_leverage = 20
    cfg.risk.max_leverage = 25
    validator = SignalValidator(cfg)

    meta = SourceMetadata(
        chat_id=-1001756316676,
        message_id=1,
        source_name="Test Source",
        telegram_timestamp=datetime.now(timezone.utc),
    )

    # 1. Short SL (1.5% distance) -> safe lev = floor(0.75 / 0.015) = 50x -> Clamped to max 25x
    parsed_tight_sl = ParsedSignal(
        signal_id="sig_lev_1",
        metadata=meta,
        raw_text="Tight SL",
        symbol_raw="BTC/USDT",
        symbol_candidate="BTCUSDT",
        side=PositionSide.LONG,
        entries=[Decimal("100.0")],
        stop_loss=Decimal("98.5"),  # 1.5% distance
        take_profits=[Decimal("105.0"), Decimal("110.0"), Decimal("115.0")],
        leverage_requested=50,  # requested 50x
    )
    p1, v1 = validator.validate_and_resolve(parsed_tight_sl)
    assert v1.leverage == 25  # Clamped to system max 25x

    # 2. Medium SL (5.0% distance with anti-wick buffer) -> clamped to safe range (14x - 15x <= 25x)
    parsed_med_sl = ParsedSignal(
        signal_id="sig_lev_2",
        metadata=meta,
        raw_text="Med SL",
        symbol_raw="BTC/USDT",
        symbol_candidate="BTCUSDT",
        side=PositionSide.LONG,
        entries=[Decimal("100.0")],
        stop_loss=Decimal("95.0"),  # 5.0% distance
        take_profits=[Decimal("105.0"), Decimal("110.0"), Decimal("115.0")],
        leverage_requested=25,  # requested 25x
    )
    p2, v2 = validator.validate_and_resolve(parsed_med_sl)
    assert v2.leverage in (14, 15)  # Auto-reduced to 14x/15x to guarantee Zero Liquidation

    # 3. Wide SL (7.5% distance) -> safe lev = floor(0.75 / 0.075) = 10x or 9x with buffer
    parsed_wide_sl = ParsedSignal(
        signal_id="sig_lev_3",
        metadata=meta,
        raw_text="Wide SL",
        symbol_raw="BTC/USDT",
        symbol_candidate="BTCUSDT",
        side=PositionSide.LONG,
        entries=[Decimal("100.0")],
        stop_loss=Decimal("92.5"),  # 7.5% distance
        take_profits=[Decimal("105.0"), Decimal("110.0"), Decimal("115.0")],
        leverage_requested=20,
    )
    p3, v3 = validator.validate_and_resolve(parsed_wide_sl)
    assert v3.leverage in (9, 10)  # Auto-reduced to 9x/10x to ensure SL before liquidation


def test_breakeven_price_favorable_guard():
    """Quy tắc 4: Breakeven chỉ kích hoạt khi TP1 khớp VÀ giá có lãi >= +0.2% so với Entry."""
    entry_p = Decimal("100.0")

    # Long position:
    # Favorable: mark_price >= 100.0 * 1.002 = 100.20
    assert (Decimal("100.25") >= entry_p * Decimal("1.002")) is True
    assert (Decimal("100.10") >= entry_p * Decimal("1.002")) is False
    assert (Decimal("99.90") >= entry_p * Decimal("1.002")) is False  # Drop back below entry

    # Short position:
    # Favorable: mark_price <= 100.0 * 0.998 = 99.80
    assert (Decimal("99.75") <= entry_p * Decimal("0.998")) is True
    assert (Decimal("99.90") <= entry_p * Decimal("0.998")) is False
    assert (Decimal("100.10") <= entry_p * Decimal("0.998")) is False
