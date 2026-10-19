import pytest
from datetime import datetime
from decimal import Decimal
from config.config import load_config
from core.enums import MarginMode, PositionSide
from core.models import SourceMetadata, ValidatedSignal
from risk.risk_engine import RiskEngine, RiskCheckError

def make_signal(chat_id: int, entries, stop_loss: Decimal, leverage: int = 10, risk_pct: Decimal = Decimal("2.5")):
    now = datetime.utcnow()
    return ValidatedSignal(
        signal_id=f"sig_{chat_id}_{stop_loss}",
        symbol="ALTUSDT",
        side=PositionSide.LONG,
        entries=entries,
        stop_loss=stop_loss,
        take_profits=[(Decimal("1.2000"), Decimal("1.0"))],
        leverage=leverage,
        margin_mode=MarginMode.CROSSED,
        is_breakeven_after_tp1=True,
        risk_pct=risk_pct,
        metadata=SourceMetadata(chat_id=chat_id, message_id=123, telegram_timestamp=now),
    )

def test_tiered_margin_all_scenarios():
    cfg = load_config("config.yaml")
    engine = RiskEngine(cfg)
    equity = Decimal("82.70")
    
    chat_elite = -1001756316676  # Boom Boom Billionaires (Elite mult=1.0)
    chat_scalp = -1001895315984  # Crypto Quality Signals (Secondary mult=0.5)

    # -------------------------------------------------------------
    # Scenario 1: Standard SL (3.0% distance: Entry 1.0000, SL 0.9700)
    # -------------------------------------------------------------
    sig_elite_std = make_signal(chat_elite, [(Decimal("1.0000"), Decimal("1.0"))], Decimal("0.9700"), leverage=10)
    sig_scalp_std = make_signal(chat_scalp, [(Decimal("1.0000"), Decimal("1.0"))], Decimal("0.9700"), leverage=10)

    res_elite = engine.calculate_position_sizes(
        sig_elite_std, equity, Decimal("0"), Decimal("0.1"), Decimal("0.1"), Decimal("5.0"), Decimal("1.0000")
    )
    res_scalp = engine.calculate_position_sizes(
        sig_scalp_std, equity, Decimal("0"), Decimal("0.1"), Decimal("0.1"), Decimal("5.0"), Decimal("1.0000")
    )

    notional_e = res_elite[0][0] * res_elite[0][1]
    margin_e = notional_e / Decimal("10")
    notional_s = res_scalp[0][0] * res_scalp[0][1]
    margin_s = notional_s / Decimal("10")

    assert margin_e > margin_s
    # Exactly 2:1 ratio within step_size rounding
    ratio = margin_e / margin_s
    assert Decimal("1.9") <= ratio <= Decimal("2.1")
    # Elite margin ~5.0% - 7.0% ($4.15 - $5.79)
    assert Decimal("4.0") <= margin_e <= Decimal("6.0")
    # Scalp margin ~2.0% - 3.5% ($2.00 - $3.00)
    assert Decimal("2.0") <= margin_s <= Decimal("3.0")

    # -------------------------------------------------------------
    # Scenario 2: Tight SL (0.8% distance: Entry 1.0000, SL 0.9920) -> Capped by Max Margin
    # -------------------------------------------------------------
    sig_elite_tight = make_signal(chat_elite, [(Decimal("1.0000"), Decimal("1.0"))], Decimal("0.9920"), leverage=10)
    sig_scalp_tight = make_signal(chat_scalp, [(Decimal("1.0000"), Decimal("1.0"))], Decimal("0.9920"), leverage=10)

    res_e_tight = engine.calculate_position_sizes(
        sig_elite_tight, equity, Decimal("0"), Decimal("0.1"), Decimal("0.1"), Decimal("5.0"), Decimal("1.0000")
    )
    res_s_tight = engine.calculate_position_sizes(
        sig_scalp_tight, equity, Decimal("0"), Decimal("0.1"), Decimal("0.1"), Decimal("5.0"), Decimal("1.0000")
    )

    margin_e_tight = (res_e_tight[0][0] * res_e_tight[0][1]) / Decimal("10")
    margin_s_tight = (res_s_tight[0][0] * res_s_tight[0][1]) / Decimal("10")

    # Elite capped at 7% ($5.789 -> max margin)
    assert margin_e_tight <= Decimal("5.79")
    # Scalp capped at 3.5% ($2.894 -> max margin)
    assert margin_s_tight <= Decimal("2.90")
    assert margin_e_tight > margin_s_tight

    # -------------------------------------------------------------
    # Scenario 3: Wide SL (7.0% distance: Entry 1.0000, SL 0.9300) -> Bounded by Risk Budget
    # -------------------------------------------------------------
    sig_elite_wide = make_signal(chat_elite, [(Decimal("1.0000"), Decimal("1.0"))], Decimal("0.9300"), leverage=10)
    sig_scalp_wide = make_signal(chat_scalp, [(Decimal("1.0000"), Decimal("1.0"))], Decimal("0.9300"), leverage=10)

    res_e_wide = engine.calculate_position_sizes(
        sig_elite_wide, equity, Decimal("0"), Decimal("0.1"), Decimal("0.1"), Decimal("5.0"), Decimal("1.0000")
    )
    res_s_wide = engine.calculate_position_sizes(
        sig_scalp_wide, equity, Decimal("0"), Decimal("0.1"), Decimal("0.1"), Decimal("5.0"), Decimal("1.0000")
    )

    loss_e_wide = res_e_wide[0][1] * (Decimal("1.0000") - Decimal("0.9300"))
    loss_s_wide = res_s_wide[0][1] * (Decimal("1.0000") - Decimal("0.9300"))

    # Max risk budget for Elite is 2.5% of 82.7 = 2.0675 USDT
    assert loss_e_wide <= Decimal("2.07")
    # Max risk budget for Scalp is 1.25% of 82.7 = 1.03375 USDT
    assert loss_s_wide <= Decimal("1.04")

    # -------------------------------------------------------------
    # Scenario 4: Max Open Risk Limit (12.0% of 82.7 = 9.924 USDT)
    # -------------------------------------------------------------
    # With 8.50 open risk: 8.50 + 2.07 = 10.57 > 9.924 (Elite fails)
    with pytest.raises(RiskCheckError, match="Vuot qua han muc tong rui ro dang mo"):
        engine.calculate_position_sizes(
            sig_elite_std, equity, Decimal("8.50"), Decimal("0.1"), Decimal("0.1"), Decimal("5.0"), Decimal("1.0000")
        )
    # 8.50 + 1.03 = 9.53 <= 9.924 (Scalp passes!)
    res_scalp_fit = engine.calculate_position_sizes(
        sig_scalp_std, equity, Decimal("8.50"), Decimal("0.1"), Decimal("0.1"), Decimal("5.0"), Decimal("1.0000")
    )
    assert len(res_scalp_fit) == 1
