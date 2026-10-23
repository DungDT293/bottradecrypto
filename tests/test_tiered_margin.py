import pytest
from datetime import datetime
from decimal import Decimal
from config.config import AppConfig
from config.policy_defaults import SourcePolicyOverride
from core.enums import MarginMode, OrderSide, OrderType, PositionSide
from core.models import SourceMetadata, ValidatedSignal
from risk.risk_engine import RiskEngine

def test_tiered_margin_elite_vs_secondary():
    cfg = AppConfig()
    cfg.risk.default_leverage = 20
    cfg.risk.max_leverage = 25
    cfg.sources = {
        -1001756316676: SourcePolicyOverride(chat_id=-1001756316676, name="Elite", margin_multiplier=Decimal("1.0")),
        -1001895315984: SourcePolicyOverride(chat_id=-1001895315984, name="Secondary", margin_multiplier=Decimal("0.5")),
    }
    engine = RiskEngine(cfg)
    equity = Decimal("82.70")
    now = datetime.utcnow()

    # Case A: Standard SL distance (~3.44% SL distance: Entry 0.3200, SL 0.3090)
    meta_elite = SourceMetadata(chat_id=-1001756316676, message_id=1001, telegram_timestamp=now)
    sig_elite = ValidatedSignal(
        signal_id="sig_test_elite",
        symbol="GTCUSDT",
        side=PositionSide.LONG,
        entries=[(Decimal("0.3200"), Decimal("1.0"))],
        stop_loss=Decimal("0.3090"),
        take_profits=[(Decimal("0.3400"), Decimal("1.0"))],
        leverage=10,
        margin_mode=MarginMode.CROSSED,
        is_breakeven_after_tp1=True,
        risk_pct=Decimal("2.5"),
        metadata=meta_elite,
    )

    sizes_elite = engine.calculate_position_sizes(
        signal=sig_elite,
        current_equity=equity,
        open_risk_amount=Decimal("0.0"),
        step_size=Decimal("0.1"),
        min_qty=Decimal("0.1"),
        min_notional=Decimal("5.0"),
        current_market_price=Decimal("0.3200"),
    )
    p_e, q_e = sizes_elite[0]
    notional_elite = p_e * q_e
    margin_elite = notional_elite / Decimal("10")

    meta_sec = SourceMetadata(chat_id=-1001895315984, message_id=1002, telegram_timestamp=now)
    sig_sec = ValidatedSignal(
        signal_id="sig_test_sec",
        symbol="GTCUSDT",
        side=PositionSide.LONG,
        entries=[(Decimal("0.3200"), Decimal("1.0"))],
        stop_loss=Decimal("0.3090"),
        take_profits=[(Decimal("0.3400"), Decimal("1.0"))],
        leverage=10,
        margin_mode=MarginMode.CROSSED,
        is_breakeven_after_tp1=True,
        risk_pct=Decimal("2.5"),
        metadata=meta_sec,
    )

    sizes_sec = engine.calculate_position_sizes(
        signal=sig_sec,
        current_equity=equity,
        open_risk_amount=Decimal("0.0"),
        step_size=Decimal("0.1"),
        min_qty=Decimal("0.1"),
        min_notional=Decimal("5.0"),
        current_market_price=Decimal("0.3200"),
    )
    p_s, q_s = sizes_sec[0]
    notional_sec = p_s * q_s
    margin_sec = notional_sec / Decimal("10")

    print(f"\n[Standard SL 3.4%] Elite Margin: {margin_elite:.2f} USDT (Notional: {notional_elite:.2f})")
    print(f"[Standard SL 3.4%] Secondary Margin: {margin_sec:.2f} USDT (Notional: {notional_sec:.2f})")

    # Elite is exactly double Secondary (5.0% vs 2.5% of equity)
    assert margin_elite > margin_sec
    assert abs(margin_elite - margin_sec * Decimal("2.0")) < Decimal("0.2")
    # Margin for Elite is ~5% to 7% of 82.7 (~$4.5 - $5.8)
    assert Decimal("4.5") <= margin_elite <= Decimal("6.0")
    # Margin for Secondary is ~2.5% to 3.5% of 82.7 (~$2.2 - $3.0)
    assert Decimal("2.2") <= margin_sec <= Decimal("3.0")

