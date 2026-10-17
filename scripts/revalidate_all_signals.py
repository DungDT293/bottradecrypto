import json
import os
import sqlite3
import sys
from datetime import datetime
from decimal import Decimal

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config.config import load_config
from core.enums import EntryMode, PositionSide, SignalState
from core.models import ParsedSignal, SourceMetadata
from parser.validator import SignalValidator


def revalidate():
    db_path = os.path.join(PROJECT_ROOT, "data", "trading_state.db")
    conn = sqlite3.connect(db_path, timeout=30)
    c = conn.cursor()

    c.execute("SELECT state, COUNT(*) FROM signals GROUP BY state")
    initial_counts = dict(c.fetchall())

    c.execute("""
        SELECT signal_id, chat_id, message_id, symbol, side, state,
               entry_mode, entries_json, stop_loss, take_profits_json, leverage,
               blocking_reason, created_at
        FROM signals
    """)
    rows = c.fetchall()

    config = load_config()
    validator = SignalValidator(config)
    now_utc = datetime.utcnow()

    updates = []
    timeline_events = []

    for r in rows:
        (
            sig_id, chat_id, msg_id, sym, side_str, state_str,
            emode_str, entries_j, sl_str, tps_j, lev,
            blocking_reason, created_at
        ) = r

        if not sym or not side_str or not entries_j or not sl_str or not tps_j:
            continue

        # Preserve VIP bait rejections
        if state_str == "REJECTED" and blocking_reason and "VIP" in blocking_reason:
            continue

        try:
            side = PositionSide(side_str)
            entry_mode = EntryMode(emode_str) if emode_str else EntryMode.SINGLE
            entries = [Decimal(str(e)) for e in json.loads(entries_j)]
            tps = [Decimal(str(tp)) for tp in json.loads(tps_j)]
            sl = Decimal(str(sl_str))

            parsed = ParsedSignal(
                signal_id=sig_id,
                symbol_candidate=sym,
                symbol_raw=sym,
                side=side,
                entry_mode=entry_mode,
                entries=entries,
                stop_loss=sl,
                take_profits=tps,
                leverage_requested=lev or 5,
                metadata=SourceMetadata(chat_id=chat_id, message_id=msg_id, telegram_timestamp=now_utc),
                validation_status=SignalState(state_str),
                blocking_reason=blocking_reason,
            )

            res_parsed, validated = validator.validate_and_resolve(parsed)

            if validated:
                new_state = SignalState.VALIDATED.value
                new_reason = None
                updates.append((new_state, new_reason, sig_id))
                timeline_events.append((
                    sig_id,
                    now_utc.isoformat(),
                    "SIGNAL_VALIDATED",
                    f"Xác nhận tín hiệu theo chuẩn 9 mẫu: {validated.symbol} {validated.side.value}",
                    json.dumps({
                        "leverage": validated.leverage,
                        "entries": [str(e) for e in validated.entries],
                        "stop_loss": str(validated.stop_loss),
                        "take_profits": [str(tp) for tp in validated.take_profits],
                    }),
                ))
            else:
                new_state = res_parsed.validation_status.value
                new_reason = res_parsed.blocking_reason
                if new_state != state_str:
                    updates.append((new_state, new_reason, sig_id))
        except Exception:
            pass

    # Batch update in single transaction
    c.executemany("UPDATE signals SET state = ?, blocking_reason = ? WHERE signal_id = ?", updates)
    c.executemany("""
        INSERT INTO signal_timeline (signal_id, timestamp, event_type, description, payload_json)
        VALUES (?, ?, ?, ?, ?)
    """, timeline_events)
    conn.commit()

    c.execute("SELECT state, COUNT(*) FROM signals GROUP BY state")
    final_counts = dict(c.fetchall())
    conn.close()

    print("=" * 60)
    print("✅ HOÀN TẤT CẬP NHẬT TÍN HIỆU THEO CHUẨN 9 MẪU GỐC:")
    print("=" * 60)
    for st, cnt in final_counts.items():
        diff = cnt - initial_counts.get(st, 0)
        diff_str = f" (+{diff})" if diff > 0 else (f" ({diff})" if diff < 0 else "")
        print(f"   • {st}: {cnt}{diff_str}")


if __name__ == "__main__":
    revalidate()

