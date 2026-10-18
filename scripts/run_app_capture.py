import subprocess, time

app_path = r'C:\Users\PC Gaming\AppData\Local\telegram-binance-signal-executor\app.exe'
work_dir = r'C:\Users\PC Gaming\AppData\Local\telegram-binance-signal-executor'

print(f"Launching {app_path}...")
proc = subprocess.Popen(
    [app_path],
    cwd=work_dir,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

for i in range(12):
    time.sleep(1)
    ret = proc.poll()
    if ret is not None:
        print(f"Process exited at second {i+1} with code: {ret}")
        out, err = proc.communicate()
        print("STDOUT:\n", out)
        print("STDERR:\n", err)
        break
    print(f"Second {i+1}: still running (PID {proc.pid})")
else:
    print("Process still running happily after 12 seconds!")

