import os
import subprocess
import sys

backend_exe = os.path.expandvars(r"%LOCALAPPDATA%\telegram-binance-signal-executor\backend-x86_64-pc-windows-msvc.exe")
data_dir = os.path.expandvars(r"%APPDATA%\telegram_binance_signal_executor")
config_path = os.path.join(data_dir, "config.yaml")

print(f"Starting backend: {backend_exe}")
print(f"Data dir: {data_dir}")
print(f"Config: {config_path}")

cmd = [backend_exe, "--data-dir", data_dir, "--config", config_path]
proc = subprocess.Popen(cmd)
print(f"Backend started with PID: {proc.pid}")

