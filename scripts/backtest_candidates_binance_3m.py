import asyncio
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, r"e:\TOOL DUNG CODE\bottradecrypto")
sys.stdout.reconfigure(encoding="utf-8")

from telethon import TelegramClient
from parser.signal_parser import SignalParser
from core.models import SourceMetadata

KLINE_URL = "https://fapi.binance.com/fapi/v1/klines"
MARK_URL = "https://fapi.binance.com/fapi/v1/markPriceKlines"

session_copy = os.path.expandvars(r"%APPDATA%\telegram_binance_signal_executor\data\temp_backtest_3m.session")
session_orig = os.path.expandvars(r"%APPDATA%\telegram_binance_signal_executor\data\telegram_user.session")
import shutil
shutil.copy2(session_orig, session_copy)

api_id = 28680296
api_hash = "927e2da6e7d0ec3d97a79d11cc794e46"

client = TelegramClient(session_copy, api_id, api_hash)

def binance_get(url, params):
    req = Request(url + "?" + urlencode(params), headers={"User-Agent": "audit-backtest/1.0"})
    try:
        with urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        return []

def fetch_klines(url, symbol, start_ms, end_ms):
    rows = []
    cursor = start_ms
    while cursor < end_ms:
        batch = binance_get(url, {"symbol": symbol, "interval": "1m", "startTime": cursor, "endTime": end_ms, "limit": 1500})
        if not batch:
            break
        rows.extend(batch)
        nxt = int(batch[-1][0]) + 60000
        if nxt <= cursor:
            break
        cursor = nxt
        if len(batch) < 1500:
            break
        time.sleep(0.02)
    return rows

def simulate_signal(sig):
    symbol = sig["symbol"]
    side = sig["side"]
    entry = Decimal(sig["entry"])
    sl = Decimal(sig["sl"])
    tps = [Decimal(x) for x in sig["tps"]]
    
    ts = datetime.fromisoformat(sig["timestamp"].replace("Z", "+00:00"))
    start_ms = int(ts.timestamp() * 1000)
    end_ms = start_ms + 72 * 3600 * 1000
    
    contract_k = fetch_klines(KLINE_URL, symbol, start_ms, end_ms)
    if not contract_k:
        return {"status": "UNKNOWN", "reason": "NO_BINANCE_DATA", "pnl_pct": Decimal("0")}
    
    mark_k = fetch_klines(MARK_URL, symbol, start_ms, end_ms)
    marks = {int(x[0]): (Decimal(str(x[2])), Decimal(str(x[3]))) for x in mark_k}
    
    entered = False
    for k in contract_k:
        t = int(k[0])
        hi = Decimal(str(k[2]))
        lo = Decimal(str(k[3]))
        mh, ml = marks.get(t, (hi, lo))
        
        if not entered:
            if lo <= entry <= hi:
                entered = True
            else:
                continue
        
        if side == "LONG":
            hit_sl = ml <= sl
            hit_tp = hi >= min(tps)
        else:
            hit_sl = mh >= sl
            hit_tp = lo <= max(tps)
            
        if hit_sl and hit_tp:
            # Ambiguous inside same minute, mark as unknown/loss conservative
            return {"status": "LOSS", "reason": "SAME_MINUTE_SL_TP", "pnl_pct": (sl - entry) / entry * 100 if side == "LONG" else (entry - sl) / entry * 100}
        if hit_tp:
            tp1 = min(tps) if side == "LONG" else max(tps)
            pnl = (tp1 - entry) / entry * 100 if side == "LONG" else (entry - tp1) / entry * 100
            return {"status": "WIN", "reason": "TP1_HIT", "pnl_pct": pnl}
        if hit_sl:
            pnl = (sl - entry) / entry * 100 if side == "LONG" else (entry - sl) / entry * 100
            return {"status": "LOSS", "reason": "SL_HIT", "pnl_pct": pnl}
            
    if not entered:
        return {"status": "MISSED_ENTRY", "reason": "ENTRY_NOT_REACHED", "pnl_pct": Decimal("0")}
    return {"status": "EXPIRED", "reason": "NO_TERMINAL_HIT_72H", "pnl_pct": Decimal("0")}

