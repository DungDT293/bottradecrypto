import asyncio
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, List, Any, Optional, Tuple
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config.config import load_config
from core.models import SourceMetadata
from parser.signal_parser import SignalParser
from parser.validator import SignalValidator

cfg = load_config()
sig_parser = SignalParser()
validator = SignalValidator(cfg)

cutoff = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
conn = sqlite3.connect("data/trading_state.db")
c = conn.cursor()

CHANNELS = [
    {"name": "Crypto Hunters", "id": -1002191067035},
    {"name": "Crypto Neon", "id": -1001370457350},
    {"name": "Crypto spider 🕷️ scalper", "id": -1001895315984},
    {"name": "THE WOLF (CRYPTO)®", "id": -1002007658025},
    {"name": "CRYPTO LEOPARD'S", "id": -1002052872813},
    {"name": "THE CRYPTO TRADER", "id": -1001590450482},
    {"name": "THE MASTER (CRYPTO)", "id": -1002266035358},
    {"name": "Global Crypto Research", "id": -1001161683441},
    {"name": "Crypto World Updates", "id": -1001652601224},
]

# Cache klines in memory to minimize API calls
KLINE_CACHE: Dict[str, List[Any]] = {}

def get_binance_klines(symbol: str, start_ts_ms: int, end_ts_ms: int) -> List[Any]:
    cache_key = f"{symbol}_{start_ts_ms // 3600000}"
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&startTime={start_ts_ms}&endTime={end_ts_ms}&limit=100"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            return data
    except Exception:
        return []

def evaluate_signal_outcome(sig: Dict[str, Any]) -> str:
    """
    Returns: 'WIN_TP1', 'WIN_TP2', 'WIN_TP3', 'LOSS_SL', or 'EXPIRED'
    """
    symbol = sig["symbol"]
    side = sig["side"]
    entry = sig["entry"]
    sl = sig["sl"]
    tp1 = sig["tp1"]
    tp2 = sig.get("tp2")
    tp3 = sig.get("tp3")

    try:
        dt = datetime.fromisoformat(sig["date"]) if "T" in sig["date"] else datetime.utcnow()
        start_ts = int(dt.timestamp() * 1000)
        end_ts = start_ts + (72 * 3600 * 1000) # 72 hours max holding
    except Exception:
        return "UNKNOWN"

    klines = get_binance_klines(symbol, start_ts, end_ts)
    if not klines:
        return "NO_DATA"

    # Iterate through 1h candles
    hit_tp1 = False
    hit_tp2 = False
    hit_tp3 = False

    for k in klines:
        high = float(k[2])
        low = float(k[3])

        if side == "LONG":
            # Check TP hits
            if high >= tp1:
                hit_tp1 = True
            if tp2 and high >= tp2:
                hit_tp2 = True
            if tp3 and high >= tp3:
                hit_tp3 = True

            # If hit TP1, SL was moved to breakeven (entry)!
            current_sl = entry if hit_tp1 else sl
            if low <= current_sl:
                if hit_tp1:
                    # Locked profit at TP1, broke even on rest
                    return "WIN_TP3" if hit_tp3 else ("WIN_TP2" if hit_tp2 else "WIN_TP1")
                else:
                    return "LOSS_SL"

        elif side == "SHORT":
            if low <= tp1:
                hit_tp1 = True
            if tp2 and low <= tp2:
                hit_tp2 = True
            if tp3 and low <= tp3:
                hit_tp3 = True

            current_sl = entry if hit_tp1 else sl
            if high >= current_sl:
                if hit_tp1:
                    return "WIN_TP3" if hit_tp3 else ("WIN_TP2" if hit_tp2 else "WIN_TP1")
                else:
                    return "LOSS_SL"

    if hit_tp1:
        return "WIN_TP3" if hit_tp3 else ("WIN_TP2" if hit_tp2 else "WIN_TP1")
    return "EXPIRED"

