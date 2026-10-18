import subprocess, time, os

cmd = [
    r'desktop\src-tauri\target\release\backend-x86_64-pc-windows-msvc.exe',
    '--data-dir', r'C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor',
    '--config', r'C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\config.yaml'
]

proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
for i in range(10):
    time.sleep(1)
    if proc.poll() is not None:
        print("Backend exited early with code:", proc.returncode)
        out, err = proc.communicate()
        print("STDOUT:\n", out)
        print("STDERR:\n", err)
        break
    # Check if handshake file exists anywhere
    for check_dir in [
        r'C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor',
        r'C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\data',
        r'e:\TOOL DUNG CODE\bottradecrypto',
        r'e:\TOOL DUNG CODE\bottradecrypto\data',
    ]:
        hs = os.path.join(check_dir, 'backend_handshake.json')
        if os.path.exists(hs):
            print(f"FOUND handshake at: {hs} (mtime: {os.path.getmtime(hs)})")
            with open(hs, 'r') as f:
                print("CONTENT:", f.read())
            proc.terminate()
            exit(0)
    print(f"Waiting {i+1}s...")

proc.terminate()

