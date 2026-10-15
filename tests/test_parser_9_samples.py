from datetime import datetime
from decimal import Decimal
import pytest

from config.config import load_config
from config.policy_defaults import SourcePolicyOverride
from core.enums import EntryMode, EntryRangePolicy, MultiEntryWeightMode, MultiTPWeightMode, PositionSide, SignalState
from core.models import SourceMetadata
from parser.signal_parser import SignalParser
from parser.validator import SignalValidator
from tests.fixtures.sample_signals import SAMPLE_SIGNALS


@pytest.fixture
def parser():
    return SignalParser()


@pytest.fixture
def default_config():
    return load_config()


def create_metadata(chat_id: int = 1001, msg_id: int = 1) -> SourceMetadata:
    return SourceMetadata(
        chat_id=chat_id,
        message_id=msg_id,
        telegram_timestamp=datetime.utcnow(),
    )


def test_sample_1_grass(parser, default_config):
    meta = create_metadata(1001, 1)
    parsed = parser.parse(SAMPLE_SIGNALS["GRASS"], meta)

    assert parsed.symbol_candidate == "GRASSUSDT"
    assert parsed.side == PositionSide.LONG
    assert parsed.entries == [Decimal("0.5020"), Decimal("0.4870")]
    assert parsed.entry_mode == EntryMode.MULTIPLE
    assert parsed.take_profits == [Decimal("0.5230"), Decimal("0.5440")]
    assert parsed.tp_weights == [Decimal("0.5"), Decimal("0.5")]
    assert parsed.stop_loss == Decimal("0.4720")
    assert parsed.is_breakeven_mandatory is False  # "Consider moving SL" is optional hint
    assert any("don’t chase above ." in w for w in parsed.warnings)

    # Initial state needs policy for multi-entry weights
    assert parsed.validation_status == SignalState.NEEDS_POLICY

    # When approved policy is supplied, it validates
    override = SourcePolicyOverride(chat_id=1001, name="GRASS_SOURCE", allow_multi_entry_equal_split=True)
    validator = SignalValidator(default_config)
    _, validated = validator.validate_and_resolve(parsed, override)
    assert validated is not None
    assert validated.symbol == "GRASSUSDT"
    assert len(validated.entries) == 2


def test_sample_2_zerebro(parser, default_config):
    meta = create_metadata(1002, 2)
    parsed = parser.parse(SAMPLE_SIGNALS["ZEREBRO"], meta)

    assert parsed.symbol_candidate == "ZEREBROUSDT"
    assert parsed.side == PositionSide.LONG
    assert parsed.entries == [Decimal("0.04800")]
    assert parsed.entry_mode == EntryMode.SINGLE
    assert parsed.take_profits == [Decimal("0.04905"), Decimal("0.05100"), Decimal("0.05500")]
    assert parsed.stop_loss == Decimal("0.04480")
    assert parsed.leverage_range == (20, 50)
    assert parsed.leverage_requested == 20  # Never picks highest (50)

    # Missing TP weights -> NEEDS_POLICY
    assert parsed.validation_status == SignalState.NEEDS_POLICY

    # Test resolution with approved policy
    override = SourcePolicyOverride(chat_id=1002, name="ZEREBRO_SOURCE", allow_tp_equal_split=True)
    validator = SignalValidator(default_config)
    _, validated = validator.validate_and_resolve(parsed, override)
    assert validated is not None
    # Leverage clamped to max_leverage (5)
    assert validated.leverage == 5


def test_sample_3_rsr(parser, default_config):
    meta = create_metadata(1003, 3)
    parsed = parser.parse(SAMPLE_SIGNALS["RSR"], meta)

    assert parsed.symbol_candidate == "RSRUSDT"
    assert parsed.side == PositionSide.LONG
    assert parsed.entries == [Decimal("0.002075")]
    assert len(parsed.take_profits) == 4
    assert parsed.stop_loss == Decimal("0.001925")
    assert parsed.validation_status == SignalState.NEEDS_POLICY


def test_sample_4_truth_ambiguous_entry(parser, default_config):
    meta = create_metadata(1004, 4)
    parsed = parser.parse(SAMPLE_SIGNALS["TRUTH"], meta)

    assert parsed.symbol_candidate == "TRUTHUSDT"
    assert parsed.side == PositionSide.SHORT
    # Regression: TRUTH must have exactly 3 TPs with exact Decimal values
    assert parsed.take_profits == [
        Decimal("0.02250"),
        Decimal("0.02175"),
        Decimal("0.019999"),
    ]
    # "Short BELOW (0.02300)(0.02325)" is ambiguous -> NEEDS_REVIEW
    assert parsed.validation_status == SignalState.NEEDS_REVIEW
    assert "Short BELOW" in parsed.blocking_reason

    # Validator must NOT validate this signal
    validator = SignalValidator(default_config)
    _, validated = validator.validate_and_resolve(parsed)
    assert validated is None


