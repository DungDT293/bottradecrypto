from decimal import Decimal
from datetime import datetime, timezone
import pytest

from core.enums import EntryMode, PositionSide, SignalState
from core.models import SourceMetadata
from parser.signal_parser import SignalParser
from parser.validator import SignalValidator
from config.config import load_config


@pytest.fixture
def parser():
    return SignalParser()


@pytest.fixture
def validator():
    return SignalValidator(load_config())


def make_meta(chat_id: int, msg_id: int = 1):
    return SourceMetadata(
        chat_id=chat_id,
        message_id=msg_id,
        telegram_timestamp=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )


# ==============================================================================
# CHANNEL 1: THE MASTER (CRYPTO) (-1002266035358)
# ==============================================================================
def test_channel_the_master_crypto_single_entry(parser, validator):
    text = """#IRYS / USDT — BUY (LONG) 
Leverage: Cross 25x – 50x 📈
Entry Zone: 0.02666


⚡️ TAKE PROFIT TARGETS 


🥇 TP1:  0.02730
🥈 TP2:  0.02810
🥉 TP3:  0.03030


❌ STOP LOSS: 0.02500


⚠️ RISK MANAGEMENT IS KEY
👉 Use ONLY 3% – 5% of your total portfolio"""

    meta = make_meta(-1002266035358, 23197)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "IRYSUSDT"
    assert parsed.side == PositionSide.LONG
    assert parsed.entries == [Decimal("0.02666")]
    assert parsed.entry_mode == EntryMode.SINGLE
    assert parsed.take_profits == [Decimal("0.02730"), Decimal("0.02810"), Decimal("0.03030")]
    assert parsed.stop_loss == Decimal("0.02500")

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None
    assert validated.symbol == "IRYSUSDT"
    assert validated.side == PositionSide.LONG


def test_channel_the_master_crypto_range_entry(parser, validator):
    text = """#PARTI/ USDT — BUY (LONG) 
Leverage: Cross 25x – 50x 📈
Entry Zone: 0.03900-0.03800


⚡️ TAKE PROFIT TARGETS 


🥇 TP1:  0.03990
🥈 TP2:  0.04150
🥉 TP3:  0.04420


❌ STOP LOSS: 0.03650


⚠️ RISK MANAGEMENT IS KEY
👉 Use ONLY 3% – 5% of your total portfolio"""

    meta = make_meta(-1002266035358, 23146)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "PARTIUSDT"
    assert parsed.side == PositionSide.LONG
    assert parsed.entries == [Decimal("0.03900"), Decimal("0.03800")]
    assert parsed.entry_mode == EntryMode.RANGE
    assert parsed.take_profits == [Decimal("0.03990"), Decimal("0.04150"), Decimal("0.04420")]
    assert parsed.stop_loss == Decimal("0.03650")

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None


def test_channel_the_master_crypto_short(parser, validator):
    text = """#JCT / USDT — BUY (SHORT) 
Leverage: Cross 25x – 50x 📈
Entry Zone: 0.004900


⚡️ TAKE PROFIT TARGETS 


🥇 TP1:  0.004780
🥈 TP2:  0.004600
🥉 TP3:  0.004250


❌ STOP LOSS: 0.005180


⚠️ RISK MANAGEMENT IS KEY
👉 Use ONLY 3% – 5% of your total portfolio"""

    meta = make_meta(-1002266035358, 23138)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "JCTUSDT"
    assert parsed.side == PositionSide.SHORT
    assert parsed.entries == [Decimal("0.004900")]
    assert parsed.take_profits == [Decimal("0.004780"), Decimal("0.004600"), Decimal("0.004250")]
    assert parsed.stop_loss == Decimal("0.005180")

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None
    assert validated.side == PositionSide.SHORT


