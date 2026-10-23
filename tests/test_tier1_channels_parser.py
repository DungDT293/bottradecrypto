from datetime import datetime, timezone
from decimal import Decimal
import pytest

from core.models import SourceMetadata
from core.enums import PositionSide, SignalState
from parser.signal_parser import SignalParser
from parser.validator import SignalValidator
from config.config import AppConfig


@pytest.fixture
def parser():
    return SignalParser()


@pytest.fixture
def validator():
    config = AppConfig()
    config.execution.allow_below_pattern_as_valid = True
    return SignalValidator(config)


def test_crypto_hunters_signal(parser, validator):
    text = """☄️ Project Type :- SCALP 
🟢PAIR: #BTR/USDT
⚡️ Direction : LONG
🛠 Leverage: Cross 20x to 50x
🩷 Entrys : 0.06350
🏆 Targets:
1️⃣ 0.06490
2️⃣ 0.06750
3️⃣ 0.07100
⛔️ Stop-Loss: 0.05940"""
    meta = SourceMetadata(chat_id=-1002191067035, message_id=1, telegram_timestamp=datetime.now(timezone.utc), received_at=datetime.now(timezone.utc))
    parsed = parser.parse(text, meta)
    assert parsed.symbol_candidate == "BTRUSDT"
    assert parsed.side == PositionSide.LONG
    assert len(parsed.take_profits) == 3
    parsed, validated = validator.validate_and_resolve(parsed, None)
    assert validated is not None
    assert validated.symbol == "BTRUSDT"


def test_whales_circle_signal(parser, validator):
    text = """🐳 DOS/USDT #LONG 🐳
✳️ ENTRY :- 0.2250 - 0.2150
💢 LEVERAGE :- 20X
🔖 TARGET :- 
1 : 0.2350
2 : 0.2500
3 : 0.2700
⛔️ STOP-LOSS :- 0.2100
☝️ Margin Use 2–3%"""
    meta = SourceMetadata(chat_id=-1001700314832, message_id=2, telegram_timestamp=datetime.now(timezone.utc), received_at=datetime.now(timezone.utc))
    parsed = parser.parse(text, meta)
    assert parsed.symbol_candidate == "DOSUSDT"
    assert len(parsed.take_profits) == 3
    parsed, validated = validator.validate_and_resolve(parsed, None)
    assert validated is not None
    assert validated.symbol == "DOSUSDT"


def test_bitcoin_bulls_pipe_targets_signal(parser, validator):
    text = """⌛#CHZ/USDT  ( LONG )
🍁 Leverage 👉 20X to 25X 
⛩️ Entry ➡️ 0.01346 - 0.01349
💠 Targets :- 0.01362 | 0.01374 | 0.01389 | 0.01403 | 0.01419 | 0.01436
🔕 Stoploss = 0.01300"""
    meta = SourceMetadata(chat_id=-1001391574614, message_id=3, telegram_timestamp=datetime.now(timezone.utc), received_at=datetime.now(timezone.utc))
    parsed = parser.parse(text, meta)
    assert parsed.symbol_candidate == "CHZUSDT"
    assert len(parsed.take_profits) == 6
    parsed, validated = validator.validate_and_resolve(parsed, None)
    assert validated is not None
    assert len(validated.take_profits) == 6


def test_crypto_spider_scalper_signal(parser, validator):
    text = """🚀 #ZEREBROUSDT LONG SIGNAL 🚀
⚡️ LEVERAGE 50X–75X
📌 ENTRY ➜ 0.02930
🎯 TAKE PROFIT LEVELS
① 🟢 TP1 ➜ 0.03010
② 🟢 TP2 ➜ 0.03050
③ 🟢 TP3 ➜ 0.03245
④ 🟢 TP4 ➜ 0.03520
🚫 STOP LOSS 0.02710"""
    meta = SourceMetadata(chat_id=-1001895315984, message_id=4, telegram_timestamp=datetime.now(timezone.utc), received_at=datetime.now(timezone.utc))
    parsed = parser.parse(text, meta)
    assert parsed.symbol_candidate == "ZEREBROUSDT"
    assert len(parsed.take_profits) == 4
    parsed, validated = validator.validate_and_resolve(parsed, None)
    assert validated is not None


def test_crypto_monk_square_emoji_signal(parser, validator):
    text = """#LONG 🟢
#ONDO/USDT
Margin Mode : Isolated 💎
Signal Type : Scalp Trade🔥
BUY :
1) 0.4327 - 100% 
Take Profit Targets : 
1)🟩 0.4377
2)🟩 0.4457
3)🟩 0.4544
4)🟩 0.4631
5)🟩 0.4759
🟥 SL : 0.4103 - 100%   
📊 LEV : 20X"""
    meta = SourceMetadata(chat_id=-1001552004524, message_id=5, telegram_timestamp=datetime.now(timezone.utc), received_at=datetime.now(timezone.utc))
    parsed = parser.parse(text, meta)
    assert parsed.symbol_candidate == "ONDOUSDT"
    assert len(parsed.take_profits) == 5
    parsed, validated = validator.validate_and_resolve(parsed, None)
    assert validated is not None


def test_crypto_leopard_inline_medals_signal(parser, validator):
    text = """#LDO     /USDT (LONG) 🔼🔼
⌛LEVERAGE : 20X TO 75X
📊 LONG BELOW (0.03800)(0.03770)
🪙 TARGETS 
🥇  0.03900  🥈  0.04050  🥉 0.04300
 ⚠️ STOPLOSS : 0.03650"""
    meta = SourceMetadata(chat_id=-1002052872813, message_id=6, telegram_timestamp=datetime.now(timezone.utc), received_at=datetime.now(timezone.utc))
    parsed = parser.parse(text, meta)
    assert parsed.symbol_candidate == "LDOUSDT"
    assert len(parsed.take_profits) == 3
    parsed, validated = validator.validate_and_resolve(parsed, None)
    assert validated is not None

