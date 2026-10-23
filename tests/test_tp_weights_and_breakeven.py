from datetime import datetime
from decimal import Decimal
import pytest

from config.policy_defaults import calculate_tp_weights
from config.config import load_config
from core.enums import MarginMode, MultiTPWeightMode, PositionSide, SignalState
from core.models import ParsedSignal, SourceMetadata
from parser.validator import SignalValidator


def test_calculate_tp_weights_3_targets():
    # 60% TP1 -> Remainder 40% -> TP2 = 40% * 0.65 = 26%, TP3 = 14%
    w = calculate_tp_weights(3, Decimal("60.0"))
    assert w == [Decimal("0.600"), Decimal("0.260"), Decimal("0.140")]
    assert sum(w) == Decimal("1.000")

    # 70% TP1 -> Remainder 30% -> TP2 = 30% * 0.65 = 19.5%, TP3 = 10.5%
    w2 = calculate_tp_weights(3, Decimal("70.0"))
    assert w2 == [Decimal("0.700"), Decimal("0.195"), Decimal("0.105")]
    assert sum(w2) == Decimal("1.000")

    # 50% TP1 -> Remainder 50% -> TP2 = 50% * 0.65 = 32.5%, TP3 = 17.5%
    w3 = calculate_tp_weights(3, Decimal("50.0"))
    assert w3 == [Decimal("0.500"), Decimal("0.325"), Decimal("0.175")]
    assert sum(w3) == Decimal("1.000")


def test_calculate_tp_weights_2_targets():
    w = calculate_tp_weights(2, Decimal("65.0"))
    assert w == [Decimal("0.650"), Decimal("0.350")]
    assert sum(w) == Decimal("1.000")


def test_calculate_tp_weights_1_target():
    w = calculate_tp_weights(1, Decimal("60.0"))
    assert w == [Decimal("1.0")]


def test_calculate_tp_weights_clamping():
    # Below 10% clamped to 10%
    w_low = calculate_tp_weights(2, Decimal("5.0"))
    assert w_low[0] == Decimal("0.100")

    # Above 90% clamped to 90%
    w_high = calculate_tp_weights(2, Decimal("95.0"))
    assert w_high[0] == Decimal("0.900")


def test_calculate_tp_weights_20_40_40():
    w = calculate_tp_weights(3, Decimal("20.0"))
    assert w == [Decimal("0.200"), Decimal("0.400"), Decimal("0.400")]
    assert sum(w) == Decimal("1.000")


def test_validator_with_fixed_20_40_40():
    config = load_config()
    config.execution.multi_tp_default_weight_mode = MultiTPWeightMode.FIXED_20_40_40

    validator = SignalValidator(config)
    meta = SourceMetadata(chat_id=12345, message_id=1, telegram_timestamp=datetime.utcnow())
    parsed = ParsedSignal(
        signal_id="sig_tp_20_40_40",
        metadata=meta,
        symbol_raw="BTC/USDT",
        symbol_candidate="BTCUSDT",
        side=PositionSide.LONG,
        entries=[Decimal("60000")],
        stop_loss=Decimal("58000"),
        take_profits=[Decimal("62000"), Decimal("64000"), Decimal("68000")],
        validation_status=SignalState.PARSED,
    )

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None
    assert len(validated.take_profits) == 3
    assert validated.take_profits[0][1] == Decimal("0.200")
    assert validated.take_profits[1][1] == Decimal("0.400")
    assert validated.take_profits[2][1] == Decimal("0.400")
    assert validated.is_breakeven_after_tp1 is True


def test_validator_with_custom_tp1_ratio():
    config = load_config()
    config.execution.multi_tp_default_weight_mode = MultiTPWeightMode.CUSTOM_TP1_RATIO
    config.execution.tp1_target_weight_pct = Decimal("60.0")

    validator = SignalValidator(config)
    meta = SourceMetadata(chat_id=12345, message_id=1, telegram_timestamp=datetime.utcnow())
    parsed = ParsedSignal(
        signal_id="sig_tp_custom",
        metadata=meta,
        symbol_raw="BTC/USDT",
        symbol_candidate="BTCUSDT",
        side=PositionSide.LONG,
        entries=[Decimal("60000")],
        stop_loss=Decimal("58000"),
        take_profits=[Decimal("62000"), Decimal("64000"), Decimal("68000")],
        validation_status=SignalState.PARSED,
    )

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None
    assert len(validated.take_profits) == 3
    # Check weights: 60%, 26%, 14%
    assert validated.take_profits[0][1] == Decimal("0.600")
    assert validated.take_profits[1][1] == Decimal("0.260")
    assert validated.take_profits[2][1] == Decimal("0.140")
    assert validated.is_breakeven_after_tp1 is True
