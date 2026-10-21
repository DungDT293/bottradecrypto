import urllib.request, time, hmac, hashlib, json, os, yaml, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('config.yaml', 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)

api_key = cfg['binance']['api_key']
api_secret = cfg['binance']['api_secret']

def sign(params):
    query = '&'.join([f'{k}={v}' for k, v in sorted(params.items())])
    sig = hmac.new(api_secret.encode('utf-8'), query.encode('utf-8'), hashlib.sha256).hexdigest()
    return f'{query}&signature={sig}'

server_time = json.loads(urllib.request.urlopen('https://fapi.binance.com/fapi/v1/time').read())['serverTime']

for sym in ['METISUSDT', 'WLDUSDT', 'CTRUSDT', 'XRPUSDT']:
    params = {'symbol': sym, 'timestamp': server_time, 'recvWindow': 10000}
    signed_url = 'https://fapi.binance.com/fapi/v1/userTrades?' + sign(params)
    req = urllib.request.Request(signed_url, headers={'X-MBX-APIKEY': api_key, 'User-Agent': 'Mozilla/5.0'})
    try:
        trades = json.loads(urllib.request.urlopen(req).read().decode('utf-8'))
        print('=== TRADES FOR ' + sym + ' ===')
        for t in trades[-8:]:
            dt = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t['time']/1000))
            print(f"  [{dt}] Side={t['side']} Qty={t['qty']} Price={t['price']} RealizedPnL={t['realizedPnl']} Fee={t['commission']}")
    except Exception as e:
        print('Error ' + sym + ': ' + str(e))
