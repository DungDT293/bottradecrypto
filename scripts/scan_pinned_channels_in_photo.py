import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Any
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient

from config.config import load_config
from core.enums import PositionSide, SignalState
from core.models import SourceMetadata
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from parser.validator import SignalValidator

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PINNED_CHANNELS = [
    {"name": "CRYPTO MONK", "id": -1001552004524},
    {"name": "ESTR - EAT SLEEP TRADE REPEAT", "id": -1001656921849},
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

def get_binance_futures_symbols():
    try:
        url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {s["symbol"] for s in data["symbols"]}
    except Exception as e:
        print(f"Warning: could not fetch Binance symbols ({e})")
        return set()

async def scan_pinned_channels():
    cfg = load_config()
    parser = SignalParser()
    validator = SignalValidator(cfg)
    upd_parser = ChannelUpdateParser()
    binance_symbols = get_binance_futures_symbols()

    if not cfg.telegram.api_id or not cfg.telegram.api_hash:
        raise RuntimeError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in local .env")
    client = TelegramClient("data/telegram_user", cfg.telegram.api_id, cfg.telegram.api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print("Telegram not authorized!")
        return

    # Cutoff 48 hours to cover yesterday (16/10) and today (17/10)
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=48)
    today_start = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc)

    print("=" * 80)
    print(f"🚀 QUÉT TOÀN BỘ 11 KÊNH TELEGRAM ĐƯỢC GHIM TRONG ẢNH")
    print(f"   Thời gian hiện tại: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"   Phạm vi quét: Từ 48 giờ trước ({cutoff.strftime('%Y-%m-%d %H:%M')} UTC) đến nay")
    print("=" * 80)

    summary_results = []

    for idx, ch in enumerate(PINNED_CHANNELS, 1):
        cid = ch["id"]
        cname = ch["name"]
        print(f"\n[{idx}/11] 🔍 Đang quét: {cname} (ID: {cid})...")

        messages = []
        try:
            async for msg in client.iter_messages(cid, offset_date=cutoff, reverse=True):
                if msg.text:
                    messages.append(msg)
        except Exception as e:
            print(f"   ❌ Lỗi truy cập kênh {cname}: {e}")
            summary_results.append({
                "name": cname,
                "id": cid,
                "msg_count": 0,
                "signals": [],
                "updates": [],
                "status": f"ERROR: {e}",
            })
            continue

        signals_detected = []
        updates_detected = []

        override = cfg.sources.get(cid)

        for m in messages:
            txt = m.text
            msg_dt = m.date
            mid = m.id

            meta = SourceMetadata(
                chat_id=cid,
                message_id=mid,
                telegram_timestamp=msg_dt,
            )

            # Try parsing as signal
            parsed = parser.parse(txt, meta)
            if parsed.symbol_candidate and (parsed.entries or parsed.stop_loss):
                resolved, val = validator.validate_and_resolve(parsed, override)
                is_on_binance = (parsed.symbol_candidate in binance_symbols) if binance_symbols else True

                # Determine if today or yesterday
                is_today = msg_dt >= today_start

                signals_detected.append({
                    "id": mid,
                    "date": msg_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "is_today": is_today,
                    "symbol": parsed.symbol_candidate,
                    "is_on_binance": is_on_binance,
                    "side": parsed.side.value if parsed.side else "UNKNOWN",
                    "entries": [float(e) for e in parsed.entries],
                    "stop_loss": float(parsed.stop_loss) if parsed.stop_loss else None,
                    "targets": [float(t) for t in parsed.take_profits],
                    "leverage_requested": parsed.leverage_requested,
                    "validated_leverage": val.leverage if val else None,
                    "status": "VALIDATED" if val else parsed.validation_status.value,
                    "blocking_reason": parsed.blocking_reason,
                    "text": txt[:300],
                })
                continue

            # Try parsing as update
            upd_type, new_price, detail = upd_parser.parse_update(txt)
            if upd_type.value != "UNKNOWN" and "COMMENTARY" not in upd_type.value:
                updates_detected.append({
                    "id": mid,
                    "date": msg_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "type": upd_type.value,
                    "text": txt[:120].replace("\n", " "),
                })

        last_msg_text = messages[-1].text[:80].replace("\n", " ") if messages else "Không có tin mới"
        last_msg_time = messages[-1].date.strftime("%H:%M %d/%m") if messages else "N/A"

        print(f"   • Tổng tin nhắn: {len(messages)} | Tín hiệu mới: {len(signals_detected)} | Cập nhật lệnh: {len(updates_detected)}")
        print(f"   • Tin nhắn mới nhất [{last_msg_time}]: \"{last_msg_text}\"")

        for sig in signals_detected:
            today_badge = "🔥 [HÔM NAY]" if sig["is_today"] else "⏱️ [HÔM QUA]"
            binance_badge = "✅ Binance USD-M" if sig["is_on_binance"] else "⚠️ Không có trên Binance"
            val_badge = f"🎯 ĐÃ DUYỆT (Bẩy {sig['validated_leverage']}x)" if sig["status"] == "VALIDATED" else f"❌ {sig['status']} ({sig['blocking_reason']})"
            print(f"     -> {today_badge} {sig['side']} {sig['symbol']} | Entry: {sig['entries']} | SL: {sig['stop_loss']} | TPs: {sig['targets'][:3]}... | {binance_badge} | {val_badge}")

        summary_results.append({
            "name": cname,
            "id": cid,
            "msg_count": len(messages),
            "last_msg_time": last_msg_time,
            "last_msg_text": last_msg_text,
            "signals": signals_detected,
            "updates": updates_detected,
            "status": "OK",
        })

    await client.disconnect()

    with open("data/scanned_pinned_photo_channels.json", "w", encoding="utf-8") as f:
        json.dump(summary_results, f, ensure_ascii=False, indent=2)

    return summary_results

if __name__ == "__main__":
    asyncio.run(scan_pinned_channels())

