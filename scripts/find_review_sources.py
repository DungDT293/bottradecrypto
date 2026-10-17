import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/trading_state.db')
c = conn.cursor()

KNOWN_CHANNELS = {
    -1002052872813: "CRYPTO LEOPARD'S",
    -1001552004524: "CRYPTO MONK",
}

c.execute('''
    SELECT m.chat_id, m.message_id, m.telegram_timestamp, s.symbol, s.blocking_reason, m.raw_text
    FROM signals s
    JOIN messages m ON s.message_id = m.message_id AND s.chat_id = m.chat_id
    WHERE s.state = 'NEEDS_REVIEW'
    ORDER BY m.telegram_timestamp DESC
''')
rows = c.fetchall()

by_chat = {}
for r in rows:
    chat_id, msg_id, ts, sym, reason, text = r
    if chat_id not in by_chat:
        by_chat[chat_id] = []
    by_chat[chat_id].append((msg_id, ts, sym, reason, text))

for cid, msgs in by_chat.items():
    name = KNOWN_CHANNELS.get(cid, str(cid))
    print(f"\n========================================================")
    print(f"NHÓM: {name} (Chat ID: {cid})")
    print(f"Tổng số tin chờ xem xét: {len(msgs)}")
    print(f"Khoảng thời gian: Từ {msgs[-1][1]} đến {msgs[0][1]}")
    print(f"--------------------------------------------------------")
    print("5 tin gần nhất:")
    for m in msgs[:5]:
        first_line = m[4].split('\n')[0].strip() if m[4] else ""
        print(f"  • Coin: {m[2]:<12} | Message ID: {m[0]:<7} | Thời gian: {m[1]}")
        print(f"    Lý do: {m[3]}")
    if len(msgs) > 5:
        print(f"  ... và {len(msgs) - 5} tin khác trải dài từ {msgs[-1][1]} đến {msgs[5][1]}")
