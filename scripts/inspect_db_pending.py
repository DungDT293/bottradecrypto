import sqlite3
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

db_paths = [
    './data/trading_state.db',
    os.path.expandvars('%APPDATA%/telegram_binance_signal_executor/data/trading_state.db'),
    'bot_storage.db'
]

for db_path in db_paths:
    if os.path.exists(db_path):
        print(f"=== DB: {db_path} ===")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        try:
            cur.execute("SELECT signal_id, symbol, side, state, entries_json, stop_loss, take_profits_json, blocking_reason FROM signals WHERE symbol LIKE '%BTW%' OR symbol LIKE '%SKY%' ORDER BY created_at DESC LIMIT 5")
            print("--- SIGNALS ---")
            for r in cur.fetchall():
                print(f"Signal ID: {r[0]}, Sym: {r[1]}, Side: {r[2]}, State: {r[3]}, Entries: {r[4]}, SL: {r[5]}, TPs: {r[6]}, Block: {r[7]}")
            
            cur.execute("SELECT client_order_id, symbol, side, order_type, price, quantity, status, exchange_order_id FROM orders WHERE symbol LIKE '%BTW%' OR symbol LIKE '%SKY%' ORDER BY created_at DESC LIMIT 5")
            print("--- ORDERS ---")
            for r in cur.fetchall():
                print(f"Order: {r}")
        except Exception as e:
            print('Err:', e)
        conn.close()

