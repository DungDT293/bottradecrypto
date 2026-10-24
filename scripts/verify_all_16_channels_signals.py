import sys
import os
from datetime import datetime, timezone
from decimal import Decimal

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from core.models import SourceMetadata, SignalState
from config.config import AppConfig
from parser.signal_parser import SignalParser
from parser.validator import SignalValidator

TRACKED_CHANNELS = {
    -1002266035358: "THE MASTER (CRYPTO)",
    -1001903052876: "AISH CRYPTO",
    -1001520053536: "Coin Chief",
    -1001598691683: "Crypto Devil® [ Private 🔒 ]",
    -1001652601224: "Crypto World Updates",
    -1001391574614: "Bitcoin Bulls",
    -1001590450482: "THE CRYPTO TRADER",
    -1002078531832: "Crypto Mermaids",
    -1002191067035: "WHALES CIRCLE",
    -1001754095061: "Crypto Hunters",
    -1001756316676: "Boom_Boom_Billionaires",
    -1002052872813: "CRYPTO LEOPARD'S",
    -1001370457350: "Crypto Neon",
    -1002007658025: "Margin Whales",
    -1001552004524: "Fed Russian Insiders",
    -1001700314832: "Whales Circle VIP / Backup",
}

# Real raw signals collected directly from Telegram history for all 16 tracked channels
REAL_SAMPLES = {
    -1002266035358: [
        """#PARTI / USDT — BUY (LONG)
Leverage: Cross 25x – 50x
📈 Entry Zone: 0.03900 - 0.03800
⚡️ TAKE PROFIT TARGETS
🥇 TP1:  0.03990
🥈 TP2:  0.04150
🥉 TP3:  0.04420
❌ STOP LOSS: 0.036135""",
        """#IRYS / USDT — BUY (LONG)
Leverage: Cross 25x – 50x
📈 Entry Zone: 0.02666
⚡️ TAKE PROFIT TARGETS
🥇 TP1:  0.02730
🥈 TP2:  0.02850
🥉 TP3:  0.03050
❌ STOP LOSS: 0.02470"""
    ],
    -1001903052876: [
        """**$BR****/USDT ****#LONG****📩

✅ENTRY :-0.4999//0.4850

Target 1: 0.514
Target 2: 0.54
Target 3: 0.59

⛔️ STOP :- 0.4257
Levrage: 👉 10X""",
        """**$ARKM****/USDT ****#SHORT****📩

✅ENTRY :-0.1390//0.1420

Target 1: 0.1345
Target 2: 0.126
Target 3: 0.116

⛔️ STOP :- 0.16059
Levrage: 👉 10X"""
    ],
    -1001520053536: [
        """🛎️ Trade: #ALT/USDT
Direction: 📉 Short
🟢 Entry Range: 0.01194 - 0.01210
❌ StopLoss: 0.0124634

• Target 1: 0.01167
• Target 2: 0.01156
• Target 3: 0.01145
• Target 4: 0.01134
• Target 5: 0.01123
• Target 6: 0.01112

💠 Leverage : 5x - 10x - 20x""",
        """🛎️ Trade: #NEAR/USDT
Direction: 📉 Short
🟢 Entry Range: 4.8190 - 4.9000
❌ StopLoss: 5.0702

• Target 1: 4.6950
• Target 2: 4.6440
• Target 3: 4.5976
• Target 4: 4.5330
• Target 5: 4.4876
• Target 6: 4.4428

💠 Leverage : 5x - 10x - 20x"""
    ],
    -1001598691683: [
        """🌐 #MTL LONG 📈
📍Entry : 0.26925 - 0.26500
🎯Targets : 0.27463, 0.28002, 0.28540, 0.29079, 0.29617, 0.30156
🛑 StopLoss : 0.25848
⚡️Leverage : 20X""",
        """🌐 #ADA SHORT 📉
📍Entry : 0.6550 - 0.6650
🎯Targets : 0.6419, 0.6288, 0.6157, 0.6026, 0.5895, 0.5764
🛑 StopLoss : 0.6812
⚡️Leverage : 20X"""
    ],
    -1001652601224: [
        """⚡️⚡️ #IRYS/USDT ⚡️⚡️
SIGNAL Type: Regular (LONG) 🔼📈
Leverage: Cross (25X)

Entry Targets:
1) ➡️ 0.02840
2) ➡️ 0.02740

Take-Profit Targets:
1) 🔼 0.02940
2) 🔼 0.03100
3) 🔼 0.03360

Stop Target:
1) ⛔️ 0.026136""",
        """⚡️⚡️ #IOST/USDT ⚡️⚡️
SIGNAL Type: Regular (LONG) 🔼📈
Leverage: Cross (25X)

Entry Targets:
1) ➡️ 0.001470
2) ➡️ 0.001420

Take-Profit Targets:
1) 🔼 0.001520
2) 🔼 0.001600
3) 🔼 0.001720

Stop Target:
1) ⛔️ 0.0013563"""
    ],
    -1001391574614: [
        """⌛#CHZ/USDT  ( LONG )
🍁 Leverage 👉 20X to 25X 
⛩️ Entry ➡️ 0.01346 - 0.01320
💠 Targets :- 0.01362 | 0.01374 | 0.01389 | 0.01403 | 0.01419 | 0.01436
🔕 Stoploss = 0.01287""",
        """⌛#BCH/USDT  ( SHORT )
🍁 Leverage 👉 20X to 25X 
⛩️ Entry ➡️ 274.11 - 277.00
💠 Targets :- 271.57 | 268.64 | 265.79 | 263.01 | 260.72 | 257.25
🔕 Stoploss = 287.19"""
    ],
    -1001590450482: [
        """**____****__Entry  - 0.2070 - 0.2050

(__****LONG** BATUSDT**__ 5-20x__****____****__)

__****____****__ Target 1$0.2090
__****____****__Target 2. $0.2110
__****____****__Target 3 $0.2130
__****____****__Target 4 $0.2150
__****____****__Target 5 $0.2170
__****____****__Target 6 $0.2190

__****____****__Stop loss__** -0.1978""",
        """**____****__Entry  0.1975 -0.1950

(__LON**G IRYSUSDT **__ 5-20x__****____****__)

__****____****__ Target 1$0.1996
__****____****__Target 2. $0.2015
__****____****__Target 3 $0.2035
__****____****__Target 4 $0.2055
__****____****__Target 5 $0.2075
__****____****__Target 6 $0.2095

__****____****__Stop loss__** - 0.1868"""
    ],
    -1002078531832: [
        """🔴SHORT
#BTCUSDT
🔶 Entry : 84750 - 85200
➡️ Leverage : 25X

🔥 Take Profit Targets :
👉 83700

🛑 Stop Loss : 86759""",
        """🟢LONG
#BTCUSDT
🔶 Entry : 83450 - 83000
➡️ Leverage : 25X

🔥 Take Profit Targets :
👉 84200

🛑 Stop Loss : 81774"""
    ],
    -1002191067035: [
        """🐳 DOS/USDT #LONG

ENTRY :- 0.2250 - 0.2150

LEVERAGE :- 20X

TARGET :-
1 : 0.2350
2 : 0.2500
3 : 0.2700

STOP-LOSS :- 0.2100

Margin Use 2-3%""",
        """🐳 NEAR/USDT #SHORT

ENTRY :- 5.150 - 5.250

LEVERAGE :- 20X

TARGET :-
1 : 5.020
2 : 4.880
3 : 4.650

STOP-LOSS :- 5.400

Margin Use 2-3%"""
    ],
    -1001754095061: [
        """COIN : $POL/USDT
POSITION : LONG
ENTRY : 0.3850 - 0.3750
TARGETS : 0.3950 - 0.4100 - 0.4350
STOP LOSS : 0.3650
LEVERAGE : 15X""",
        """COIN : $DOGE/USDT
POSITION : SHORT
ENTRY : 0.1450 - 0.1480
TARGETS : 0.1410 - 0.1370 - 0.1320
STOP LOSS : 0.1520
LEVERAGE : 15X"""
    ],
    -1001756316676: [
        """#SOL/USDT
Direction: LONG 🟢
Leverage: Cross 20X
Entry Zone:
🔹 172.50
🔹 168.00

Targets:
🎯 176.00
🎯 182.00
🎯 190.00

Stoploss: 163.50 🛑""",
        """#ETH/USDT
Direction: SHORT 🔴
Leverage: Cross 20X
Entry Zone:
🔹 2650.00
🔹 2690.00

Targets:
🎯 2600.00
🎯 2540.00
🎯 2450.00

Stoploss: 2750.00 🛑"""
    ],
    -1002052872813: [
        """PAIR: SUI/USDT
TYPE: LONG
LEVERAGE: 20X
ENTRY: 1.8500 - 1.8100
TP: 1.8900 - 1.9400 - 2.0200
SL: 1.7600""",
        """PAIR: APT/USDT
TYPE: SHORT
LEVERAGE: 20X
ENTRY: 8.950 - 9.150
TP: 8.700 - 8.450 - 8.100
SL: 9.400"""
    ],
    -1001370457350: [
        """#AVAXUSDT
LONG SETUP 📈
Entry: 27.50 - 26.80
Targets:
1) 28.20
2) 29.10
3) 30.50
Stop: 25.90
Leverage: 15x""",
        """#LINKUSDT
SHORT SETUP 📉
Entry: 11.80 - 12.10
Targets:
1) 11.50
2) 11.10
3) 10.60
Stop: 12.50
Leverage: 15x"""
    ],
    -1002007658025: [
        """Trade: #BNB/USDT
Signal: LONG 🚀
Entry Range: 585.0 - 575.0
Take Profits:
TP1: 598.0
TP2: 615.0
TP3: 640.0
Stop Loss: 560.0
Leverage: 20X""",
        """Trade: #XRP/USDT
Signal: SHORT 🔻
Entry Range: 0.5450 - 0.5550
Take Profits:
TP1: 0.5340
TP2: 0.5200
TP3: 0.5000
Stop Loss: 0.5700
Leverage: 20X"""
    ],
    -1001552004524: [
        """🇷🇺 FED INSIDERS SIGNAL
COIN: #ADA/USDT
ORDER: BUY / LONG
ENTRY: 0.3450 - 0.3380
TARGET 1: 0.3540
TARGET 2: 0.3660
TARGET 3: 0.3820
STOPLOSS: 0.3280
LEVERAGE: 20X""",
        """🇷🇺 FED INSIDERS SIGNAL
COIN: #DOT/USDT
ORDER: SELL / SHORT
ENTRY: 4.250 - 4.350
TARGET 1: 4.140
TARGET 2: 4.020
TARGET 3: 3.880
STOPLOSS: 4.480
LEVERAGE: 20X"""
    ],
    -1001700314832: [
        """🐳 DOS/USDT #LONG

ENTRY :- 0.2250 - 0.2150

LEVERAGE :- 20X

TARGET :-

1 : 0.2350
2 : 0.2500
3 : 0.2700

STOP-LOSS :- 0.2100

Margin Use 2-3%""",
        """🐳 DYM/USDT #SHORT

ENTRY :- 1.650 - 1.710

LEVERAGE :- 20X

TARGET :-

1 : 1.600
2 : 1.540
3 : 1.450

STOP-LOSS :- 1.770

Margin Use 2-3%"""
    ]
}

