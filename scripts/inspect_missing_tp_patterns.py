import sqlite3
import sys
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

db_path = r"C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\data\trading_state.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

print("="*80)
print("PHÂN TÍCH TẤT CẢ CÁC TÍN HIỆU BỊ 'THIẾU TAKE PROFIT' TRONG 18 KÊNH THEO DÕI")
print("="*80)

# 18 monitored channels
monitored_channels = [
    -1001756316676, -1002052872813, -1001754095061, -1002007658025, -1001552004524,
    -1001370457350, -1001895315984, -1002266035358, -1001161683441, -1001212188460,
    -1001519589508, -1001966506182, -1002191067035, -1001860630181, -1001656921849,
    -1001652601224, -1001553551852, -1001781413045
]

placeholders = ",".join(str(c) for c in monitored_channels)
query = f"""
SELECT m.chat_id, m.message_id, m.raw_text, s.symbol, s.signal_id
FROM signals s
JOIN message_versions m ON s.chat_id = m.chat_id AND s.message_id = m.message_id
WHERE s.blocking_reason LIKE '%Thieu Take Profit%'
  AND s.chat_id IN ({placeholders})
ORDER BY m.message_id DESC
"""

rows = conn.execute(query).fetchall()
print(f"\nTổng số tín hiệu trong 18 kênh bị từ chối vì 'Thieu Take Profit': {len(rows)}\n")

by_chat = defaultdict(list)
for r in rows:
    by_chat[r["chat_id"]].append(r)

for chat_id, chat_rows in by_chat.items():
    print(f"\n{'#'*60}")
    print(f"KÊNH CHAT ID: {chat_id} (Tổng số lỗi TP: {len(chat_rows)})")
    print(f"{'#'*60}")
    # Sample up to 3 distinct examples
    for i, r in enumerate(chat_rows[:3]):
        print(f"\n--- MẪU {i+1} (Msg ID #{r['message_id']} - Symbol: {r['symbol']}) ---")
        lines = r["raw_text"].strip().split("\n")
        # Print relevant snippet around TP
        print("\n".join(lines[:20]))
        if len(lines) > 20:
            print("...")
            print("\n".join(lines[-6:]))

conn.close()

