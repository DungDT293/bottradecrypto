import sqlite3

conn = sqlite3.connect(r'e:\TOOL DUNG CODE\bottradecrypto\data\trading_state.db')
rows = conn.execute("SELECT signal_id, symbol, side, state, blocking_reason, created_at FROM signals WHERE state IN ('NEEDS_REVIEW', 'NEEDS_POLICY')").fetchall()
print(f"Needs review signals count: {len(rows)}")
for r in rows:
    print(" ", r)
conn.close()

