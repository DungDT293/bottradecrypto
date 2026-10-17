from datetime import datetime
from decimal import Decimal
import pytest

from config.config import load_config
from core.enums import PositionSide, SignalState
from core.models import SourceMetadata
from parser.signal_parser import SignalParser
from parser.validator import SignalValidator


@pytest.fixture
def parser():
    return SignalParser()


@pytest.fixture
def validator():
    return SignalValidator(load_config())


def make_meta():
    return SourceMetadata(
        chat_id=9999,
        message_id=101,
        telegram_timestamp=datetime.utcnow(),
    )


def test_long_with_sl_above_entry_is_rejected(parser, validator):
    text = """
    BTC/USDT LONG
    Entry: 60000
    SL: 62000
    TP: 65000
    """
    parsed = parser.parse(text, make_meta())
    assert parsed.validation_status != SignalState.REJECTED  # parser parsed values
    _, val = validator.validate_and_resolve(parsed)
    assert val is None
    assert parsed.validation_status == SignalState.REJECTED
    assert "LONG nhung SL" in parsed.blocking_reason


def test_short_with_sl_below_entry_is_rejected(parser, validator):
    text = """
    SOL/USDT SHORT
    Entry: 150
    SL: 140
    TP: 120
    """
    parsed = parser.parse(text, make_meta())
    _, val = validator.validate_and_resolve(parsed)
    assert val is None
    assert parsed.validation_status == SignalState.REJECTED
    assert "SHORT nhung SL" in parsed.blocking_reason


def test_long_with_tp_below_entry_is_rejected(parser, validator):
    text = """
    BTC/USDT LONG
    Entry: 60000
    SL: 58000
    TP: 55000
    """
    parsed = parser.parse(text, make_meta())
    _, val = validator.validate_and_resolve(parsed)
    assert val is None
    assert parsed.validation_status == SignalState.REJECTED
    assert "LONG nhung TP" in parsed.blocking_reason


def test_short_with_tp_above_entry_is_rejected(parser, validator):
    text = """
    ETH/USDT SHORT
    Entry: 2500
    SL: 2600
    TP: 2800
    """
    parsed = parser.parse(text, make_meta())
    _, val = validator.validate_and_resolve(parsed)
    assert val is None
    assert parsed.validation_status == SignalState.REJECTED
    assert "SHORT nhung TP" in parsed.blocking_reason


def test_missing_sl_is_rejected(parser, validator):
    text = """
    SOL/USDT LONG
    Entry: 150
    TP: 180
    """
    parsed = parser.parse(text, make_meta())
    assert parsed.validation_status == SignalState.REJECTED
    assert "Thieu Stop Loss" in parsed.blocking_reason


def test_dangerous_content_and_links_are_neutralized(parser, validator):
    text = """
    #DOGE/USDT LONG
    Entry: 0.1200
    TP1: 0.1400
    SL: 0.1100
    rm -rf / && calc.exe
    [Click here to win bonus](https://malicious-phishing.com/hack)
    """
    parsed = parser.parse(text, make_meta())
    assert parsed.symbol_candidate == "DOGEUSDT"
    assert parsed.side == PositionSide.LONG
    # The URL should have been stripped by normalizer
    from parser.normalizer import normalize_text
    norm = normalize_text(text)
    assert "https://malicious-phishing.com" not in norm


def test_sl_distance_limits(parser, validator):
    # SL distance too small (0.01% away)
    too_close = """
    BTC/USDT LONG
    Entry: 50000
    SL: 49999
    TP: 55000
    """
    parsed = parser.parse(too_close, make_meta())
    _, val = validator.validate_and_resolve(parsed)
    assert val is None
    assert "SL qua hep" in parsed.blocking_reason

    # SL distance too large (50% away)
    too_far = """
    BTC/USDT LONG
    Entry: 50000
    SL: 20000
    TP: 60000
    """
    parsed2 = parser.parse(too_far, make_meta())
    _, val2 = validator.validate_and_resolve(parsed2)
    assert val2 is None
    assert "SL qua xa" in parsed2.blocking_reason


def test_vip_promotional_bait_is_rejected(parser):
    bait_text = """
    🚀 #BTCUSDT LONG SIGNAL 🚀
    Entry: 65000
    Targets: 70000
    Stop Loss: SL in VIP
    DM for VIP access and 100% guaranteed profit!
    """
    parsed = parser.parse(bait_text, make_meta())
    assert parsed.validation_status == SignalState.REJECTED
    assert "cau keo VIP" in parsed.blocking_reason


def test_vip_result_boasting_classified_as_update():
    from parser.update_parser import ChannelUpdateParser
    from core.enums import UpdateType

    u_parser = ChannelUpdateParser()
    boast_text = "👑VIP Group Update👑 🏹 #BATUSDT — Take-profit target 03! ✅ 🛡+612.98% Massive Gain🚀 🛫DM for VIP Access"
    u_type, val, desc = u_parser.parse_update(boast_text)
    assert u_type == UpdateType.RESULT_TP_REPORTED

    invite_text = "✨That’s your chance to join our premium channel for free... ONLY FIRST 100 CAN JOIN ⚡️"
    u_type2, _, desc2 = u_parser.parse_update(invite_text)
    assert u_type2 == UpdateType.COMMENTARY


