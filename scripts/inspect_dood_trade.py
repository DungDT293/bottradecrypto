import sqlite3
import os
import sys
import json
import urllib.request
import hmac
import hashlib
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

db_path = os.path.expandvars(r"%APPDATA%\telegram_binance_signal_executor\data\trading_state.db")
print(f"Reading DB: {db_path}\n")

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# 1. Timeline
c.execute("SELECT * FROM signal_timeline WHERE signal_id LIKE '%76471%' ORDER BY id ASC")
timeline = c.fetchall()
print(f"--- TIMELINE ({len(timeline)}) ---")
for t in timeline:
    print(dict(t))
print()

# 2. Orders in DB
c.execute("SELECT * FROM orders WHERE symbol = 'DOODUSDT' ORDER BY created_at ASC")
orders = c.fetchall()
print(f"--- ORDERS IN DB ({len(orders)}) ---")
for o in orders:
    print(dict(o))
print()

# 3. Check Binance user trades for DOODUSDT directly using Binance Futures API
env_path = os.path.expandvars(r"%APPDATA%\telegram_binance_signal_executor\.env")
live_key = None
live_secret = None
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("BINANCE_LIVE_API_KEY="):
                live_key = line.strip().split("=", 1)[1].strip()
            elif line.startswith("BINANCE_LIVE_API_SECRET="):
                live_secret = line.strip().split("=", 1)[1].strip()

if not live_key and os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("BINANCE_LIVE_API_KEY="):
                live_key = line.strip().split("=", 1)[1].strip()
            elif line.startswith("BINANCE_LIVE_API_SECRET="):
                live_secret = line.strip().split("=", 1)[1].strip()

print(f"Has Binance Live Key: {bool(live_key)}")

if live_key and live_secret:
    print("\n--- QUERYING BINANCE FUTURES FOR DOODUSDT ---")
    base_url = "https://fapi.binance.com"
    
    # 1. User Trades (all executed fills for DOODUSDT)
    timestamp = int(time.time() * 1000)
    query = f"symbol=DOODUSDT&timestamp={timestamp}"
    sig = hmac.new(live_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"{base_url}/fapi/v1/userTrades?{query}&signature={sig}"
    
    req = urllib.request.Request(url, headers={"X-MBX-APIKEY": live_key})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            trades = json.loads(resp.read().decode("utf-8"))
        print(f"Binance userTrades count: {len(trades)}")
        total_pnl = 0.0
        for tr in trades:
            pnl = float(tr.get('realizedPnl', 0))
            total_pnl += pnl
            trade_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(tr.get('time') / 1000))
            print(f"  [{trade_time}] ID: {tr.get('id')} | OrderID: {tr.get('orderId')} | Side: {tr.get('side')} | Price: {tr.get('price')} | Qty: {tr.get('qty')} | RealizedPnL: {tr.get('realizedPnl')} USDT | Commission: {tr.get('commission')} {tr.get('commissionAsset')}")
        print(f"===> TOTAL REALIZED PnL: {total_pnl:+.6f} USDT")
    except Exception as e:
        print("Error fetching userTrades:", e)

    # 2. All Orders on Binance (including canceled/filled)
    timestamp = int(time.time() * 1000)
    query = f"symbol=DOODUSDT&timestamp={timestamp}"
    sig = hmac.new(live_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"{base_url}/fapi/v1/allOrders?{query}&signature={sig}"
    
    req = urllib.request.Request(url, headers={"X-MBX-APIKEY": live_key})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            all_orders = json.loads(resp.read().decode("utf-8"))
        print(f"\nBinance allOrders count: {len(all_orders)}")
        for ao in all_orders:
            order_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ao.get('time') / 1000))
            print(f"  [{order_time}] OrderID: {ao.get('orderId')} | ClientID: {ao.get('clientOrderId')} | Type: {ao.get('type')} | Side: {ao.get('side')} | Px: {ao.get('price')} | StopPx: {ao.get('stopPrice')} | OrigQty: {ao.get('origQty')} | ExecQty: {ao.get('executedQty')} | Status: {ao.get('status')}")
    except Exception as e:
        print("Error fetching allOrders:", e)

