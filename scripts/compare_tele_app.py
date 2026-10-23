import sqlite3
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
db_path = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

query = '''
    SELECT 
        s.signal_id, s.chat_id, s.message_id, s.symbol, s.side, s.state, 
        s.entry_mode, s.entries_json, s.stop_loss, s.take_profits_json, 
        s.leverage, s.blocking_reason, s.created_at,
        m.telegram_timestamp, m.raw_text
    FROM signals s
    LEFT JOIN messages m ON s.chat_id = m.chat_id AND s.message_id = m.message_id
    ORDER BY COALESCE(m.telegram_timestamp, s.created_at) DESC
    LIMIT 20
'''
cur.execute(query)
rows = cur.fetchall()

channel_map = {
    -1002007658025: 'THE WOLF (CRYPTO)®',
    -1002052872813: "CRYPTO LEOPARD'S",
    -1001552004524: 'CRYPTO MONK',
    -1001756316676: 'Boom_Boom_Billionaires',
    -1001754095061: 'CRYPTO NEON'
}

print(f'TOTAL FETCHED: {len(rows)}')
for i, r in enumerate(rows, 1):
    cname = channel_map.get(r[1], str(r[1]))
    print(f'================================================================================')
    print(f'STT {i}: [{r[13]}] | {cname} | {r[3]} {r[4]} | Trang thai: {r[5]}')
    print(f'  - Signal ID: {r[0]} | Chat: {r[1]} | Msg ID: {r[2]}')
    print(f'  - Ly do: {r[11]}')
    print(f'  - Data trong App: Entry={r[7]} | SL={r[8]} | TP={r[9]} | Lev={r[10]}')
    print(f'  - TIN GOC TREN TELEGRAM:\n{r[14]}')

