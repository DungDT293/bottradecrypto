import sqlite3

db_ws = r'e:\TOOL DUNG CODE\bottradecrypto\data\trading_state.db'
db_app = r'C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\data\trading_state.db'

conn_ws = sqlite3.connect(db_ws)
conn_app = sqlite3.connect(db_app)

tables_ws = [r[0] for r in conn_ws.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
tables_app = [r[0] for r in conn_app.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

print('WS tables:', tables_ws)
print('App tables:', tables_app)

for t in sorted(set(tables_ws + tables_app)):
    c_ws = conn_ws.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] if t in tables_ws else 'N/A'
    c_app = conn_app.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] if t in tables_app else 'N/A'
    print(f"  {t:25s} | WS: {str(c_ws):8s} | App: {str(c_app):8s}")

conn_ws.close()
conn_app.close()

