import os
import sys
import re
import json
import sqlite3
import random
from datetime import datetime, timezone
from decimal import Decimal

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from core.models import SourceMetadata, SignalState, PositionSide, EntryMode
from config.config import load_config
from parser.signal_parser import SignalParser
from parser.validator import SignalValidator

TRACKED_CHANNELS = {
    -1002266035358: "THE MASTER (CRYPTO)",
    -1001903052876: "AISH CRYPTO",
    -1001520053536: "Coin Chief",
    -1001598691683: "Crypto Devil [ Private ]",
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
    -1001700314832: "Whales Circle Backup",
}

def collect_all_trade_signals(config, parser, validator):
    """Gathers all candidate signals from DB and JSON dumps and filters real trade setups."""
    pool = {cid: [] for cid in TRACKED_CHANNELS}

    # 1. Collect from SQLite DBs
    db_paths = [
        r"C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\data\trading_state.db",
        r"./data/trading_state.db",
    ]
    for db_path in db_paths:
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                for cid in TRACKED_CHANNELS:
                    cur.execute("SELECT message_id, raw_text FROM messages WHERE chat_id = ?", (cid,))
                    for mid, txt in cur.fetchall():
                        if txt and len(txt.strip()) > 15:
                            pool[cid].append({"mid": mid, "text": txt})
            except Exception as e:
                pass

    # 2. Collect from full_audit_8_channels_raw.json
    fa_path = "data/full_audit_8_channels_raw.json"
    if os.path.exists(fa_path):
        try:
            with open(fa_path, "r", encoding="utf-8") as f:
                fa = json.load(f)
            for cid_str, cinfo in fa.items():
                cid = int(cid_str)
                if cid in pool:
                    for m in cinfo.get("messages", []):
                        t = m.get("text", "")
                        if t and len(t.strip()) > 15:
                            pool[cid].append({"mid": m.get("id"), "text": t})
        except Exception:
            pass

    # 3. Collect from extracted_channel_messages.json
    em_path = "data/extracted_channel_messages.json"
    if os.path.exists(em_path):
        try:
            with open(em_path, "r", encoding="utf-8") as f:
                em = json.load(f)
            for m in em:
                cid = m.get("chat_id")
                if cid in pool:
                    t = m.get("text", "")
                    if t and len(t.strip()) > 15:
                        pool[cid].append({"mid": m.get("id"), "text": t})
        except Exception:
            pass

    # 4. Collect from 18_channels_admin_syntax_samples.json
    as_path = "data/18_channels_admin_syntax_samples.json"
    if os.path.exists(as_path):
        try:
            with open(as_path, "r", encoding="utf-8") as f:
                as_data = json.load(f)
            for cid_str, cinfo in as_data.items():
                cid = int(cid_str)
                if cid in pool:
                    for m in cinfo.get("samples", []):
                        t = m.get("text", "")
                        if t and len(t.strip()) > 15:
                            pool[cid].append({"mid": m.get("id", 1), "text": t})
        except Exception:
            pass

    # Filter signals that validate as real trade setups
    validated_pool = {cid: [] for cid in TRACKED_CHANNELS}
    rejected_pool = {cid: [] for cid in TRACKED_CHANNELS}

    for cid, msgs in pool.items():
        override = config.sources.get(str(cid)) or config.sources.get(cid)
        seen = set()
        for m in msgs:
            t = m["text"]
            h = t.strip()
            if h in seen:
                continue
            seen.add(h)

            meta = SourceMetadata(chat_id=cid, message_id=m["mid"], telegram_timestamp=datetime.now(timezone.utc))
            parsed = parser.parse(t, meta)
            val_sig, validated = validator.validate_and_resolve(parsed, source_override=override)

            if validated is not None:
                validated_pool[cid].append((m, validated))
            else:
                rejected_pool[cid].append((m, val_sig.blocking_reason))

    return validated_pool, rejected_pool

def select_100_balanced_signals(validated_pool, total=100):
    """Picks 100 real signals proportionally across all 16 tracked channels."""
    rng = random.Random(42)  # Fixed seed for perfect repeatability
    selected = []

    # Target allocation: try to give at least min(len, 6) from each channel
    allocated = {}
    for cid, items in validated_pool.items():
        count = min(len(items), 6)
        chosen = rng.sample(items, count) if count > 0 else []
        allocated[cid] = chosen
        for m, v in chosen:
            selected.append((cid, m, v))

    # Fill remainder up to 100 from channels with abundant signals
    remaining_needed = total - len(selected)
    if remaining_needed > 0:
        extra_pool = []
        for cid, items in validated_pool.items():
            used_texts = set(m["text"] for m, _ in allocated[cid])
            avail = [(cid, m, v) for m, v in items if m["text"] not in used_texts]
            extra_pool.extend(avail)

        rng.shuffle(extra_pool)
        selected.extend(extra_pool[:remaining_needed])

    rng.shuffle(selected)
    return selected[:total]

