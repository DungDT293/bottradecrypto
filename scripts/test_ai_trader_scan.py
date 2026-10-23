"""Opt-in AI market scan; defaults to offline dry-run."""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.config import load_config
from exchange.binance_client import BinanceFuturesClient
from services.gemini_autonomous_trader import GeminiAutonomousTrader


async def test_ai_trader() -> None:
    cfg = load_config()
    client = BinanceFuturesClient(cfg)
    trader = GeminiAutonomousTrader(config=cfg, binance_client=client)
    try:
        print("=== TESTING GEMINI AUTONOMOUS TRADER SCAN ===")
        setups = await trader.scan_market(["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"])
        print(f"Scan completed! Found {len(setups)} valid trade setups")
        for setup in setups:
            print(setup)
    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Opt-in Binance/Gemini AI scan")
    parser.add_argument("--confirm-network", action="store_true", help="Allow market-data and Gemini network calls")
    args = parser.parse_args()
    if not args.confirm_network:
        print("DRY-RUN: no Binance or Gemini requests. Re-run with --confirm-network to opt in.")
    else:
        asyncio.run(test_ai_trader())
