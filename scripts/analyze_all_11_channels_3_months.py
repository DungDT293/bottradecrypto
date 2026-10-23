import asyncio
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Any
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient

from config.config import load_config
from core.enums import PositionSide
from core.models import SourceMetadata
from parser.normalizer import normalize_text
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from parser.validator import SignalValidator

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CHANNELS = [
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

def get_binance_symbols():
    try:
        url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {s["symbol"] for s in data["symbols"]}
    except Exception:
        return set()

def load_db_messages() -> Dict[int, List[Dict[str, Any]]]:
    conn = sqlite3.connect("data/trading_state.db")
    c = conn.cursor()
    chat_ids = tuple(ch["id"] for ch in CHANNELS)
    query = f"SELECT chat_id, message_id, telegram_timestamp, raw_text FROM messages WHERE chat_id IN {chat_ids} ORDER BY telegram_timestamp ASC"
    c.execute(query)
    rows = c.fetchall()
    conn.close()

    result: Dict[int, List[Dict[str, Any]]] = {ch["id"]: [] for ch in CHANNELS}
    for cid, mid, dt, txt in rows:
        if cid in result:
            result[cid].append({
                "id": mid,
                "date": dt,
                "text": txt,
            })
    return result

async def fetch_latest_telegram_messages(existing_msgs: Dict[int, List[Dict[str, Any]]]):
    print("Checking for today's newest messages via Telethon...")
    cfg = load_config()
    if not cfg.telegram.api_id or not cfg.telegram.api_hash:
        raise RuntimeError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in local .env")
    client = TelegramClient("data/telegram_user", cfg.telegram.api_id, cfg.telegram.api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print("Telegram client not authorized!")
        return

    for ch in CHANNELS:
        cid = ch["id"]
        cname = ch["name"]
        known_ids = {m["id"] for m in existing_msgs.get(cid, [])}

        try:
            new_count = 0
            async for msg in client.iter_messages(cid, limit=50):
                if msg.text and msg.id not in known_ids:
                    existing_msgs[cid].append({
                        "id": msg.id,
                        "date": msg.date.isoformat(),
                        "text": msg.text,
                    })
                    new_count += 1
            if new_count > 0:
                print(f"  + Added {new_count} latest messages for {cname}")
        except Exception as e:
            print(f"  Warning fetching latest for {cname}: {e}")

    await client.disconnect()

def classify_message(text: str, sig_parser: SignalParser, upd_parser: ChannelUpdateParser, validator: SignalValidator, cid: int, mid: int, dt: str, binance_symbols: set, override: Any) -> Dict[str, Any]:
    norm = normalize_text(text)

    # 1. Check Exchange Referral / External Exchange Promo
    is_exchange_promo = bool(re.search(
        r"(?:account on the MEXC|MEXC exchange|send me your UID|mexc\.com|bitunix\.com|register\?vipCode|register\?inviteCode|bingx\.com|bitget\.com|bybit\.com|okx\.com|trade on mexc|bonus on mexc|deposit bonus)",
        text,
        re.IGNORECASE,
    )) and not re.search(r"\b(?:Target1|Entry|STOP LOSS)\b", text, re.IGNORECASE)

    if is_exchange_promo:
        return {
            "category": "EXCHANGE_PROMO",
            "category_vn": "Quảng cáo sàn ngoài / Link Ref",
            "details": "Mời tạo tài khoản sàn MEXC/Bitunix/kêu gửi UID",
            "data": None,
        }

    # 2. Check VIP Lure / Baiting / Paid Group Ads
    is_vip_bait = bool(re.search(
        r"(?:join\s*vip|join\s*our\s*premium|vip\s*membership|dm\s*for\s*vip|lifetime\s*vip|vip\s*access|only\s*(?:first\s*)?\d+\s*(?:slots?|people)|free\s*for\s*\d+\s*minutes\s*only|paid\s*channel\s*free\s*now|free\s*premiums|contact\s*admin\s*for\s*vip|vip\s*winner|dm\s*to\s*join|she\s*accept\s*\d+\s*people\s*without\s*money|vip\s*entry\s*-\s*100%\s*free|t\.me/\+[A-Za-z0-9_-]+)",
        text,
        re.IGNORECASE,
    )) and not re.search(r"\b(?:Entry|Targets?|Stop\s*Loss|Take\s*Profit)\b", text, re.IGNORECASE)

    if is_vip_bait:
        return {
            "category": "VIP_BAIT",
            "category_vn": "Dụ dỗ vào nhóm VIP / Mua slot",
            "details": "Quảng cáo nhóm VIP, DM admin, giới hạn slot, link t.me/+",
            "data": None,
        }

    # 3. Try parsing as Signal
    meta = SourceMetadata(
        chat_id=cid,
        message_id=mid,
        telegram_timestamp=datetime.fromisoformat(dt) if "T" in dt else datetime.utcnow(),
    )
    parsed_sig = sig_parser.parse(text, meta)
    if parsed_sig.symbol_candidate and (parsed_sig.entries or parsed_sig.stop_loss):
        resolved, val = validator.validate_and_resolve(parsed_sig, override)
        is_on_binance = (parsed_sig.symbol_candidate in binance_symbols) if binance_symbols else True

        return {
            "category": "SIGNAL",
            "category_vn": "Tin nhắn bắn kèo (Trade Signal)",
            "details": f"{'VALIDATED' if val else 'REJECTED'}: {parsed_sig.side.value if parsed_sig.side else 'UNKNOWN'} {parsed_sig.symbol_candidate}",
            "data": {
                "symbol": parsed_sig.symbol_candidate,
                "is_on_binance": is_on_binance,
                "side": parsed_sig.side.value if parsed_sig.side else "UNKNOWN",
                "entries": [float(e) for e in parsed_sig.entries],
                "stop_loss": float(parsed_sig.stop_loss) if parsed_sig.stop_loss else None,
                "targets": [float(t) for t in parsed_sig.take_profits],
                "leverage_requested": parsed_sig.leverage_requested,
                "validated_leverage": val.leverage if val else None,
                "status": "VALIDATED" if val else parsed_sig.validation_status.value,
                "blocking_reason": parsed_sig.blocking_reason,
            }
        }

    # 4. Check Trade Updates (TP Hit, SL Hit, Breakeven, Close)
    # Check Target Hit e.g. "Target 1 Done", "TP2 HIT", "Profit Booked"
    done_m = re.search(r"#?([A-Za-z0-9]+).*?(?:Target\s*(\d+)\s*(?:Done|Hit|Reached)|TP\s*(\d+)\s*(?:Done|Hit)|Profit\s*Booked)", text, re.IGNORECASE)
    if done_m:
        sym = done_m.group(1).upper()
        t_idx = done_m.group(2) or done_m.group(3)
        return {
            "category": "TRADE_UPDATE",
            "category_vn": "Báo chốt lời / Chạm Target",
            "details": f"Báo TP{t_idx if t_idx else ''} khớp cho #{sym}",
            "data": {"symbol": sym, "type": "TARGET_HIT", "target_index": int(t_idx) if t_idx else 1},
        }

    upd_type, new_price, detail = upd_parser.parse_update(text)
    if upd_type.value not in ["UNKNOWN", "COMMENTARY"]:
        return {
            "category": "TRADE_UPDATE",
            "category_vn": "Cập nhật lệnh (SL / BE / Đóng)",
            "details": detail,
            "data": {"type": upd_type.value, "price": float(new_price) if new_price else None},
        }

    # 5. Market Commentary / News / Greetings
    return {
        "category": "COMMENTARY_NEWS",
        "category_vn": "Nhận định thị trường / Tin tức / Chào hỏi",
        "details": "Bình luận thị trường, tin tức BTC, chào buổi sáng, nhắc quản lý vốn",
        "data": None,
    }

async def main():
    cfg = load_config()
    sig_parser = SignalParser()
    upd_parser = ChannelUpdateParser()
    validator = SignalValidator(cfg)
    binance_symbols = get_binance_symbols()

    # Load messages
    all_msgs = load_db_messages()
    await fetch_latest_telegram_messages(all_msgs)

    print("\n" + "=" * 90)
    print("🚀 BẮT ĐẦU PHÂN LOẠI & KẾT XUẤT TOÀN BỘ TIN NHẮN 3 THÁNG CHO 11 KÊNH GHIM")
    print("=" * 90)

    channel_stats = []

    for ch in CHANNELS:
        cid = ch["id"]
        cname = ch["name"]
        msgs = all_msgs.get(cid, [])
        override = cfg.sources.get(cid)

        categories_count = {
            "SIGNAL": 0,
            "TRADE_UPDATE": 0,
            "VIP_BAIT": 0,
            "EXCHANGE_PROMO": 0,
            "COMMENTARY_NEWS": 0,
        }

        signals_list = []
        updates_list = []
        vip_baits = []
        exchange_promos = []

        for m in msgs:
            res = classify_message(
                text=m["text"],
                sig_parser=sig_parser,
                upd_parser=upd_parser,
                validator=validator,
                cid=cid,
                mid=m["id"],
                dt=m["date"],
                binance_symbols=binance_symbols,
                override=override,
            )

            cat = res["category"]
            categories_count[cat] += 1

            if cat == "SIGNAL":
                signals_list.append({"id": m["id"], "date": m["date"], **res["data"]})
            elif cat == "TRADE_UPDATE":
                updates_list.append({"id": m["id"], "date": m["date"], "text": m["text"][:80], **res["data"]})
            elif cat == "VIP_BAIT":
                vip_baits.append({"id": m["id"], "date": m["date"], "text": m["text"][:100]})
            elif cat == "EXCHANGE_PROMO":
                exchange_promos.append({"id": m["id"], "date": m["date"], "text": m["text"][:100]})

        total = len(msgs)
        valid_sigs = sum(1 for s in signals_list if s["status"] == "VALIDATED")

        stat = {
            "name": cname,
            "id": cid,
            "total_messages": total,
            "categories": categories_count,
            "categories_pct": {
                k: round(v / total * 100, 1) if total else 0
                for k, v in categories_count.items()
            },
            "signals_count": len(signals_list),
            "valid_signals_count": valid_sigs,
            "valid_signals_pct": round(valid_sigs / len(signals_list) * 100, 1) if signals_list else 0,
            "signals_sample": signals_list[-5:],
            "vip_bait_sample": vip_baits[-3:],
            "exchange_promo_sample": exchange_promos[-3:],
        }
        channel_stats.append(stat)

    # Save to JSON
    with open("data/all_11_channels_3_months_classified.json", "w", encoding="utf-8") as f:
        json.dump(channel_stats, f, ensure_ascii=False, indent=2)

    # Print Report
    print("\n" + "=" * 95)
    print(f"{'KÊNH TELEGRAM':<28} | {'TỔNG TIN':<9} | {'BẮN KÈO':<11} | {'CẬP NHẬT TP/SL':<15} | {'DỤ VIP':<9} | {'QC SÀN':<8}")
    print("-" * 95)
    for s in channel_stats:
        c = s["categories"]
        p = s["categories_pct"]
        sig_str = f"{c['SIGNAL']} ({p['SIGNAL']}%)"
        upd_str = f"{c['TRADE_UPDATE']} ({p['TRADE_UPDATE']}%)"
        vip_str = f"{c['VIP_BAIT']} ({p['VIP_BAIT']}%)"
        ref_str = f"{c['EXCHANGE_PROMO']} ({p['EXCHANGE_PROMO']}%)"
        print(f"{s['name'][:28]:<28} | {s['total_messages']:<9} | {sig_str:<11} | {upd_str:<15} | {vip_str:<9} | {ref_str:<8}")
    print("=" * 95)

if __name__ == "__main__":
    asyncio.run(main())

