import os
import sys
import yaml
from datetime import datetime
from binance.client import Client

sys.stdout.reconfigure(encoding='utf-8')
config_path = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\config.yaml')
with open(config_path, 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)

bcfg = cfg.get('binance', {})
client = Client(bcfg['api_key'], bcfg['api_secret'])

print("=== DASH USER TRADES ===")
trades = client.futures_account_trades(symbol='DASHUSDT', limit=20)
for t in trades:
    dt = datetime.fromtimestamp(t['time'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
    print(f"Time: {dt} | OrderId: {t['orderId']} | Side: {t['side']} | Price: {t['price']} | Qty: {t['qty']} | RealizedPnL: {t['realizedPnl']} USDT | Fee: {t['commission']}")

print("\n=== DASH LIVE OPEN ORDERS ===")
open_orders = client.futures_get_open_orders(symbol='DASHUSDT')
for o in open_orders:
    print(f"OrderId: {o['orderId']} | Type: {o['type']} | Side: {o['side']} | OrigQty: {o['origQty']} | Price: {o['price']} | StopPrice: {o['stopPrice']} | Status: {o['status']}")

print("\n=== DASH LIVE POSITION ===")
positions = client.futures_position_information(symbol='DASHUSDT')
for p in positions:
    amt = float(p['positionAmt'])
    if amt != 0:
        print(f"Symbol: {p['symbol']} | Amt: {p['positionAmt']} | EntryPrice: {p['entryPrice']} | MarkPrice: {p['markPrice']} | UnPnl: {p['unRealizedProfit']} | Lev: {p['leverage']}x | Margin: {float(p['initialMargin']):.4f} USDT | LiqPrice: {p['liquidationPrice']}")

