import json, os, urllib.request

handshake_path = r'C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\backend_handshake.json'
if not os.path.exists(handshake_path):
    handshake_path = r'C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\data\backend_handshake.json'

print("Using handshake path:", handshake_path)
with open(handshake_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

print("Handshake data:", data)
port = data['port']
token = data['session_token']

# Query leaderboard API
url = f"http://127.0.0.1:{port}/channels/leaderboard?timeframe=all"
req = urllib.request.Request(
    url,
    headers={"Authorization": f"Bearer {token}", "X-Session-Token": token}
)

try:
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode('utf-8'))
        print("\n=== SUCCESS: Leaderboard API Response ===")
        print("Bankroll USD:", res.get('bankroll_usd'))
        print("Margin per trade pct:", res.get('margin_per_trade_pct'))
        print("Margin per trade usd:", res.get('margin_per_trade_usd'))
        print("Summary:", res.get('summary'))
        print("\nRankings:")
        for ch in res.get('channels', []):
            perf = ch['performance']
            clean_name = ch['channel_name'].encode('ascii', 'ignore').decode('ascii')
            print(f"  #{ch['rank']} {clean_name:25s} | Tier {ch['tier']} | Valid: {ch['validated_signals']:3d}/{ch['total_signals']:3d} | Winrate: {perf['win_rate_pct']:5.1f}% | PnL: ${perf['net_pnl_usd']:6.2f} (ROI: {perf['roi_pct']:5.1f}%)")
except Exception as e:
    print("API Error:", e)

# Also test /snapshot to check real equity
req_snap = urllib.request.Request(
    f"http://127.0.0.1:{port}/snapshot",
    headers={"Authorization": f"Bearer {token}", "X-Session-Token": token}
)
try:
    with urllib.request.urlopen(req_snap) as resp:
        snap = json.loads(resp.read().decode('utf-8'))
        acc = snap.get('account', {})
        print("\n=== Snapshot Account Info ===")
        print("Connected:", acc.get('connected'))
        print("Equity:", acc.get('equity'))
        print("Total margin balance:", acc.get('total_margin_balance'))
        print("Wallet balance:", acc.get('wallet_balance'))
        print("Open positions:", acc.get('open_positions_count'))
except Exception as e:
    print("Snapshot Error:", e)
