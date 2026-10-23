import sqlite3
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

for db_path in ['data/trading_state.db', r'C:\Users\PC Gaming\AppData\Local\telegram-binance-signal-executor\data\trading_state.db']:
    print(f"\n=== DB: {db_path} ===")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT signal_id, symbol, side, state, stop_loss, leverage, created_at FROM signals WHERE state IN ('OPEN_PROTECTED', 'ENTRY_PENDING')")
    rows = c.fetchall()
    print(f"Active signals count: {len(rows)}")
    for r in rows:
        print(f"  Signal: {r[0]} | {r[1]} {r[2]} | State: {r[3]} | SL: {r[4]} | Lev: {r[5]}x")
        c.execute("SELECT client_order_id, order_type, side, price, trigger_price, quantity, is_reduce_only, is_algo, status FROM orders WHERE signal_id=?", (r[0],))
        ords = c.fetchall()
        print(f"    Orders count: {len(ords)}")
        for o in ords:
            print(f"      {o[0]} | {o[1]} {o[2]} | Px={o[3]} | Trig={o[4]} | Qty={o[5]} | ReduceOnly={o[6]} | Status={o[8]}")
    conn.close()

print("\n=== SKYAI SIGNALS ===")
for db_path in ['data/trading_state.db', r'C:\Users\PC Gaming\AppData\Local\telegram-binance-signal-executor\data\trading_state.db']:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT signal_id, symbol, side, state, stop_loss, created_at FROM signals WHERE symbol='SKYAIUSDT'")
    print(db_path, c.fetchall())
    conn.close()