def main():
    print("=" * 80)
    print("🚀 BẮT ĐẦU ĐÁNH GIÁ TỈ LỆ THẮNG (WIN RATE) CHO 9 NHÓM GHIM TRONG 6 THÁNG QUA")
    print("=" * 80)

    results = []

    for ch in CHANNELS:
        cid = ch["id"]
        cname = ch["name"]
        override = cfg.sources.get(cid)

        # 1. Parse all valid signals from DB
        c.execute("""
            SELECT message_id, raw_text, telegram_timestamp 
            FROM messages 
            WHERE chat_id = ? AND telegram_timestamp >= ?
            ORDER BY telegram_timestamp ASC
        """, (cid, cutoff))
        
        rows = c.fetchall()
        valid_signals = []
        sl_distances = []
        tp1_distances = []

        for mid, text, dt in rows:
            meta = SourceMetadata(chat_id=cid, message_id=mid, telegram_timestamp=datetime.fromisoformat(dt) if "T" in dt else datetime.utcnow())
            sig = sig_parser.parse(text, meta)
            if sig.symbol_candidate and (sig.entries or sig.stop_loss):
                res, val = validator.validate_and_resolve(sig, override)
                if val:
                    entry_p = float(val.entries[0][0])
                    sl_p = float(val.stop_loss)
                    tp1_p = float(val.take_profits[0][0])
                    tp2_p = float(val.take_profits[1][0]) if len(val.take_profits) > 1 else None
                    tp3_p = float(val.take_profits[2][0]) if len(val.take_profits) > 2 else None

                    sl_dist = abs(entry_p - sl_p) / entry_p * 100
                    tp1_dist = abs(tp1_p - entry_p) / entry_p * 100
                    sl_distances.append(sl_dist)
                    tp1_distances.append(tp1_dist)

                    valid_signals.append({
                        "id": mid,
                        "date": dt,
                        "symbol": val.symbol,
                        "side": val.side.value,
                        "entry": entry_p,
                        "sl": sl_p,
                        "tp1": tp1_p,
                        "tp2": tp2_p,
                        "tp3": tp3_p,
                    })

        total_sigs = len(valid_signals)
        avg_sl = round(sum(sl_distances) / len(sl_distances), 2) if sl_distances else 0
        avg_tp1 = round(sum(tp1_distances) / len(tp1_distances), 2) if tp1_distances else 0

        # Sample 40 representative signals to evaluate live against Binance klines
        # (sampling to respect Binance API rate limits and deliver instantaneous results)
        sample_size = min(40, total_sigs)
        step = max(1, total_sigs // sample_size)
        sampled_sigs = valid_signals[::step][:sample_size]

        wins = 0
        losses = 0
        tp1_only = 0
        tp2_plus = 0
        expired = 0
        no_data = 0

        print(f"\n⏳ Đang kiểm định giá sàn Binance cho {cname} (Mẫu kiểm định: {len(sampled_sigs)} kèo)...")
        for s in sampled_sigs:
            outcome = evaluate_signal_outcome(s)
            time.sleep(0.05) # Rate limit safety
            if outcome in ["WIN_TP1", "WIN_TP2", "WIN_TP3"]:
                wins += 1
                if outcome == "WIN_TP1":
                    tp1_only += 1
                else:
                    tp2_plus += 1
            elif outcome == "LOSS_SL":
                losses += 1
            elif outcome == "EXPIRED":
                expired += 1
            else:
                no_data += 1

        resolved_trades = wins + losses
        winrate = round(wins / resolved_trades * 100, 1) if resolved_trades > 0 else 0

        res_item = {
            "name": cname,
            "id": cid,
            "total_signals_6m": total_sigs,
            "avg_sl_pct": avg_sl,
            "avg_tp1_pct": avg_tp1,
            "sampled_count": len(sampled_sigs),
            "wins": wins,
            "losses": losses,
            "winrate": winrate,
            "tp1_only": tp1_only,
            "tp2_plus": tp2_plus,
            "expired": expired,
        }
        results.append(res_item)
        print(f"  👉 {cname}: Win Rate = {winrate}% (Thắng {wins} / Thua {losses} | Khớp sâu TP2-3: {tp2_plus}) | SL TB: {avg_sl}% | TP1 TB: {avg_tp1}%")

    with open("data/channel_winrates_6_months.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 110)
    print(f"{'KÊNH TELEGRAM':<26} | {'TỔNG KÈO (6T)':<14} | {'TỈ LỆ THẮNG (WIN RATE)':<24} | {'SL TRUNG BÌNH':<14} | {'TP1 TRUNG BÌNH':<15}")
    print("-" * 110)
    for r in results:
        wr_str = f"{r['winrate']}% ({r['wins']}W - {r['losses']}L)"
        print(f"{r['name'][:26]:<26} | {r['total_signals_6m']:<14} | {wr_str:<24} | {r['avg_sl_pct']:<14}% | {r['avg_tp1_pct']:<15}%")
    print("=" * 110)

if __name__ == "__main__":
    main()

