import os
import subprocess
import sys

backend_exe = os.path.expandvars(r"%LOCALAPPDATA%\telegram-binance-signal-executor\backend-x86_64-pc-windows-msvc.exe")
data_dir = os.path.expandvars(r"%APPDATA%\telegram_binance_signal_executor")
config_path = os.path.join(data_dir, "config.yaml")

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

proc = subprocess.Popen(
    [backend_exe, "--data-dir", data_dir, "--config", config_path],
    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
    close_fds=True
)

print(f"Spawned backend daemon PID: {proc.pid}")

