import sqlite3

for db_path in ['data/trading_state.db', 'C:/Users/PC Gaming/AppData/Local/telegram-binance-signal-executor/data/trading_state.db']:
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            UPDATE signals
            SET state = 'CLOSED', blocking_reason = 'Hết hạn lịch sử > 24h'
            WHERE state NOT IN ('CLOSED', 'REJECTED')
            AND created_at < datetime('now', '-1 day')
            AND symbol != 'SKYAIUSDT'
        """)
        updated = cur.rowcount
        conn.commit()
        print(f"{db_path}: Closed {updated} stale historical signals.")
    except Exception as e:
        print(f"Error {db_path}: {e}")

