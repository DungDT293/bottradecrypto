import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from services.gemini_autonomous_trader import GeminiAutonomousTrader
from config.config import load_config

def test_committee_rules():
    cfg = load_config()
    trader = GeminiAutonomousTrader(config=cfg, binance_client=None)

    # Mock market snapshot: Bullish pullback setup
    snapshot = {
        "symbol": "SOLUSDT",
        "current_price": 178.5,
        "ema20": 179.2,
        "ema50": 175.0,
        "rsi_14": 44.5,
        "atr_14": 2.8,
        "trend": "BULLISH",
        "change_24h_pct": 3.4,
        "recent_candles": [],
    }

    setup = trader.analyze_with_quant_rules(snapshot)
    print("=== TEST MULTI-AGENT COMMITTEE QUANT FALLBACK ===")
    print("Symbol:", setup["symbol"])
    print("Direction:", setup["direction"])
    print("Confidence:", setup["confidence"])
    print("Bull Arguments:", setup.get("bull_arguments"))
    print("Bear Arguments:", setup.get("bear_arguments"))
    print("Risk Verdict:", setup.get("risk_verdict"))
    print("Rationale:", setup.get("rationale"))
    print("Entry:", setup["entry_price"], "| SL:", setup["stop_loss"], "| TP2:", setup["take_profit_2"])

    assert setup["has_setup"] is True
    assert setup["direction"] == "LONG"
    assert setup["risk_verdict"] == "APPROVED"
    assert "bull_arguments" in setup
    assert "bear_arguments" in setup
    print("\nPASSED! Committee rules generated correct structured debate.")

if __name__ == "__main__":
    test_committee_rules()
