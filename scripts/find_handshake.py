import os

for root_dir in [
    r'e:\TOOL DUNG CODE\bottradecrypto',
    r'C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor',
    r'C:\Users\PC Gaming\AppData\Local\telegram-binance-signal-executor',
    r'C:\Users\PC Gaming\AppData\Local\com.bottradecrypto.executor',
]:
    if os.path.exists(root_dir):
        for root, dirs, files in os.walk(root_dir):
            for file in files:
                if 'handshake' in file.lower() or file.endswith('.json'):
                    print(os.path.join(root, file))

