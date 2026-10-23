import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import re
import sqlite3
import sys
from typing import Dict, List, Optional, Any, Set
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from telethon import TelegramClient, errors

from config.config import load_config
from core.enums import PositionSide
from core.models import SourceMetadata
import hashlib
from parser.normalizer import normalize_text
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from parser.validator import SignalValidator

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

def get_binance_symbols() -> Set[str]:
    try:
        url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {s["symbol"] for s in data["symbols"]}
    except Exception as e:
        print(f"Warning fetching Binance symbols: {e}")
        return set()

async def fetch_and_sync_telegram_history(cutoff_dt: datetime):
    print(f"\n📡 BẮT ĐẦU ĐỒNG BỘ TIN NHẮN TỪ TELEGRAM TRONG VÒNG NỬA NĂM (TỪ {cutoff_dt.strftime('%Y-%m-%d')} ĐẾN NAY)...")
    cfg = load_config()
    if not cfg.telegram.api_id or not cfg.telegram.api_hash:
        raise RuntimeError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in local .env")
    client = TelegramClient("data/telegram_user", cfg.telegram.api_id, cfg.telegram.api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print("Telegram client not authorized!")
        return

    conn = sqlite3.connect("data/trading_state.db")
    c = conn.cursor()

    for ch in CHANNELS:
        cid = ch["id"]
        cname = ch["name"]
        print(f"\n⏳ Đang quét lịch sử kênh: {cname} (ID: {cid})...")

        # Get existing message IDs
        c.execute("SELECT message_id FROM messages WHERE chat_id = ?", (cid,))
        existing_ids = {r[0] for r in c.fetchall()}

        # Fetch messages backwards from Telegram
        fetched_count = 0
        new_inserted = 0
        batch = []

        try:
            async for msg in client.iter_messages(cid, limit=4000):
                if not msg.date:
                    continue
                # If message is older than 6 months, stop scanning this channel
                if msg.date < cutoff_dt:
                    break

                fetched_count += 1
                if msg.text and msg.id not in existing_ids:
                    norm = normalize_text(msg.text)
                    fp = hashlib.sha256(norm.encode("utf-8")).hexdigest()
                    now_iso = datetime.now(timezone.utc).isoformat()
                    msg_iso = msg.date.isoformat()
                    edit_iso = msg.edit_date.isoformat() if msg.edit_date else None
                    sender_id = msg.sender_id if msg.sender_id else None

                    batch.append((
                        cid, msg.id, sender_id, msg_iso, now_iso, edit_iso, msg.text, norm, fp
                    ))
                    existing_ids.add(msg.id)
                    new_inserted += 1

                    if len(batch) >= 100:
                        c.executemany("""
                            INSERT OR REPLACE INTO messages
                            (chat_id, message_id, sender_id, telegram_timestamp, received_at, edit_timestamp, raw_text, normalized_text, fingerprint)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, batch)
                        conn.commit()
                        batch.clear()

            if batch:
                c.executemany("""
                    INSERT OR REPLACE INTO messages
                    (chat_id, message_id, sender_id, telegram_timestamp, received_at, edit_timestamp, raw_text, normalized_text, fingerprint)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, batch)
                conn.commit()
                batch.clear()

            print(f"  ✅ Kênh {cname}: Quét {fetched_count} tin trong 6 tháng (Thêm mới {new_inserted} tin vào DB)")

        except errors.FloodWaitError as fwe:
            print(f"  ⚠️ FloodWait: Cần chờ {fwe.seconds} giây...")
            await asyncio.sleep(fwe.seconds + 1)
        except Exception as e:
            print(f"  ❌ Lỗi khi tải kênh {cname}: {e}")

        # Small sleep between channels to be gentle
        await asyncio.sleep(0.5)

    conn.close()
    await client.disconnect()
    print("✨ Đồng bộ hoàn tất cơ sở dữ liệu tin nhắn nửa năm!")

def load_db_messages_6_months(cutoff_dt: datetime) -> Dict[int, List[Dict[str, Any]]]:
    conn = sqlite3.connect("data/trading_state.db")
    c = conn.cursor()
    chat_ids = tuple(ch["id"] for ch in CHANNELS)
    cutoff_str = cutoff_dt.isoformat()
    query = f"""
        SELECT chat_id, message_id, telegram_timestamp, raw_text 
        FROM messages 
        WHERE chat_id IN {chat_ids} AND telegram_timestamp >= ?
        ORDER BY telegram_timestamp ASC
    """
    c.execute(query, (cutoff_str,))
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

def classify_message(text: str, sig_parser: SignalParser, upd_parser: ChannelUpdateParser, validator: SignalValidator, cid: int, mid: int, dt: str, binance_symbols: Set[str], override: Any) -> Dict[str, Any]:
    # 1. Exchange Referral / Promo
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

    # 2. VIP Lure / Baiting / Paid Group Ads
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
    try:
        t_dt = datetime.fromisoformat(dt) if "T" in dt else datetime.utcnow()
    except Exception:
        t_dt = datetime.utcnow()

    meta = SourceMetadata(chat_id=cid, message_id=mid, telegram_timestamp=t_dt)
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

    # 4. Trade Updates (TP Hit, SL Hit, Breakeven, Close)
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
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=180)
    await fetch_and_sync_telegram_history(cutoff_dt)

    cfg = load_config()
    sig_parser = SignalParser()
    upd_parser = ChannelUpdateParser()
    validator = SignalValidator(cfg)
    binance_symbols = get_binance_symbols()

    all_msgs = load_db_messages_6_months(cutoff_dt)

    print("\n" + "=" * 95)
    print("🚀 PHÂN LOẠI & KẾT XUẤT TOÀN BỘ TIN NHẮN NỬA NĂM (6 THÁNG) CHO 9 NHÓM GHIM CÒN LẠI")
    print("=" * 95)

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
    out_file = "data/all_9_channels_6_months_classified.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(channel_stats, f, ensure_ascii=False, indent=2)

    print(f"\n💾 Đã lưu kết quả phân loại 6 tháng vào: {out_file}\n")
    print("=" * 115)
    print(f"{'KÊNH TELEGRAM':<28} | {'TỔNG TIN':<8} | {'KÈO HỢP LỆ':<11} | {'KÈO LỖI/CHẶN':<12} | {'CẬP NHẬT TP/SL':<15} | {'DỤ VIP':<8} | {'QC SÀN':<8}")
    print("-" * 115)
    for s in channel_stats:
        c = s["categories"]
        total = s["total_messages"]
        val_sig = s["valid_signals_count"]
        inv_sig = s["signals_count"] - val_sig
        upd = f"{c['TRADE_UPDATE']} ({round(c['TRADE_UPDATE']/total*100, 1) if total else 0}%)"
        vip = f"{c['VIP_BAIT']} ({round(c['VIP_BAIT']/total*100, 1) if total else 0}%)"
        promo = f"{c['EXCHANGE_PROMO']} ({round(c['EXCHANGE_PROMO']/total*100, 1) if total else 0}%)"
        print(f"{s['name'][:28]:<28} | {total:<8} | {val_sig:<11} | {inv_sig:<12} | {upd:<15} | {vip:<8} | {promo:<8}")
    print("=" * 115)

if __name__ == "__main__":
    asyncio.run(main())