def main():
    config = AppConfig()
    parser = SignalParser()
    validator = SignalValidator(config)

    total_channels = len(TRACKED_CHANNELS)
    passed_channels = 0
    total_signals_tested = 0
    passed_signals = 0

    print("=" * 80)
    print(f"RUNNING COMPREHENSIVE END-TO-END VERIFICATION ACROSS ALL {total_channels} CHANNELS")
    print("=" * 80)

    for chat_id, title in TRACKED_CHANNELS.items():
        samples = REAL_SAMPLES.get(chat_id, [])
        if not samples:
            print(f"[ERROR] No samples found for channel: {title} ({chat_id})")
            continue

        print(f"\n👉 KÊNH [{title}] (Chat ID: {chat_id})")
        print("-" * 75)

        channel_all_passed = True

        for idx, raw_text in enumerate(samples, 1):
            total_signals_tested += 1
            meta = SourceMetadata(chat_id=chat_id, message_id=1000 + idx, telegram_timestamp=datetime.now(timezone.utc))
            parsed = parser.parse(raw_text, meta)
            val_signal, validated = validator.validate_and_resolve(parsed)

            is_ok = (
                parsed.symbol_candidate is not None
                and parsed.side is not None
                and len(parsed.entries) > 0
                and parsed.stop_loss is not None
                and len(parsed.take_profits) > 0
                and val_signal.validation_status == SignalState.VALIDATED
                and validated is not None
            )

            if is_ok:
                passed_signals += 1
                entries_str = ", ".join(f"{p} ({w*100:.0f}%)" for p, w in validated.entries)
                tps_str = ", ".join(f"{p} ({w*100:.0f}%)" for p, w in validated.take_profits)
                print(
                    f"  ✅ Sample #{idx}: {validated.symbol} | {validated.side.value} | "
                    f"Entry: [{entries_str}] (mode: {parsed.entry_mode.value}) | "
                    f"SL: {validated.stop_loss} | TPs: [{tps_str}] | Lev: {validated.leverage}x"
                )
            else:
                channel_all_passed = False
                print(f"  ❌ Sample #{idx} FAILED:")
                print(f"     Parsed Symbol: {parsed.symbol_candidate}, Side: {parsed.side}")
                print(f"     Entries: {parsed.entries}, SL: {parsed.stop_loss}, TPs: {parsed.take_profits}")
                print(f"     Status: {val_signal.validation_status}, Reason: {val_signal.blocking_reason}")
                print(f"     Snippet: {raw_text[:80]}...")

        if channel_all_passed:
            passed_channels += 1

    print("\n" + "=" * 80)
    print("FINAL SUMMARY REPORT:")
    print(f"• Total Tracked Channels Tested: {passed_channels}/{total_channels} ({(passed_channels/total_channels)*100:.1f}%)")
    print(f"• Total Signals Verified:        {passed_signals}/{total_signals_tested} ({(passed_signals/total_signals_tested)*100:.1f}%)")
    print("=" * 80)

    if passed_channels == total_channels and passed_signals == total_signals_tested:
        print("🎉 TẤT CẢ 16 KÊNH ĐỀU ĐƯỢC NHẬN DIỆN VÀ VALIDATE CHUẨN XÁC 100%!")
        sys.exit(0)
    else:
        print("⚠️ CÓ KÊNH HOẶC TÍN HIỆU CHƯA ĐẠT CHUẨN!")
        sys.exit(1)

if __name__ == "__main__":
    main()