async def main():
    detected_p = "data/detected_signal_channels_3days.json"
    if not os.path.exists(detected_p):
        print(f"Error: {detected_p} does not exist yet!")
        return

    with open(detected_p, "r", encoding="utf-8") as f:
        candidates = json.load(f)

    if not candidates:
        print("No candidates detected.")
        return

    print(f"Loaded {len(candidates)} candidate channels. Starting 3-month signal extraction & Binance backtest...")
    await client.connect()
    
    parser = SignalParser()
    cutoff_90d = datetime.now(timezone.utc) - timedelta(days=90)
    
    overall_report = {}

    for cand in candidates:
        cid = cand["id"]
        title = cand["title"]
        print(f"\n{'='*60}\nFETCHING 3-MONTH SIGNALS FOR: {title} (ID: {cid})\n{'='*60}")
        
        try:
            entity = await client.get_entity(cid)
        except Exception as e:
            print(f"Cannot get entity for {title}: {e}")
            continue

        raw_signals = []
        msg_count = 0
        
        async for m in client.iter_messages(entity, limit=600):
            if not m.date or m.date < cutoff_90d:
                break
            msg_count += 1
            txt = m.text or ""
            if not txt or len(txt) < 15:
                continue
            
            meta = SourceMetadata(chat_id=cid, message_id=m.id, telegram_timestamp=m.date, received_at=datetime.now(timezone.utc))
            parsed = parser.parse(txt, meta)
            sym = parsed.symbol_candidate or parsed.symbol_raw
            if sym and parsed.side and parsed.entries and (parsed.take_profits or parsed.stop_loss):
                raw_signals.append({
                    "chat_id": cid,
                    "chat_title": title,
                    "message_id": m.id,
                    "timestamp": m.date.isoformat(),
                    "symbol": sym,
                    "side": parsed.side.value,
                    "entry": str(parsed.entries[0]),
                    "sl": str(parsed.stop_loss) if parsed.stop_loss else str(parsed.entries[0] * Decimal("0.95") if parsed.side.value == "LONG" else parsed.entries[0] * Decimal("1.05")),
                    "tps": [str(t) for t in parsed.take_profits] if parsed.take_profits else [str(parsed.entries[0] * Decimal("1.02") if parsed.side.value == "LONG" else parsed.entries[0] * Decimal("0.98"))]
                })

        print(f"Found {len(raw_signals)} valid signals out of {msg_count} messages in last 90 days.")
        
        # Now backtest against Binance
        wins = 0
        losses = 0
        missed = 0
        unknown = 0
        total_pnl = Decimal("0")
        
        for idx, sig in enumerate(raw_signals):
            res = simulate_signal(sig)
            st = res["status"]
            if st == "WIN":
                wins += 1
                total_pnl += res["pnl_pct"]
            elif st == "LOSS":
                losses += 1
                total_pnl += res["pnl_pct"]
            elif st == "MISSED_ENTRY":
                missed += 1
            else:
                unknown += 1
            if (idx + 1) % 15 == 0:
                print(f"  Processed {idx + 1}/{len(raw_signals)} signals: Wins={wins}, Losses={losses}, Missed={missed}")

        denom = wins + losses
        winrate = round(wins / denom * 100, 2) if denom > 0 else 0.0
        
        overall_report[str(cid)] = {
            "title": title,
            "total_signals_90d": len(raw_signals),
            "filled_signals": denom,
            "wins": wins,
            "losses": losses,
            "missed_entry": missed,
            "win_rate_pct": winrate,
            "total_unleveraged_pnl_pct": float(total_pnl),
            "recommendation": "KHUYÊN DÙNG (TOP TIER)" if denom >= 15 and winrate >= 75.0 else ("CÂN NHẮC (CẦN GIÁM SÁT)" if denom >= 10 and winrate >= 65.0 else "LOẠI BỎ (RỦI RO)")
        }
        print(f"--> RESULT FOR {title}: Total={len(raw_signals)}, Filled={denom}, WinRate={winrate}%, PnL={total_pnl:.2f}%")

    out_file = "data/candidate_channels_binance_3m_backtest.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(overall_report, f, ensure_ascii=False, indent=2)
    print(f"\nALL CANDIDATES BACKTESTED! Results written to {out_file}")

if __name__ == "__main__":
    client.loop.run_until_complete(main())
    client.disconnect()