# ==============================================================================
# CHANNEL 2: AISH CRYPTO (-1001903052876)
# ==============================================================================
def test_channel_aish_crypto_long(parser, validator):
    text = """**$BR****/USDT ****#LONG****📩

✅ENTRY :-0.4999//0.482

Target 1: 0.514
Target 2: 0.54
Target 3: 0.59

⛔️ STOP :- 0.43
      Levrage: 👉 10X

⚠️𝐀𝐥𝐥𝐨𝐜𝐚𝐭𝐞 𝐎𝐧𝐥𝐲 𝟏-𝟑% 𝐎𝐟 𝐎𝐮𝐫 𝐃𝐞𝐩𝐨𝐬𝐢𝐭 𝐅𝐨𝐫 𝐄𝐚𝐜𝐡 𝐓𝐫𝐚𝐝𝐞"""

    meta = make_meta(-1001903052876, 12994)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "BRUSDT"
    assert parsed.side == PositionSide.LONG
    assert Decimal("0.4999") in parsed.entries
    assert parsed.take_profits == [Decimal("0.514"), Decimal("0.54"), Decimal("0.59")]
    assert parsed.stop_loss == Decimal("0.43")
    assert parsed.leverage_requested == 10

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None
    assert validated.leverage > 0


def test_channel_aish_crypto_short(parser, validator):
    text = """**$ARKM****/USDT ****#SHORT****📩

✅ENTRY :-0.139//0.144

Target 1: 0.1345
Target 2: 0.126
Target 3: 0.116

⛔️ STOP :- 0.159
      Levrage: 👉 10X"""

    meta = make_meta(-1001903052876, 12988)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "ARKMUSDT"
    assert parsed.side == PositionSide.SHORT
    assert parsed.take_profits == [Decimal("0.1345"), Decimal("0.126"), Decimal("0.116")]
    assert parsed.stop_loss == Decimal("0.159")

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None


# ==============================================================================
# CHANNEL 3: Coin Chief (-1001520053536)
# ==============================================================================
def test_channel_coin_chief_short(parser, validator):
    text = """🛎️ Trade: #ALT/USDT 
Direction: 📉 Short 

🟢 Entry Range: 0.01178 - 0.01210 

❌ StopLoss: 0.01234 

• Target 1: 0.01167
• Target 2: 0.01156
• Target 3: 0.01145
• Target 4: 0.01134
• Target 5: 0.01123
• Target 6: 0.01112

💠 Leverage : 5x - 10x - 20x"""

    meta = make_meta(-1001520053536, 24253)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "ALTUSDT"
    assert parsed.side == PositionSide.SHORT
    assert parsed.entries == [Decimal("0.01178"), Decimal("0.01210")]
    assert parsed.stop_loss == Decimal("0.01234")
    assert len(parsed.take_profits) == 6
    assert parsed.take_profits[0] == Decimal("0.01167")

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None


def test_channel_coin_chief_long(parser, validator):
    text = """🛎️ Trade: #ARKM/USDT 
Direction: 📈 LONG 

🟢 Entry Range: 0.1181 - 0.1143 

❌ StopLoss: 0.1127 

• Target 1: 0.1192
• Target 2: 0.1203
• Target 3: 0.1215
• Target 4: 0.1227
• Target 5: 0.1239
• Target 6: 0.1253

💠 Leverage : 5x - 10x - 20x"""

    meta = make_meta(-1001520053536, 24238)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "ARKMUSDT"
    assert parsed.side == PositionSide.LONG
    assert parsed.entries == [Decimal("0.1181"), Decimal("0.1143")]
    assert parsed.stop_loss == Decimal("0.1127")

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None


# ==============================================================================
# CHANNEL 4: Crypto Devil® [ Private 🔒 ] (-1001598691683)
# ==============================================================================
def test_channel_crypto_devil_usdt_long(parser, validator):
    text = """🌐 #MTL LONG 📈

📍Entry : 0.2675 - 0.2710

🎯Targets : 0.2740, 0.2780, 0.2820, 0.2870, 0.2920, 0.2970

🛑 StopLoss : 0.2520

⚡️Leverage : 20X"""

    meta = make_meta(-1001598691683, 60221)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "MTLUSDT"
    assert parsed.side == PositionSide.LONG
    assert parsed.entries == [Decimal("0.2675"), Decimal("0.2710")]
    assert parsed.stop_loss == Decimal("0.2520")
    assert len(parsed.take_profits) == 6
    assert parsed.leverage_requested == 20

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None
    assert validated.leverage > 0


