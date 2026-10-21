from datetime import datetime, timezone
from decimal import Decimal
import pytest

from core.enums import EntryMode, PositionSide, SignalState
from core.models import SourceMetadata
from parser.signal_parser import SignalParser


@pytest.fixture
def parser():
    return SignalParser()


def create_metadata(chat_id: int = -1001781413045, msg_id: int = 237139) -> SourceMetadata:
    now = datetime.now(timezone.utc)
    return SourceMetadata(
        chat_id=chat_id,
        message_id=msg_id,
        telegram_timestamp=now,
        received_at=now,
    )


def test_binance_360_vip_ctrusdt(parser):
    """Signal CTRUSDT from Binance 360 VIP with bare decimal TPs after 'Take Profits :'"""
    text = """🔥 MTC Indicator 🔥

 15 Minutes Timeframe

🔴 SHORT

#CTR/USDT

Entry zone : 0.0174677 - 0.0169590

Take Profits : 

0.0168733
0.0163620
0.0158507
0.0153394
0.0148281

Stop loss :0.01814613

Leverage: 10x"""

    meta = create_metadata(-1001781413045, 237139)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "CTRUSDT"
    assert parsed.side == PositionSide.SHORT
    assert parsed.entries == [Decimal("0.0174677"), Decimal("0.0169590")]
    assert parsed.entry_mode == EntryMode.RANGE
    assert parsed.stop_loss == Decimal("0.01814613")
    assert parsed.take_profits == [
        Decimal("0.0168733"),
        Decimal("0.0163620"),
        Decimal("0.0158507"),
        Decimal("0.0153394"),
        Decimal("0.0148281"),
    ]
    assert parsed.leverage_requested == 10


def test_estr_bullet_sl_regression(parser):
    """ESTR signal where SL was previously parsed as 1 instead of 0.018100"""
    text = """PAIR: HEMI/USDT
DIRECTION: LONG

Entry Price
1) 0.018700

Take Profit (TP):
1) 0.019500

Stop-Loss (SL):
1) 0.018100

Leverage: 20x (Cross)
Risk Reminder: Use only 2% of your capital per trade"""

    meta = create_metadata(-1001656921849, 50542)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "HEMIUSDT"
    assert parsed.side == PositionSide.LONG
    assert parsed.entries == [Decimal("0.018700")]
    assert parsed.stop_loss == Decimal("0.018100")
    assert parsed.take_profits == [Decimal("0.019500")]


def test_binance_team_long_zone_and_target_bullets(parser):
    """Binance Team signal with LONG ZONE and numbered target emojis without 'Take Profit' header"""
    text = """🔱 Trade: #ASTER/USDT 🔱

🟢 LONG ZONE: 0.69 - 0.67

🀄️ LEVERAGE: 20x

1.🎯 0.7020
2.🎯 0.7075
3.🎯 0.7122
4.🎯 0.7158
5.🎯 0.7203
6.🎯 0.7255

⛔️ STOP-LOSS: 0.6642"""

    meta = create_metadata(-1001212188460, 44217)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "ASTERUSDT"
    assert parsed.side == PositionSide.LONG
    assert parsed.entries == [Decimal("0.69"), Decimal("0.67")]
    assert parsed.entry_mode == EntryMode.RANGE
    assert parsed.stop_loss == Decimal("0.6642")
    assert parsed.take_profits == [
        Decimal("0.7020"),
        Decimal("0.7075"),
        Decimal("0.7122"),
        Decimal("0.7158"),
        Decimal("0.7203"),
        Decimal("0.7255"),
    ]


def test_green_trading_brackets_and_inline_loss(parser):
    """Bracket range entries and bracket list take profits with inline loss emoji"""
    text = """Green Trading #VVIP 💚:  APE/USDT

 👉 Trade Type = SHORT 🔴

 👉 Leverage :- 20x

⚡ Entry = [ 0.1336 TO 0.1333 ]

❌ Stoploss 🔴Loss :- 0.1384

✅ Take profit = [ 0.1313, 0.1296, 0.1280, 0.1261, 0.1244, 0.1220 ]"""

    meta = create_metadata(-1001294641953, 76989)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "APEUSDT"
    assert parsed.side == PositionSide.SHORT
    assert parsed.entries == [Decimal("0.1336"), Decimal("0.1333")]
    assert parsed.stop_loss == Decimal("0.1384")
    assert len(parsed.take_profits) == 6
    assert parsed.take_profits[0] == Decimal("0.1313")


def test_slash_targets_and_k_suffix_sl(parser):
    """Slash targets and SL under 62k"""
    text = """$BTCUSDT LONG SETUP

Entry range: $63500 - $64200
Targets: $65000/$66500/$68000
SL under 62k"""

    meta = create_metadata(-1001519589508, 54621)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "BTCUSDT"
    assert parsed.side == PositionSide.LONG
    assert parsed.entries == [Decimal("63500"), Decimal("64200")]
    assert parsed.stop_loss == Decimal("62000")
    assert parsed.take_profits == [Decimal("65000"), Decimal("66500"), Decimal("68000")]


def test_comma_thousand_separators(parser):
    """Numbers with comma thousand separators (e.g. BTC, ETH)"""
    text = """🔱 BTC/USDT LONG 🔱

LEVERAGE : 50X

🟢 Entry: 63,100 : 62,700

🎯 TP1: 63,400
🎯 TP2: 63,800
🎯 TP3: 64,200

🛑 STOP LOSS : 61,500"""

    meta = create_metadata(-1001212188460, 44884)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "BTCUSDT"
    assert parsed.side == PositionSide.LONG
    assert parsed.entries == [Decimal("63100"), Decimal("62700")]
    assert parsed.stop_loss == Decimal("61500")
    assert parsed.take_profits == [Decimal("63400"), Decimal("63800"), Decimal("64200")]

