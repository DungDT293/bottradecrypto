import subprocess, os

app_path = r'C:\Users\PC Gaming\AppData\Local\telegram-binance-signal-executor\app.exe'
work_dir = r'C:\Users\PC Gaming\AppData\Local\telegram-binance-signal-executor'

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

print("Launching detached app.exe...")
proc = subprocess.Popen(
    [app_path],
    cwd=work_dir,
    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
    close_fds=True
)
print("Spawned PID:", proc.pid)