def test_channel_crypto_devil_usd_quote_rejection(parser, validator):
    # System boundary: Quote asset 'USD' is rejected because Binance requires USDT perpetual
    text = """BTC/USD SELL
Entry : $  83666
Target1: $  82900
Target2: $  81000
Target3: $ 78568
SL : $ 85252"""

    meta = make_meta(-1001598691683, 60232)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate is None
    assert parsed.validation_status == SignalState.REJECTED


# ==============================================================================
# CHANNEL 5: Crypto World Updates (-1001652601224)
# ==============================================================================
def test_channel_crypto_world_updates_long(parser, validator):
    text = """⚡️⚡️ #IRYS/USDT️️️️⚡️️⚡️
SIGNAL Type: Regular (LONG) 🔼📈
Leverage: Cross (25X)

Amount: 1% ⚠️

Entry Targets:
1) ➡️  0.02840
2) ➡️  0.02740

Take-Profit Targets:
1) 🔼 0.02940
2) 🔼 0.03100
3) 🔼 0.03360

Stop Target:
1) ⛔️ 0.02640

Trailing Configuration:
Stop: Moving Target -
Trigger: Target (1)"""

    meta = make_meta(-1001652601224, 178427)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "IRYSUSDT"
    assert parsed.side == PositionSide.LONG
    assert parsed.entries == [Decimal("0.02840"), Decimal("0.02740")]
    assert parsed.take_profits == [Decimal("0.02940"), Decimal("0.03100"), Decimal("0.03360")]
    assert parsed.stop_loss == Decimal("0.02640")
    assert parsed.leverage_requested == 25

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None
    assert validated.leverage > 0


def test_channel_crypto_world_updates_short(parser, validator):
    text = """⚡️⚡️ #IRYS/USDT ️️️️⚡️️⚡️
SIGNAL Type: Regular (SHORT) 🔽
Leverage: Cross (25X)

Amount: 2% ⚠️

Entry Targets:
1) ➡️ 0.02170
2) ➡️ 0.02240

Take-Profit Targets:
1) 🔽 0.02105
2) ⬇️ 0.02000
3) 📉 0.01800

Stop Target:
1) ⛔️ 0.02310"""

    meta = make_meta(-1001652601224, 178344)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "IRYSUSDT"
    assert parsed.side == PositionSide.SHORT
    assert parsed.entries == [Decimal("0.02170"), Decimal("0.02240")]
    assert parsed.take_profits == [Decimal("0.02105"), Decimal("0.02000"), Decimal("0.01800")]
    assert parsed.stop_loss == Decimal("0.02310")

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None


# ==============================================================================
# CHANNEL 6: Bitcoin Bulls (-1001391574614)
# ==============================================================================
def test_channel_bitcoin_bulls_long(parser, validator):
    text = """⌛#CHZ/USDT  ( LONG )

🍁 Leverage 👉 20X to 25X 

⛩️ Entry ➡️ 0.01346 - 0.01349

💠 Targets :- 0.01362 | 0.01374 | 0.01389 | 0.01403 | 0.01419 | 0.01436

🔕 Stoploss = 0.01300"""

    meta = make_meta(-1001391574614, 40999)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "CHZUSDT"
    assert parsed.side == PositionSide.LONG
    assert parsed.entries == [Decimal("0.01346"), Decimal("0.01349")]
    assert len(parsed.take_profits) == 6
    assert parsed.take_profits[0] == Decimal("0.01362")
    assert parsed.stop_loss == Decimal("0.01300")

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None


