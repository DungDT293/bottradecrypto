import sqlite3
import os

top5 = (-1002052872813, -1001756316676, -1001370457350, -1002007658025, -1001552004524)
paths = [
    r"data/trading_state.db",
    os.path.expandvars(r"%APPDATA%\telegram_binance_signal_executor\data\trading_state.db"),
    os.path.expandvars(r"%APPDATA%\telegram_binance_signal_executor\trading_state.db"),
]

for p in paths:
    if not os.path.exists(p):
        continue
    try:
        conn = sqlite3.connect(p)
        c = conn.cursor()
        
        # 1. Delete signals from non-Top5 channels
        c.execute("DELETE FROM signals WHERE chat_id NOT IN (?,?,?,?,?)", top5)
        del_sigs = c.rowcount
        
        # 2. Delete messages from non-Top5 channels
        c.execute("DELETE FROM messages WHERE chat_id NOT IN (?,?,?,?,?)", top5)
        del_msgs = c.rowcount
        
        # 3. In signals, delete ancient REJECTED signals from Top 5 that are older than 3 days
        c.execute("DELETE FROM signals WHERE state = 'REJECTED' AND created_at < datetime('now', '-3 days')")
        del_old_rej = c.rowcount
        
        conn.commit()
        conn.close()
        print(f"Cleaned {p}: Deleted {del_sigs} junk signals, {del_msgs} junk messages, {del_old_rej} old rejected.")
    except Exception as e:
        print(f"Error cleaning {p}: {e}")

