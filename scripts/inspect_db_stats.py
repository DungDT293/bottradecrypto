import sqlite3
import os

paths = [
    r'e:\TOOL DUNG CODE\bottradecrypto\data\trading_state.db',
    r'C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\data\trading_state.db',
    r'C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\trading_state.db',
    r'C:\Users\PC Gaming\AppData\Local\telegram-binance-signal-executor\data\trading_state.db'
]

for p in paths:
    if os.path.exists(p):
        print(f"=== DB: {p} (size: {os.path.getsize(p)} bytes) ===")
        conn = sqlite3.connect(p)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Check signals per chat_id
        try:
            c.execute("""
                SELECT chat_id, COUNT(*) as cnt,
                       SUM(CASE WHEN state = 'ACTIVE' OR state = 'TRIGGERED' OR state = 'CLOSED' THEN 1 ELSE 0 END) as valid_cnt,
                       SUM(CASE WHEN state = 'REJECTED' THEN 1 ELSE 0 END) as rej_cnt
                FROM signals
                GROUP BY chat_id
            """)
            rows = c.fetchall()
            for r in rows:
                print(f"  Chat {r['chat_id']}: total={r['cnt']}, valid={r['valid_cnt']}, rejected={r['rej_cnt']}")
        except Exception as e:
            print("  Signals error:", e)
            
        try:
            c.execute("SELECT COUNT(*) FROM messages")
            print("  Total messages:", c.fetchone()[0])
        except Exception as e:
            print("  Messages error:", e)
            
        conn.close()
    else:
        print(f"Not found: {p}")