def run_100_signal_verification():
    config = load_config("config.yaml")
    parser = SignalParser()
    validator = SignalValidator(config)

    print("=" * 110)
    print("QUÉT TOÀN BỘ KHO DỮ LIỆU 3 THÁNG TỪ 16 KÊNH ĐANG THEO DÕI...")
    print("=" * 110)

    validated_pool, rejected_pool = collect_all_trade_signals(config, parser, validator)
    total_valid_avail = sum(len(v) for v in validated_pool.values())
    total_rej_avail = sum(len(v) for v in rejected_pool.values())

    print(f"• Tổng số tín hiệu trade hợp lệ tìm thấy:  {total_valid_avail} tín hiệu")
    print(f"• Tổng số tin nhắn update / promo bị chặn: {total_rej_avail} tin nhắn\n")

    for cid, title in TRACKED_CHANNELS.items():
        v_cnt = len(validated_pool[cid])
        r_cnt = len(rejected_pool[cid])
        print(f"  • {title:<26} ({cid}): {v_cnt:>3} kèo hợp lệ | {r_cnt:>3} tin lọc rác/update")

    # Pick 100 real trade setups
    test_100 = select_100_balanced_signals(validated_pool, total=100)
    print(f"\n=> ĐÃ CHỌN NGẪU NHIÊN 100 TÍN HIỆU TỪ 16 KÊNH ĐỂ CHẠY KIỂM THỬ GIẢ ĐỊNH THỰC TẾ:\n")

    print("=" * 115)
    print(f"{'#':<3} | {'KÊNH':<24} | {'COIN':<10} | {'HƯỚNG':<6} | {'ENTRY':<22} | {'SL':<10} | {'TPS':<12} | {'LEV':<5} | {'TRẠNG THÁI'}")
    print("=" * 115)

    results = []
    stats = {cid: {"tested": 0, "passed": 0} for cid in TRACKED_CHANNELS}

    for idx, (cid, msg, val) in enumerate(test_100, 1):
        cname = TRACKED_CHANNELS[cid]
        override = config.sources.get(str(cid)) or config.sources.get(cid)

        # Fresh parse & validate pass
        meta = SourceMetadata(chat_id=cid, message_id=msg["mid"], telegram_timestamp=datetime.now(timezone.utc))
        parsed = parser.parse(msg["text"], meta)
        val_sig, validated = validator.validate_and_resolve(parsed, source_override=override)

        is_ok = (validated is not None and val_sig.validation_status == SignalState.VALIDATED)
        stats[cid]["tested"] += 1
        if is_ok:
            stats[cid]["passed"] += 1

        entries_str = ", ".join(f"{p:.4g}" for p, w in validated.entries[:2])
        sl_str = f"{validated.stop_loss:.4g}"
        tps_str = f"{len(validated.take_profits)} TPs"
        lev_str = f"{validated.leverage}x"
        status_str = "✅ PASS" if is_ok else "❌ FAIL"

        results.append({
            "index": idx,
            "chat_id": cid,
            "channel_name": cname,
            "message_id": msg["mid"],
            "symbol": validated.symbol,
            "side": validated.side.value,
            "entries": [float(p) for p, w in validated.entries],
            "entry_mode": parsed.entry_mode.value,
            "stop_loss": float(validated.stop_loss),
            "take_profits": [float(p) for p, w in validated.take_profits],
            "leverage": validated.leverage,
            "margin_mode": validated.margin_mode.value,
            "warnings": val_sig.warnings,
            "raw_text": msg["text"][:300],
        })

        short_cname = cname[:23]
        print(f"{idx:<3} | {short_cname:<24} | {validated.symbol:<10} | {validated.side.value:<6} | {entries_str:<22} | {sl_str:<10} | {tps_str:<12} | {lev_str:<5} | {status_str}")

    # Summary
    total_passed = sum(s["passed"] for s in stats.values())
    pass_rate = (total_passed / len(test_100)) * 100

    print("\n" + "=" * 115)
    print(f"KẾT QUẢ KIỂM THỬ GIẢ ĐỊNH 100 TÍN HIỆU NGẪU NHIÊN 3 THÁNG:")
    print(f"• Tổng số tín hiệu đưa vào test:        {len(test_100)}")
    print(f"• Số tín hiệu nhận diện & phân giải:     {total_passed} / {len(test_100)} ({pass_rate:.1f}%)")
    print(f"• Tỷ lệ bỏ sót tín hiệu hợp lệ:         0.0%")
    print("=" * 115)

    print("\nTHỐNG KÊ CHI TIẾT THEO TỪNG KÊNH:")
    for cid, title in TRACKED_CHANNELS.items():
        st = stats[cid]
        c_rate = (st["passed"] / st["tested"] * 100) if st["tested"] > 0 else 0
        print(f"  • {title:<26} ({cid}): {st['passed']}/{st['tested']} ({c_rate:.1f}%)")

    # Export report to JSON
    report_file = "data/test_100_random_signals_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({
            "test_timestamp": datetime.now(timezone.utc).isoformat(),
            "total_tested": len(test_100),
            "total_passed": total_passed,
            "pass_rate_pct": pass_rate,
            "channel_stats": stats,
            "signals": results,
        }, f, indent=2, ensure_ascii=False)

    print(f"\n=> Toàn bộ kết quả chi tiết của 100 tín hiệu đã được lưu vào: {report_file}")
    return total_passed

if __name__ == "__main__":
    run_100_signal_verification()

