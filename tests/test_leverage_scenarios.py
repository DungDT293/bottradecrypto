import pytest
from datetime import datetime
from decimal import Decimal
from config.config import load_config
from core.enums import MarginMode, PositionSide, SignalState
from core.models import SourceMetadata, ParsedSignal
from config.policy_defaults import SourcePolicyOverride
from parser.validator import SignalValidator
from risk.risk_engine import RiskEngine

@pytest.fixture
def test_setup():
    cfg = load_config("config.yaml")
    validator = SignalValidator(cfg)
    risk_engine = RiskEngine(cfg)
    now = datetime.utcnow()
    return cfg, validator, risk_engine, now

def create_parsed_signal(
    symbol="ETHUSDT",
    entry=Decimal("3000.00"),
    sl=Decimal("2910.00"),  # 3.0% SL
    tps=None,
    leverage_requested=None,
    leverage_range=None,
    chat_id=-1001756316676,
    now=None
):
    if tps is None:
        tps = [Decimal("3090.00"), Decimal("3180.00"), Decimal("3300.00")]
    meta = SourceMetadata(chat_id=chat_id, message_id=5555, telegram_timestamp=now or datetime.utcnow())
    return ParsedSignal(
        signal_id=f"sig_{chat_id}_{entry}",
        symbol_raw=symbol,
        symbol_candidate=symbol,
        side=PositionSide.LONG,
        entries=[entry],
        stop_loss=sl,
        take_profits=tps,
        leverage_requested=leverage_requested,
        leverage_range=leverage_range,
        margin_mode_requested=MarginMode.CROSSED,
        metadata=meta
    )

def test_scenario_1_range_10x_to_50x_normal_sl(test_setup):
    """When Admin gives range 10x-50x with normal SL (2.5%), bot picks 20x (in 11x-25x)."""
    cfg, validator, _, now = test_setup
    parsed = create_parsed_signal(
        entry=Decimal("100.00"),
        sl=Decimal("97.50"),  # 2.5% SL distance -> safe_lev = int(0.75/0.025) = 30x
        leverage_range=(10, 50),
        chat_id=-1001756316676,
        now=now
    )
    override = cfg.sources.get("-1001756316676")
    _, validated = validator.validate_and_resolve(parsed, override)
    assert validated is not None
    assert parsed.validation_status == SignalState.VALIDATED
    assert validated.leverage == 20, f"Expected 20x, got {validated.leverage}x"

def test_scenario_2_range_20x_to_50x_normal_sl(test_setup):
    """When Admin gives range 20x-50x with normal SL (3.0%), bot picks 20x."""
    cfg, validator, _, now = test_setup
    parsed = create_parsed_signal(
        entry=Decimal("100.00"),
        sl=Decimal("97.00"),  # 3.0% SL distance -> safe_lev = int(0.75/0.03) = 25x
        leverage_range=(20, 50),
        chat_id=-1002266035358,  # Secondary channel
        now=now
    )
    override = cfg.sources.get("-1002266035358")
    _, validated = validator.validate_and_resolve(parsed, override)
    assert validated is not None
    assert validated.leverage == 20

def test_scenario_3_single_high_leverage_100x_clamped_to_25x(test_setup):
    """When Admin asks 100x with tight SL (2.0%), clamped safely to system max 25x."""
    cfg, validator, _, now = test_setup
    parsed = create_parsed_signal(
        entry=Decimal("100.00"),
        sl=Decimal("98.00"),  # 2.0% SL distance -> safe_lev = int(0.75/0.02) = 37x
        leverage_requested=100,
        chat_id=-1001756316676,
        now=now
    )
    override = cfg.sources.get("-1001756316676")
    _, validated = validator.validate_and_resolve(parsed, override)
    assert validated is not None
    assert validated.leverage == 25, f"Expected 25x, got {validated.leverage}x"

def test_scenario_4_single_leverage_15x_respected(test_setup):
    """When Admin asks 15x (within 11x-25x) with normal SL (3.5%), bot respects 15x."""
    cfg, validator, _, now = test_setup
    parsed = create_parsed_signal(
        entry=Decimal("100.00"),
        sl=Decimal("96.50"),  # 3.5% SL distance -> safe_lev = int(0.75/0.035) = 21x
        leverage_requested=15,
        chat_id=-1001895315984,
        now=now
    )
    override = cfg.sources.get("-1001895315984")
    _, validated = validator.validate_and_resolve(parsed, override)
    assert validated is not None
    assert validated.leverage == 15

def test_scenario_5_no_leverage_specified_uses_default_20x(test_setup):
    """When message doesn't specify leverage, bot uses default 20x (in 11x-25x)."""
    cfg, validator, _, now = test_setup
    parsed = create_parsed_signal(
        entry=Decimal("100.00"),
        sl=Decimal("97.00"),  # 3.0% SL distance
        leverage_requested=None,
        leverage_range=None,
        chat_id=-1001781413045,
        now=now
    )
    override = cfg.sources.get("-1001781413045")
    _, validated = validator.validate_and_resolve(parsed, override)
    assert validated is not None
    assert validated.leverage == 20

