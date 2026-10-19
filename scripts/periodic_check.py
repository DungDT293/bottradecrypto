import json, urllib.request

handshake_path = r'C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\backend_handshake.json'
with open(handshake_path, 'r', encoding='utf-8') as f:
    hs = json.load(f)

port, token = hs['port'], hs['session_token']
headers = {'Authorization': f'Bearer {token}', 'X-Session-Token': token}

h = json.loads(urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}/health', headers=headers)).read())
s = json.loads(urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}/snapshot', headers=headers)).read())

acc = s.get('account', {})
print('=== HEALTH STATUS ===')
print('System status:', h.get('status'))
print(f"Equity: {acc.get('equity')} USDT")
print(f"Open Positions Count: {acc.get('open_positions_count')}")
for p in s.get('positions', []):
    print(f"  Pos: {p.get('symbol')} | Side: {p.get('side')} | Entry: {p.get('entry_price')} | Mark: {p.get('mark_price')} | UnPnl: {p.get('unrealized_pnl')}")
print(f"Active Orders: {len(s.get('orders', []))}")
print(f"Messages Processed: {s.get('telemetry', {}).get('messages_processed')}")