def test_sample_5_q_usd_unsupported_and_ambiguous_sl(parser, default_config):
    meta = create_metadata(1005, 5)
    parsed = parser.parse(SAMPLE_SIGNALS["Q_USD"], meta)

    # Q/USD has quote USD, not USDT
    assert parsed.symbol_candidate is None
    # SL "052506" is ambiguous integer string, not auto-fixed
    assert parsed.stop_loss is None
    # Regression: Q/USD must extract exactly 6 TPs with exact Decimal values
    assert parsed.take_profits == [
        Decimal("0.04970"),
        Decimal("0.04920"),
        Decimal("0.04870"),
        Decimal("0.04820"),
        Decimal("0.04760"),
        Decimal("0.04710"),
    ]
    assert parsed.validation_status == SignalState.REJECTED

    validator = SignalValidator(default_config)
    _, validated = validator.validate_and_resolve(parsed)
    assert validated is None


def test_sample_6_ake_misspellings_and_leverage(parser, default_config):
    meta = create_metadata(1006, 6)
    parsed = parser.parse(SAMPLE_SIGNALS["AKE"], meta)

    assert parsed.symbol_candidate == "AKEUSDT"
    assert parsed.side == PositionSide.LONG
    # Handled ENTERY PRICE: 0.02923
    assert parsed.entries == [Decimal("0.02923")]
    # Handled STOPP LOSS: 0.02740
    assert parsed.stop_loss == Decimal("0.02740")
    assert len(parsed.take_profits) == 3
    # Leverage 25X TO 50X -> range (25, 50), requested does not pick highest
    assert parsed.leverage_range == (25, 50)
    assert parsed.leverage_requested == 25


def test_sample_7_qtum_range_entry(parser, default_config):
    meta = create_metadata(1007, 7)
    parsed = parser.parse(SAMPLE_SIGNALS["QTUM"], meta)

    assert parsed.symbol_candidate == "QTUMUSDT"
    assert parsed.side == PositionSide.SHORT
    assert parsed.entry_mode == EntryMode.RANGE
    assert parsed.entries == [Decimal("0.8960"), Decimal("0.9160")]
    assert parsed.stop_loss == Decimal("0.9360")
    assert parsed.validation_status == SignalState.NEEDS_POLICY

    # Resolve with range midpoint policy
    override = SourcePolicyOverride(chat_id=1007, name="QTUM_SOURCE", allow_range_midpoint=True, allow_tp_equal_split=True)
    validator = SignalValidator(default_config)
    _, validated = validator.validate_and_resolve(parsed, override)
    assert validated is not None
    assert validated.entries == [(Decimal("0.9060"), Decimal("1.0"))]


def test_sample_8_eth_200x_and_breakeven(parser, default_config):
    meta = create_metadata(1008, 8)
    parsed = parser.parse(SAMPLE_SIGNALS["ETH"], meta)

    assert parsed.symbol_candidate == "ETHUSDT"
    assert parsed.side == PositionSide.SHORT
    assert parsed.entries == [Decimal("2367"), Decimal("2387")]
    assert parsed.stop_loss == Decimal("2408")
    assert parsed.take_profits == [Decimal("2344"), Decimal("2305"), Decimal("2250")]
    assert parsed.is_breakeven_mandatory is True  # Explicit trailing BE after TP1
    assert parsed.leverage_requested == 200  # Raw requested

    # Resolve with policies and verify leverage is clamped to max 5x
    override = SourcePolicyOverride(chat_id=1008, name="ETH_SOURCE", allow_multi_entry_equal_split=True, allow_tp_equal_split=True)
    validator = SignalValidator(default_config)
    _, validated = validator.validate_and_resolve(parsed, override)
    assert validated is not None
    assert validated.leverage == 5  # Clamped! Never copied 200x
    assert validated.is_breakeven_after_tp1 is True


def test_sample_9_atom_direction_contradiction(parser, default_config):
    meta = create_metadata(1009, 9)
    parsed = parser.parse(SAMPLE_SIGNALS["ATOM"], meta)

    assert parsed.symbol_candidate == "ATOMUSDT"
    # Contradiction: #SHORT in header but BUY : in entry
    assert parsed.validation_status == SignalState.NEEDS_REVIEW
    assert "Mau thuan huong lenh" in parsed.blocking_reason

    # Must NOT validate
    validator = SignalValidator(default_config)
    _, validated = validator.validate_and_resolve(parsed)
    assert validated is None

