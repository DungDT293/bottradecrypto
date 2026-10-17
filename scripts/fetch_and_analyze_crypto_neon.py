import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Any
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient

from config.config import load_config
from core.enums import UpdateType
from core.models import SourceMetadata
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from parser.validator import SignalValidator

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CHAT_ID = -1001370457350
OUTPUT_RAW = "data/crypto_neon_3_months_raw.json"
OUTPUT_ANALYSIS = "data/crypto_neon_3_months_analysis.json"

async def fetch_messages():
    print(f"Connecting to Telegram for channel {CHAT_ID}...")
    client = TelegramClient("data/telegram_user", 28680296, "927e2da6e7d0ec3d97a79d11cc794e46")
    await client.connect()
    if not await client.is_user_authorized():
        print("Telegram client not authorized!")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    print(f"Fetching messages since {cutoff.isoformat()}...")

    messages_data = []
    async for msg in client.iter_messages(CHAT_ID, offset_date=cutoff, reverse=True):
        if not msg.text:
            continue
        reply_to_id = msg.reply_to.reply_to_msg_id if msg.reply_to else None
        messages_data.append({
            "id": msg.id,
            "date": msg.date.isoformat(),
            "text": msg.text,
            "reply_to_id": reply_to_id,
            "views": msg.views,
            "forwards": msg.forwards,
        })

    await client.disconnect()
    print(f"Fetched {len(messages_data)} text messages.")

    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_RAW, "w", encoding="utf-8") as f:
        json.dump(messages_data, f, ensure_ascii=False, indent=2)

    return messages_data

def get_binance_futures_symbols():
    try:
        url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {s["symbol"] for s in data["symbols"]}
    except Exception as e:
        print(f"Warning: could not fetch Binance symbols ({e}), using fallback set")
        return set()