def test_channel_bitcoin_bulls_short(parser, validator):
    text = """⌛#BCH/USDT  ( SHORT )

🍁 Leverage 👉 20X to 25X 

⛩️ Entry ➡️ 274.11 - 274.79

💠 Targets :- 271.57 | 268.64 | 265.79 | 263.01 | 260.72 | 257.25

🔕 Stoploss = 284.35"""

    meta = make_meta(-1001391574614, 40973)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "BCHUSDT"
    assert parsed.side == PositionSide.SHORT
    assert parsed.entries == [Decimal("274.11"), Decimal("274.79")]
    assert parsed.stop_loss == Decimal("284.35")

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None


# ==============================================================================
# CHANNEL 7: THE CRYPTO TRADER (-1001590450482)
# ==============================================================================
def test_channel_the_crypto_trader_broken_bold_formatting(parser, validator):
    # Tests intra-word markdown tokens like LON**G
    text = """**__✅__****__Entry  0.1975 -0.1950

(__LON**G IRYSUSDT **__ 5-20x__****__🆘__****__)

__****__🏹__****__ Target 1 $0.1996
__****__🏹__****__Target 2. $0.2015
__****__🏹__****__Target 3  $0.2035
__****__🏹__****__Target 4  $0.2055
__****__🏹__****__Target 5  $0.2075
__****__🏹__****__Target 6  $0.2095

__****__🚫__****__Stop loss__** - 0.1868"""

    meta = make_meta(-1001590450482, 41596)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "IRYSUSDT"
    assert parsed.side == PositionSide.LONG
    assert parsed.entries == [Decimal("0.1975"), Decimal("0.1950")]
    assert parsed.take_profits[0] == Decimal("0.1996")
    assert parsed.stop_loss == Decimal("0.1868")

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None


def test_channel_the_crypto_trader_price_space_typo(parser, validator):
    # Tests typo '$0 7272' converted to 0.7272
    text = """**__✅__****__Entry  - 0.72000 -0.7100

(__**🆘**LONG** BRUSDT**__ 5-20x__****__🆘__****__)

__****__🏹__****__ Target 1 $0 7272
__****__🏹__****__Target 2. $0.7340
__****__🏹__****__Target 3  $0.7420
__****__🏹__****__Target 4  $0.7562
__****__🏹__****__Target 5  $0.7655
__****__🏹__****__Target 6  $0.7765

__****__🚫__****__Stop loss__** -0.6800"""

    meta = make_meta(-1001590450482, 41578)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "BRUSDT"
    assert parsed.side == PositionSide.LONG
    assert parsed.entries == [Decimal("0.72000"), Decimal("0.7100")]
    assert parsed.take_profits[0] == Decimal("0.7272")
    assert parsed.stop_loss == Decimal("0.6800")

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None


# ==============================================================================
# CHANNEL 8: Crypto Mermaids (-1002078531832)
# ==============================================================================
def test_channel_crypto_mermaids_short(parser, validator):
    text = """🔴SHORT

#BTCUSDT

🔶 Entry : 84700 - 84800

➡️ Leverage : 25X

🔥 Take Profit Targets :

👉 83700

🛑 Stop Loss : 85900

🦋 VIP - @Chief099"""

    meta = make_meta(-1002078531832, 48194)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "BTCUSDT"
    assert parsed.side == PositionSide.SHORT
    assert parsed.entries == [Decimal("84700"), Decimal("84800")]
    assert parsed.take_profits == [Decimal("83700")]
    assert parsed.stop_loss == Decimal("85900")
    assert parsed.leverage_requested == 25

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None
    assert validated.leverage > 0


def test_channel_crypto_mermaids_long(parser, validator):
    text = """🟢LONG

#BTCUSDT

🔶 Entry : 83400 - 83500

➡️ Leverage : 25X

🔥 Take Profit Targets :

👉 84200

🛑 Stop Loss : 81700"""

    meta = make_meta(-1002078531832, 47958)
    parsed = parser.parse(text, meta)

    assert parsed.symbol_candidate == "BTCUSDT"
    assert parsed.side == PositionSide.LONG
    assert parsed.entries == [Decimal("83400"), Decimal("83500")]
    assert parsed.take_profits == [Decimal("84200")]
    assert parsed.stop_loss == Decimal("81700")

    _, validated = validator.validate_and_resolve(parsed)
    assert validated is not None
