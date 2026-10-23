import sqlite3
import os
import sys
import time
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
db_path = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db')

print(f"[{datetime.now().strftime('%H:%M:%S')}] KHOI DONG WATCHER GIAM SAT TIN HIEU TELEGRAM", flush=True)
print("CHẾ ĐỘ: Đọc trực tiếp SQLite nội bộ (Zero API Network Call - 100% Không vi phạm Telegram Limit)", flush=True)

conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("SELECT max(received_at) FROM messages")
last_msg_time = c.fetchone()[0] or ""

c.execute("SELECT max(created_at) FROM signals")
last_sig_time = c.fetchone()[0] or ""

print(f"- Mốc tin nhắn ban đầu: {last_msg_time}", flush=True)
print(f"- Mốc tín hiệu ban đầu: {last_sig_time}", flush=True)
print("="*60, flush=True)
print("ĐANG THEO DÕI... (Sẽ hiển thị ngay khi có tin nhắn hoặc tín hiệu mới)", flush=True)

while True:
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        # Check new messages
        if last_msg_time:
            c.execute("SELECT chat_id, message_id, telegram_timestamp, received_at, raw_text FROM messages WHERE received_at > ? ORDER BY received_at ASC", (last_msg_time,))
        else:
            c.execute("SELECT chat_id, message_id, telegram_timestamp, received_at, raw_text FROM messages ORDER BY received_at DESC LIMIT 1")
            
        new_msgs = c.fetchall()
        for m in new_msgs:
            last_msg_time = m[3]
            now_str = datetime.now().strftime('%H:%M:%S')
            print(f"\n[{now_str}] 📩 TIN NHẮN TELEGRAM MỚI TỚI!", flush=True)
            print(f"- Chat ID: {m[0]} | Msg ID: {m[1]} | TeleTime: {m[2]}", flush=True)
            snippet = m[4].strip()
            print(f"- Nội dung:\n{snippet[:400]}", flush=True)
            print("-" * 50, flush=True)
            
        # Check new signals
        if last_sig_time:
            c.execute("SELECT signal_id, symbol, side, state, entries_json, stop_loss, blocking_reason, created_at FROM signals WHERE created_at > ? ORDER BY created_at ASC", (last_sig_time,))
        else:
            c.execute("SELECT signal_id, symbol, side, state, entries_json, stop_loss, blocking_reason, created_at FROM signals ORDER BY created_at DESC LIMIT 1")
            
        new_sigs = c.fetchall()
        for s in new_sigs:
            last_sig_time = s[7]
            now_str = datetime.now().strftime('%H:%M:%S')
            print(f"\n[{now_str}] 🎯 PHÁT HIỆN TÍN HIỆU GIAO DỊCH MỚI!", flush=True)
            print(f"- Signal ID: {s[0]}", flush=True)
            print(f"- Cặp coin: {s[1]} | Hướng: {s[2]}", flush=True)
            print(f"- Trạng thái xử lý của App: {s[3]}", flush=True)
            print(f"- Vùng Entry: {s[4]} | Stop Loss: {s[5]}", flush=True)
            if s[6]:
                print(f"- Lý do chặn / Ghi chú: {s[6]}", flush=True)
            else:
                print(f"- Kết quả: HỢP LỆ VÀ ĐÃ BẮN LỆNH LÊN SÀN THÀNH CÔNG!", flush=True)
            print("=" * 60, flush=True)
            
        conn.close()
        time.sleep(3)
    except Exception as e:
        time.sleep(3)

