import urllib.request, json, sys
sys.stdout.reconfigure(encoding='utf-8')

token = 'jjS9pD8UZCCiVlje0ACvP0wvbq1O1nibZp7pNPAGgPU'
req = urllib.request.Request('http://127.0.0.1:61786/api/trading/trades?limit=10', headers={'x-session-token': token})
res = urllib.request.urlopen(req)
trades = json.loads(res.read().decode())
print(f'Returned Trades ({len(trades)}):')
for t in trades[:5]:
    print(f"  {t['symbol']}: {t['side']} {t['qty']} @ {t['price']} | {t['time']} | {t['channel_name']}")

req2 = urllib.request.Request('http://127.0.0.1:61786/api/trading/positions', headers={'x-session-token': token})
res2 = urllib.request.urlopen(req2)
positions = json.loads(res2.read().decode())
print(f'Returned Positions ({len(positions)}):')
for p in positions:
    print(f"  {p['symbol']}: {p['side']} {p['amount']} coins | Margin: {p.get('initial_margin')} USDT | Notional: {p.get('notional')} USDT")

