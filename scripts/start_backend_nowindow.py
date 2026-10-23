import os
import subprocess
import sys

backend_exe = os.path.expandvars(r"%LOCALAPPDATA%\telegram-binance-signal-executor\backend-x86_64-pc-windows-msvc.exe")
data_dir = os.path.expandvars(r"%APPDATA%\telegram_binance_signal_executor")
config_path = os.path.join(data_dir, "config.yaml")

CREATE_NO_WINDOW = 0x08000000

with open(os.devnull, 'wb') as devnull:
    proc = subprocess.Popen(
        [backend_exe, "--data-dir", data_dir, "--config", config_path],
        creationflags=CREATE_NO_WINDOW,
        stdout=devnull,
        stderr=devnull,
        stdin=devnull
    )
print(f"Spawned backend PID: {proc.pid}")