def test_scenario_6_wide_sl_6_pct_clamped_to_safe_11x_or_12x(test_setup):
    """When Admin gives 6.0% SL and asks 25x, bot clamps to 11x (accounting for sl buffer)."""
    cfg, validator, _, now = test_setup
    parsed = create_parsed_signal(
        entry=Decimal("100.00"),
        sl=Decimal("94.00"),  # 6.0% SL distance + 0.3% buffer -> safe_lev = 11x
        leverage_requested=25,
        chat_id=-1001756316676,
        now=now
    )
    override = cfg.sources.get("-1001756316676")
    _, validated = validator.validate_and_resolve(parsed, override)
    assert validated is not None
    assert validated.leverage in (11, 12)

def test_scenario_7_wide_sl_7_5_pct_clamped_to_9x_or_10x(test_setup):
    """When Admin gives 7.5% SL (like GTCUSDT), bot clamps to 9x-10x for Zero Liquidation."""
    cfg, validator, _, now = test_setup
    parsed = create_parsed_signal(
        entry=Decimal("0.3200"),
        sl=Decimal("0.2960"),  # 7.5% SL distance -> safe_lev = 9-10x
        leverage_range=(25, 50),
        chat_id=-1002266035358,
        now=now
    )
    override = cfg.sources.get("-1002266035358")
    _, validated = validator.validate_and_resolve(parsed, override)
    assert validated is not None
    assert validated.leverage in (9, 10)

def test_scenario_8_extreme_sl_11_2_pct_clamped_to_6x(test_setup):
    """When Admin gives 11.2% SL (like BATUSDT), bot clamps to 6x for Zero Liquidation."""
    cfg, validator, _, now = test_setup
    parsed = create_parsed_signal(
        entry=Decimal("0.1840"),
        sl=Decimal("0.1634"),  # 11.2% SL distance -> safe_lev = int(0.75/0.112) = 6x
        leverage_range=(50, 75),
        chat_id=-1001895315984,
        now=now
    )
    override = cfg.sources.get("-1001895315984")
    _, validated = validator.validate_and_resolve(parsed, override)
    assert validated is not None
    assert validated.leverage == 6

def test_scenario_9_position_sizing_at_20x_leverage(test_setup):
    """Verify that at 20x leverage, Elite and Scalp position sizes are accurate and exceed min notional."""
    cfg, validator, risk_engine, now = test_setup
    equity = Decimal("82.70")
    
    # Elite signal (mult 1.0) with 20x leverage
    parsed_e = create_parsed_signal(
        entry=Decimal("1.0000"),
        sl=Decimal("0.9700"),  # 3.0% SL
        leverage_range=(10, 50),
        chat_id=-1001756316676,
        now=now
    )
    _, val_e = validator.validate_and_resolve(parsed_e, cfg.sources.get("-1001756316676"))
    assert val_e.leverage == 20
    
    sizes_e = risk_engine.calculate_position_sizes(
        val_e, equity, Decimal("0"), Decimal("0.1"), Decimal("0.1"), Decimal("5.0"), Decimal("1.0000")
    )
    p_e, q_e = sizes_e[0]
    notional_e = p_e * q_e
    margin_e = notional_e / Decimal("20")
    
    # Secondary Scalp signal (mult 0.5) with 20x leverage
    parsed_s = create_parsed_signal(
        entry=Decimal("1.0000"),
        sl=Decimal("0.9700"),  # 3.0% SL
        leverage_range=(10, 50),
        chat_id=-1001895315984,
        now=now
    )
    _, val_s = validator.validate_and_resolve(parsed_s, cfg.sources.get("-1001895315984"))
    assert val_s.leverage == 20
    
    sizes_s = risk_engine.calculate_position_sizes(
        val_s, equity, Decimal("0"), Decimal("0.1"), Decimal("0.1"), Decimal("5.0"), Decimal("1.0000")
    )
    p_s, q_s = sizes_s[0]
    notional_s = p_s * q_s
    margin_s = notional_s / Decimal("20")
    
    print(f"\n[20x Leverage] Elite Notional: {notional_e:.2f} USDT, Margin: {margin_e:.2f} USDT")
    print(f"[20x Leverage] Scalp Notional: {notional_s:.2f} USDT, Margin: {margin_s:.2f} USDT")
    
    # Both exceed Binance $5.00 min notional
    assert notional_e >= Decimal("5.0")
    assert notional_s >= Decimal("5.0")
    # Ratio between Elite and Scalp notional is exactly 2:1
    assert abs(notional_e - notional_s * Decimal("2.0")) < Decimal("1.0")
    # Loss at SL strictly bounded by risk budget
    loss_e = q_e * (Decimal("1.0000") - Decimal("0.9700"))
    assert loss_e <= Decimal("2.07")  # 2.5% of $82.70
    loss_s = q_s * (Decimal("1.0000") - Decimal("0.9700"))
    assert loss_s <= Decimal("1.04")  # 1.25% of $82.70
