import sqlite3
import os

db_ws = r'e:\TOOL DUNG CODE\bottradecrypto\data\trading_state.db'
db_app = r'C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\data\trading_state.db'
db_roam_root = r'C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\trading_state.db'

print("--- Syncing Channels -1001370457350 (Neon) & -1002007658025 (Wolf) from WS to App DB ---")

conn_ws = sqlite3.connect(db_ws)
conn_app = sqlite3.connect(db_app)

# 1. Neon (-1001370457350) and Wolf (-1002007658025)
target_chats = [-1001370457350, -1002007658025]

for chat_id in target_chats:
    print(f"\nProcessing chat_id: {chat_id}")
    
    # Check WS counts
    ws_sig_cnt = conn_ws.execute("SELECT COUNT(*) FROM signals WHERE chat_id = ?", (chat_id,)).fetchone()[0]
    ws_msg_cnt = conn_ws.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?", (chat_id,)).fetchone()[0]
    print(f"  In WS DB: signals={ws_sig_cnt}, messages={ws_msg_cnt}")
    
    # Delete old records in app DB for this chat
    # First get signal_ids to delete from timeline
    app_sig_ids = [r[0] for r in conn_app.execute("SELECT signal_id FROM signals WHERE chat_id = ?", (chat_id,)).fetchall()]
    print(f"  In App DB before: signals={len(app_sig_ids)}")
    
    if app_sig_ids:
        # Delete timeline events for these signals
        placeholders = ','.join('?' for _ in app_sig_ids)
        conn_app.execute(f"DELETE FROM signal_timeline WHERE signal_id IN ({placeholders})", app_sig_ids)
        conn_app.execute("DELETE FROM signals WHERE chat_id = ?", (chat_id,))
    
    conn_app.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
    
    # Copy messages from WS
    ws_msgs = conn_ws.execute("SELECT * FROM messages WHERE chat_id = ?", (chat_id,)).fetchall()
    if ws_msgs:
        cols = [d[0] for d in conn_ws.execute("SELECT * FROM messages WHERE chat_id = ?", (chat_id,)).description]
        col_str = ', '.join(cols)
        val_str = ', '.join('?' for _ in cols)
        conn_app.executemany(f"INSERT OR REPLACE INTO messages ({col_str}) VALUES ({val_str})", ws_msgs)
        print(f"  Copied {len(ws_msgs)} messages")
        
    # Copy signals from WS
    ws_sigs = conn_ws.execute("SELECT * FROM signals WHERE chat_id = ?", (chat_id,)).fetchall()
    if ws_sigs:
        cols = [d[0] for d in conn_ws.execute("SELECT * FROM signals WHERE chat_id = ?", (chat_id,)).description]
        col_str = ', '.join(cols)
        val_str = ', '.join('?' for _ in cols)
        conn_app.executemany(f"INSERT OR REPLACE INTO signals ({col_str}) VALUES ({val_str})", ws_sigs)
        print(f"  Copied {len(ws_sigs)} signals")
        
    # Copy timeline events for these signals
    ws_sig_ids = [r[0] for r in ws_sigs]
    if ws_sig_ids:
        placeholders = ','.join('?' for _ in ws_sig_ids)
        ws_timeline = conn_ws.execute(f"SELECT * FROM signal_timeline WHERE signal_id IN ({placeholders})", ws_sig_ids).fetchall()
        if ws_timeline:
            cols = [d[0] for d in conn_ws.execute(f"SELECT * FROM signal_timeline WHERE signal_id IN ({placeholders})", ws_sig_ids).description]
            col_str = ', '.join(cols)
            val_str = ', '.join('?' for _ in cols)
            conn_app.executemany(f"INSERT OR REPLACE INTO signal_timeline ({col_str}) VALUES ({val_str})", ws_timeline)
            print(f"  Copied {len(ws_timeline)} signal_timeline entries")

conn_app.commit()
print("\nCommitted changes to App DB.")

# Check counts in App DB now
print("\n--- Verification in App DB ---")
for chat_id in target_chats:
    sig_row = conn_app.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN state IN ('ACTIVE','TRIGGERED','CLOSED') THEN 1 ELSE 0 END) as valid,
               SUM(CASE WHEN state = 'REJECTED' THEN 1 ELSE 0 END) as rej
        FROM signals WHERE chat_id = ?
    """, (chat_id,)).fetchone()
    print(f"  Chat {chat_id}: total={sig_row[0]}, valid={sig_row[1]}, rejected={sig_row[2]}")

conn_ws.close()
conn_app.close()

