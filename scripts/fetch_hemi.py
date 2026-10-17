import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

conn = sqlite3.connect("data/trading_state.db")
c = conn.cursor()
c.execute("SELECT message_id, raw_text FROM messages WHERE chat_id = -1001656921849 AND raw_text LIKE '%0.018700%'")
rows = c.fetchall()
for r in rows:
    print(r[0])
    print(repr(r[1]))
conn.close()
