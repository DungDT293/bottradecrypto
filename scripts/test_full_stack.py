import subprocess, time, os, urllib.request, json

app_path = r'C:\Users\PC Gaming\AppData\Local\telegram-binance-signal-executor\app.exe'
work_dir = r'C:\Users\PC Gaming\AppData\Local\telegram-binance-signal-executor'

print("Starting app with stdout/stderr to files...")
log_out = open(os.path.join(work_dir, 'tauri_stdout.log'), 'w', encoding='utf-8')
log_err = open(os.path.join(work_dir, 'tauri_stderr.log'), 'w', encoding='utf-8')

proc = subprocess.Popen(
    [app_path],
    cwd=work_dir,
    stdout=log_out,
    stderr=log_err,
)

print(f"App spawned with PID {proc.pid}. Waiting for backend to bind and write handshake...")

handshake_path = r'C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\backend_handshake.json'

ready = False
for i in range(25):
    time.sleep(1)
    if proc.poll() is not None:
        print(f"App exited early with code {proc.returncode}!")
        break
    if os.path.exists(handshake_path):
        try:
            with open(handshake_path, 'r', encoding='utf-8') as f:
                hs = json.load(f)
            if hs.get('status') == 'READY':
                print(f"Backend READY! Port: {hs['port']}, token: {hs['session_token'][:8]}...")
                ready = True
                port = hs['port']
                token = hs['session_token']
                
                # Query leaderboard
                url = f"http://127.0.0.1:{port}/channels/leaderboard?timeframe=all"
                req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "X-Session-Token": token})
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    print("\n=== LEADERBOARD API VERIFIED ===")
                    print("Bankroll:", data.get('bankroll_usd'))
                    print("Margin pct:", data.get('margin_per_trade_pct'))
                    print("Summary:", data.get('summary'))
                    for ch in data.get('channels', []):
                        p = ch['performance']
                        c_name = ch['channel_name'].encode('ascii', 'ignore').decode('ascii')
                        print(f"  #{ch['rank']} {c_name:25s} | Valid: {ch['validated_signals']:3d}/{ch['total_signals']:3d} | Rej: {ch['rejected_signals']:3d} | WinRate: {p['win_rate_pct']}% | PnL: ${p['net_pnl_usd']:.2f}")
                break
        except Exception as e:
            print("Check err:", e)
    print(f"Waiting... {i+1}s")

if not ready and proc.poll() is None:
    print("Handshake was not ready within 25s, terminating...")
    proc.terminate()
