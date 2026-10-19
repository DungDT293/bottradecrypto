import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = r"e:\TOOL DUNG CODE\bottradecrypto"
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.functions.messages import GetDialogFiltersRequest

from config.config import load_config
from core.enums import UpdateType
from core.models import SourceMetadata
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from parser.validator import SignalValidator

load_dotenv(r"C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\.env")
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION = r"C:\Users\PC Gaming\.gemini\antigravity\brain\60dc2aab-6e87-40e5-ae6e-48b4f6eade2b\scratch\temp_scan"

OUTPUT_FILE = r"C:\Users\PC Gaming\.gemini\antigravity\brain\60dc2aab-6e87-40e5-ae6e-48b4f6eade2b\scratch\scan_keo_trade_1_year_full.json"


async def run_full_scan():
    cfg = load_config()
    parser = SignalParser()
    validator = SignalValidator(cfg)
    upd_parser = ChannelUpdateParser()

    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        print("[LỖI] Phiên làm việc Telegram chưa xác thực!")
        return

    # 1. Locate folder 'Kèo trade'
    raw_filters = await client(GetDialogFiltersRequest())
    filters = raw_filters.filters if hasattr(raw_filters, "filters") else (raw_filters if isinstance(raw_filters, list) else [])
    
    target_f = None
    for f in filters:
        title = getattr(f, "title", "")
        if hasattr(title, "text"):
            title = str(title.text)
        if "kèo trade" in str(title).lower():
            target_f = f
            print(f"✅ ĐÃ TÌM THẤY FOLDER: '{title}'")
            break

    if not target_f:
        print("❌ Không tìm thấy folder 'Kèo trade'!")
        await client.disconnect()
        return

    pinned_ids = []
    for p in getattr(target_f, "pinned_peers", []):
        cid = getattr(p, "channel_id", getattr(p, "chat_id", None))
        if cid:
            pinned_ids.append(int(f"-100{cid}"))

    include_ids = []
    for p in getattr(target_f, "include_peers", []):
        cid = getattr(p, "channel_id", getattr(p, "chat_id", None))
        if cid:
            include_ids.append(int(f"-100{cid}"))

    # Resolve all channel dialogs
    dialogs = await client.get_dialogs()
    dlg_map = {d.id: d for d in dialogs}

    # Build ordered list: Pinned channels first, then other folder channels
    ordered_targets = []
    for pid in pinned_ids:
        d = dlg_map.get(pid)
        ordered_targets.append({
            "id": pid,
            "name": d.name if d else f"Channel_{pid}",
            "is_pinned": True,
        })

    for cid in include_ids:
        if cid not in pinned_ids:
            d = dlg_map.get(cid)
            ordered_targets.append({
                "id": cid,
                "name": d.name if d else f"Channel_{cid}",
                "is_pinned": False,
            })

    one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
    print("=" * 80)
    print(f"BẮT ĐẦU QUÉT LỊCH SỬ 1 NĂM (TỪ {one_year_ago.strftime('%d/%m/%Y')} ĐẾN NAY)")
    print(f"Tổng số nhóm trong folder: {len(ordered_targets)} nhóm ({len(pinned_ids)} nhóm ghim + {len(ordered_targets) - len(pinned_ids)} nhóm khác)")
    print("=" * 80)

    all_channel_stats = []

    for idx, ch in enumerate(ordered_targets, 1):
        cid = ch["id"]
        cname = ch["name"]
        is_pinned = ch["is_pinned"]
        tag = "[PINNED]" if is_pinned else "[FOLDER]"
        print(f"\n{tag} [{idx}/{len(ordered_targets)}] Đang quét: '{cname}' (ID: {cid})...")
        start_t = time.time()

        try:
            entity = await client.get_entity(cid)
        except Exception as e:
            print(f"  ❌ Không thể lấy entity nhóm ({e}), bỏ qua.")
            continue

        total_msgs = 0
        valid_signals = []
        rejected_signals = []
        updates_count = 0
        clickbait_spam_count = 0
        leverage_list = []
        pairs_freq = {}
        oldest_date = None
        newest_date = None

        # Fetch backwards from now until one_year_ago
        # limit=4000 is plenty for 1 year of trade calls per channel
        async for m in client.iter_messages(entity, limit=4000):
            if not m.message:
                continue

            msg_date = m.date
            if msg_date < one_year_ago:
                break

            total_msgs += 1
            msg_text = m.message

            if newest_date is None:
                newest_date = msg_date
            oldest_date = msg_date

            # Check clickbait link pattern
            lower_text = msg_text.lower()
            is_clickbait = any(kw in lower_text for kw in ["t.me/+", "t.me/joinchat", "join vip", "giveaway", "hit 100+ reactions", "ready ?"])

            # Check update
            upd_type, upd_val, upd_note = upd_parser.parse_update(msg_text)
            if upd_type != UpdateType.UNKNOWN:
                updates_count += 1

            # Parse signal
            meta = SourceMetadata(chat_id=cid, message_id=m.id, telegram_timestamp=msg_date, name=cname)
            sig = parser.parse(msg_text, meta)
            if sig:
                # Validate
                parsed_sig, val_sig = validator.validate_and_resolve(sig)
                if val_sig is not None:
                    valid_signals.append({
                        "msg_id": m.id,
                        "date": msg_date.isoformat(),
                        "symbol": val_sig.symbol,
                        "side": val_sig.side.value if val_sig.side else None,
                        "entries": [float(x[0]) if isinstance(x, (tuple, list)) else float(x) for x in val_sig.entries] if val_sig.entries else [],
                        "tps": [float(x[0]) if isinstance(x, (tuple, list)) else float(x) for x in val_sig.take_profits] if val_sig.take_profits else [],
                        "sl": float(val_sig.stop_loss) if val_sig.stop_loss else None,
                        "leverage": val_sig.leverage,
                    })
                    if val_sig.leverage:
                        leverage_list.append(val_sig.leverage)
                    pairs_freq[val_sig.symbol] = pairs_freq.get(val_sig.symbol, 0) + 1
                else:
                    rej_reason = getattr(parsed_sig, "rejection_reason", None) or str(getattr(parsed_sig, "state", "REJECTED"))
                    rejected_signals.append({
                        "msg_id": m.id,
                        "reason": str(rej_reason),
                        "symbol": getattr(parsed_sig, "symbol", "UNKNOWN"),
                    })
            else:
                if is_clickbait and ("entry" in lower_text or "signal" in lower_text or "#" in lower_text):
                    clickbait_spam_count += 1

        duration = time.time() - start_t
        oldest_s = oldest_date.strftime("%d/%m/%Y") if oldest_date else "N/A"
        newest_s = newest_date.strftime("%d/%m/%Y") if newest_date else "N/A"

        total_valid = len(valid_signals)
        total_rej = len(rejected_signals)
        signal_purity = (total_valid / (total_valid + total_rej) * 100) if (total_valid + total_rej) > 0 else 0
        avg_lev = (sum(leverage_list) / len(leverage_list)) if leverage_list else 20.0

        days_span = max(1, (newest_date - oldest_date).days if (newest_date and oldest_date) else 1)
        signals_per_month = round((total_valid / days_span) * 30, 1)

        rr_list = []
        for s in valid_signals:
            if s["entries"] and s["tps"] and s["sl"]:
                entry = s["entries"][0]
                tp1 = s["tps"][0]
                sl = s["sl"]
                reward = abs(tp1 - entry)
                risk = abs(entry - sl)
                if risk > 0:
                    rr_list.append(reward / risk)
        avg_rr = round(sum(rr_list) / len(rr_list), 2) if rr_list else 1.5

        top_pairs = sorted(pairs_freq.items(), key=lambda x: x[1], reverse=True)[:5]

        # Tiering criteria
        if total_valid >= 80 and signal_purity >= 75 and clickbait_spam_count <= 15:
            tier = "Tier S (Cực Phẩm - Khuyên Dùng)"
            recom = "CỰC KỲ NÊN THEO DÕI. Tín hiệu chuẩn cú pháp, rõ ràng Entry/TP/SL, sạch sẽ không spam, bot vào lệnh tự động 100%."
        elif total_valid >= 40 and signal_purity >= 40:
            tier = "Tier A (Chất Lượng Tốt)"
            recom = "ĐÁNG THEO DÕI. Tín hiệu khá chuẩn, tỷ lệ lệnh hợp lệ tốt, đôi lúc có tin quảng cáo nhưng bot lọc được an toàn."
        elif total_valid >= 20 and signal_purity >= 20:
            tier = "Tier B (Trung Bình - Cần Chọn Lọc)"
            recom = "CẦN CHỌN LỌC. Có kèo thật nhưng tần suất thất thường hoặc lẫn nhiều tin phân tích/chỉnh sửa."
        elif clickbait_spam_count >= 20 or (total_valid < 10 and clickbait_spam_count > total_valid):
            tier = "Red Flag / Cảnh Báo Spam"
            recom = "CẢNH BÁO / KHÔNG NÊN THEO DÕI. Kênh chủ yếu bắn tin mập mờ, câu reaction, chèn link mời vào nhóm VIP."
        else:
            tier = "Tier C (Kém / Không Phù Hợp)"
            recom = "KHÔNG NÊN THEO DÕI. Rất ít kèo giao dịch hoặc cú pháp không nhất quán."

        ch_stat = {
            "id": cid,
            "name": cname,
            "is_pinned": is_pinned,
            "time_range": f"{oldest_s} - {newest_s}",
            "days_active": days_span,
            "total_messages": total_msgs,
            "valid_signals_count": total_valid,
            "rejected_signals_count": total_rej,
            "signal_purity_pct": round(signal_purity, 1),
            "clickbait_spam_count": clickbait_spam_count,
            "signals_per_month": signals_per_month,
            "avg_leverage": round(avg_lev, 1),
            "avg_rr_tp1": avg_rr,
            "top_pairs": [p[0] for p in top_pairs],
            "tier": tier,
            "recommendation": recom,
            "scan_duration_sec": round(duration, 1),
        }

        all_channel_stats.append(ch_stat)

        print(f"  ✅ Quét xong: {total_msgs:,} tin nhắn ({oldest_s} -> {newest_s})")
        print(f"     + Kèo hợp lệ (Valid): {total_valid:,} | Lỗi/Từ chối: {total_rej:,} | Tin rác/câu view: {clickbait_spam_count}")
        print(f"     + Độ sạch tín hiệu (Purity): {signal_purity:.1f}% | Tần suất: {signals_per_month} kèo/tháng")
        print(f"     + Đòn bẩy TB: {avg_lev:.0f}x | Tỷ lệ R:R TP1: 1:{avg_rr}")
        print(f"     + Xếp hạng: {tier}")

        # Sleep briefly between channels to avoid Telegram rate limits
        await asyncio.sleep(0.8)

    await client.disconnect()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_channel_stats, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print(f"HOÀN TẤT QUÉT 1 NĂM CHO TOÀN BỘ {len(all_channel_stats)} NHÓM TRONG FOLDER 'KÈO TRADE'!")
    print(f"Kết quả chi tiết đã lưu tại: {OUTPUT_FILE}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_full_scan())