def analyze_dataset(messages_data: List[Dict[str, Any]], binance_symbols: set):
    config = load_config()
    sig_parser = SignalParser()
    upd_parser = ChannelUpdateParser()
    validator = SignalValidator(config)

    signals: Dict[int, Dict[str, Any]] = {}
    updates: List[Dict[str, Any]] = []
    promos: List[Dict[str, Any]] = []
    other: List[Dict[str, Any]] = []

    print("\nParsing messages...")
    for m in messages_data:
        mid = m["id"]
        text = m["text"]
        dt = m["date"]
        reply_to_id = m.get("reply_to_id")

        # 1. Check if promo / referral / marketing
        if re.search(r"(?:MEXC|account on the MEXC|UID code|CLICK HERE TO WIN|Membership link|VIP|join us|contact @|premium)", text, re.IGNORECASE) and not re.search(r"(?:Entry|Target1|STOP)", text, re.IGNORECASE):
            promos.append({"id": mid, "date": dt, "text": text})
            continue

        # 2. Try parsing as signal
        meta = SourceMetadata(
            chat_id=CHAT_ID,
            message_id=mid,
            telegram_timestamp=datetime.fromisoformat(dt)
        )
        parsed_sig = sig_parser.parse(text, meta)
        
        # Consider a signal if symbol_candidate and (entries or stop_loss) exist
        if parsed_sig.symbol_candidate and (parsed_sig.entries or parsed_sig.stop_loss):
            resolved_sig, validated_sig = validator.validate_and_resolve(parsed_sig)

            # Calculate SL distance %
            entry_val = parsed_sig.entries[0] if parsed_sig.entries else None
            sl_val = parsed_sig.stop_loss
            sl_pct = None
            if entry_val and sl_val and entry_val > 0:
                sl_pct = float(abs(entry_val - sl_val) / entry_val * 100)

            tp_pcts = []
            if entry_val and parsed_sig.take_profits:
                for tp in parsed_sig.take_profits:
                    tp_pcts.append(float(abs(tp - entry_val) / entry_val * 100))

            binance_symbol = parsed_sig.symbol_candidate
            is_on_binance = binance_symbol in binance_symbols if binance_symbols else True

            signals[mid] = {
                "id": mid,
                "date": dt,
                "symbol": parsed_sig.symbol_candidate,
                "binance_symbol": binance_symbol,
                "is_on_binance": is_on_binance,
                "side": parsed_sig.side.value if parsed_sig.side else "UNKNOWN",
                "entries": [float(e) for e in parsed_sig.entries],
                "targets": [float(t) for t in parsed_sig.take_profits],
                "stop_loss": float(sl_val) if sl_val else None,
                "sl_distance_pct": sl_pct,
                "tp_distances_pct": tp_pcts,
                "leverage_requested": parsed_sig.leverage_requested,
                "is_valid": validated_sig is not None,
                "blocking_reason": parsed_sig.blocking_reason,
                "validation_warnings": parsed_sig.warnings,
                "text": text,
                "updates_received": [],
                "max_target_hit": 0,
                "stop_hit": False,
                "closed": False,
            }
            continue

        # 3. Regex check for Target Done updates like "#CFX Target 5 Done! ✅" or "#BEL | SHORT SETUP Target 2 Done! ✅"
        done_m = re.search(r"#?([A-Za-z0-9]+).*?Target\s*(\d+)\s*(?:Done|Hit|Reached)", text, re.IGNORECASE)
        if done_m:
            sym = done_m.group(1).upper()
            t_idx = int(done_m.group(2))
            updates.append({
                "id": mid,
                "date": dt,
                "reply_to_id": reply_to_id,
                "update_type": "TARGET_REACHED",
                "symbol": sym,
                "target_index": t_idx,
                "price": None,
                "text": text,
            })
            continue

        # Fallback for stop hit
        stop_m = re.search(r"#?([A-Za-z0-9]+).*?(?:Stop\s*Loss\s*Hit|SL\s*Hit|Hit\s*Stop)", text, re.IGNORECASE)
        if stop_m:
            sym = stop_m.group(1).upper()
            updates.append({
                "id": mid,
                "date": dt,
                "reply_to_id": reply_to_id,
                "update_type": "STOP_LOSS_HIT",
                "symbol": sym,
                "target_index": None,
                "price": None,
                "text": text,
            })
            continue

        # 4. Try parsing as general update via ChannelUpdateParser
        upd_type, new_price, detail = upd_parser.parse_update(text)
        if upd_type != UpdateType.UNKNOWN:
            sym_m = re.search(r"#([A-Za-z0-9]+)", text)
            sym = sym_m.group(1).upper() if sym_m else None
            updates.append({
                "id": mid,
                "date": dt,
                "reply_to_id": reply_to_id,
                "update_type": upd_type.value,
                "symbol": sym,
                "target_index": None,
                "price": float(new_price) if new_price else None,
                "text": text,
            })
            continue

        other.append({"id": mid, "date": dt, "text": text})

    # Link updates to signals
    for u in updates:
        linked_sig = None
        # 1. By reply_to_id
        if u.get("reply_to_id") and u["reply_to_id"] in signals:
            linked_sig = signals[u["reply_to_id"]]
        # 2. By symbol match (most recent signal of that symbol before update)
        elif u.get("symbol"):
            u_sym = u["symbol"].upper()
            matching = [
                s for s in signals.values()
                if (s["symbol"] == u_sym or s["symbol"] == f"{u_sym}USDT" or s["symbol"].replace("USDT", "") == u_sym)
                and s["date"] <= u["date"]
            ]
            if matching:
                linked_sig = matching[-1]

        if linked_sig:
            linked_sig["updates_received"].append(u)
            if u["update_type"] == "TARGET_REACHED" and u.get("target_index"):
                if u["target_index"] > linked_sig["max_target_hit"]:
                    linked_sig["max_target_hit"] = u["target_index"]
            elif u["update_type"] == "STOP_LOSS_HIT":
                linked_sig["stop_hit"] = True
            elif u["update_type"] == "CLOSE_POSITION":
                linked_sig["closed"] = True

    # Compile Summary Statistics
    total_signals = len(signals)
    valid_signals = sum(1 for s in signals.values() if s["is_valid"])
    invalid_signals = total_signals - valid_signals

    symbols_count: Dict[str, int] = {}
    sides_count: Dict[str, int] = {"LONG": 0, "SHORT": 0, "UNKNOWN": 0}
    sl_distances = []
    tp1_distances = []
    leverages_stated = []
    on_binance_count = 0

    target_hits = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    stop_hit_count = 0

    for s in signals.values():
        sym = s["symbol"]
        symbols_count[sym] = symbols_count.get(sym, 0) + 1
        sides_count[s["side"]] = sides_count.get(s["side"], 0) + 1

        if s["is_on_binance"]:
            on_binance_count += 1

        if s["sl_distance_pct"] is not None:
            sl_distances.append(s["sl_distance_pct"])

        if s["tp_distances_pct"]:
            tp1_distances.append(s["tp_distances_pct"][0])

        if s["leverage_requested"]:
            leverages_stated.append(s["leverage_requested"])

        if s["max_target_hit"] > 0:
            for t in range(1, s["max_target_hit"] + 1):
                if t in target_hits:
                    target_hits[t] += 1
        if s["stop_hit"]:
            stop_hit_count += 1

    analysis = {
        "chat_id": CHAT_ID,
        "chat_title": "Crypto Neon",
        "days": 90,
        "total_messages": len(messages_data),
        "total_signals": total_signals,
        "valid_signals": valid_signals,
        "invalid_signals": invalid_signals,
        "total_updates": len(updates),
        "total_promos": len(promos),
        "total_other": len(other),
        "binance_compatible_signals": on_binance_count,
        "binance_compatible_pct": round(on_binance_count / total_signals * 100, 2) if total_signals else 0,
        "sides": sides_count,
        "top_symbols": sorted(symbols_count.items(), key=lambda x: x[1], reverse=True)[:15],
        "target_hits_reported": target_hits,
        "stop_hits_reported": stop_hit_count,
        "sl_distance_stats": {
            "min": round(min(sl_distances), 2) if sl_distances else 0,
            "max": round(max(sl_distances), 2) if sl_distances else 0,
            "avg": round(sum(sl_distances) / len(sl_distances), 2) if sl_distances else 0,
            "median": round(sorted(sl_distances)[len(sl_distances) // 2], 2) if sl_distances else 0,
            "distribution": {
                "under_3pct": sum(1 for d in sl_distances if d < 3.0),
                "3pct_to_5pct": sum(1 for d in sl_distances if 3.0 <= d < 5.0),
                "5pct_to_8pct": sum(1 for d in sl_distances if 5.0 <= d < 8.0),
                "8pct_to_12pct": sum(1 for d in sl_distances if 8.0 <= d < 12.0),
                "over_12pct": sum(1 for d in sl_distances if d >= 12.0),
            }
        },
        "tp1_distance_stats": {
            "min": round(min(tp1_distances), 2) if tp1_distances else 0,
            "max": round(max(tp1_distances), 2) if tp1_distances else 0,
            "avg": round(sum(tp1_distances) / len(tp1_distances), 2) if tp1_distances else 0,
        },
        "leverage_stated_count": len(leverages_stated),
        "signals": list(signals.values()),
        "promos_sample": [p["text"][:100] for p in promos[:5]],
    }

    with open(OUTPUT_ANALYSIS, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    return analysis

async def main():
    msgs = await fetch_messages()
    symbols = get_binance_futures_symbols()
    analysis = analyze_dataset(msgs, symbols)

    print("\n" + "=" * 70)
    print("📊 BÁO CÁO PHÂN TÍCH CHI TIẾT KÊNH CRYPTO NEON (3 THÁNG QUA)")
    print("=" * 70)
    print(f"• Tổng số tin nhắn:           {analysis['total_messages']}")
    print(f"• Tổng số kèo phát hiện:      {analysis['total_signals']}")
    print(f"• Kèo hợp lệ cú pháp bot:     {analysis['valid_signals']} ({analysis['valid_signals']/analysis['total_signals']*100:.1f}%)")
    print(f"• Kèo có trên Binance USD-M:  {analysis['binance_compatible_signals']} ({analysis['binance_compatible_pct']}%)")
    print(f"• Phân bổ chiều:              LONG: {analysis['sides'].get('BUY', 0)} | SHORT: {analysis['sides'].get('SELL', 0)}")
    print(f"• Tin quảng cáo MEXC / VIP:   {analysis['total_promos']}")
    print(f"• Cập nhật chốt lời / SL:     {analysis['total_updates']}")
    print("\n[Thống kê khoảng cách Stop Loss %]:")
    sl_st = analysis['sl_distance_stats']
    print(f"  - Nhỏ nhất: {sl_st['min']}% | Lớn nhất: {sl_st['max']}% | Trung bình: {sl_st['avg']}% | Median: {sl_st['median']}%")
    print(f"  - Phân bổ SL: <3%: {sl_st['distribution']['under_3pct']} kèo | 3-5%: {sl_st['distribution']['3pct_to_5pct']} kèo | 5-8%: {sl_st['distribution']['5pct_to_8pct']} kèo | 8-12%: {sl_st['distribution']['8pct_to_12pct']} kèo | >12%: {sl_st['distribution']['over_12pct']} kèo")
    print("\n[Thống kê đạt Target theo báo cáo admin]:")
    for t_idx, hits in analysis['target_hits_reported'].items():
        print(f"  - Đạt Target {t_idx}: {hits} kèo ({hits / analysis['total_signals'] * 100:.1f}%)")
    print(f"  - Admin báo chạm SL: {analysis['stop_hits_reported']} kèo")

if __name__ == "__main__":
    asyncio.run(main())
