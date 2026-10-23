import sqlite3
import os
import sys
import json
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')

db_path = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

CHANNEL_NAMES = {
    -1002052872813: "CRYPTO LEOPARD'S 🐆",
    -1002007658025: "THE WOLF 🐺",
    -1001756316676: "Boom_Boom_Billionaires 💥",
    -1001754095061: "Crypto Radar 📡",
    -1001552004524: "VIP Signals / Channel 5",
    -1001370457350: "Crypto Neon 💎",
}

cur.execute('''
    SELECT m.chat_id, m.message_id, m.telegram_timestamp, m.received_at, m.raw_text,
           s.signal_id, s.symbol, s.side, s.state, s.entries_json, s.stop_loss, s.take_profits_json, s.blocking_reason
    FROM messages m
    LEFT JOIN signals s ON m.chat_id = s.chat_id AND m.message_id = s.message_id
    WHERE m.telegram_timestamp >= '2026-10-21T11:00:00'
    ORDER BY m.telegram_timestamp ASC
''')
rows = cur.fetchall()

print(f"================================================================================")
print(f"TỔNG HỢP TOÀN BỘ TIN NHẮN TỐI NAY (Từ 18:00 đến {datetime.now().strftime('%H:%M:%S')} ngày 21/10/2026)")
print(f"Tổng số tin nhắn: {len(rows)}")
print(f"================================================================================\n")

for idx, r in enumerate(rows, 1):
    chat_id, msg_id, tele_time, rec_time, raw_text, sig_id, symbol, side, state, entries, sl, tps, block_reason = r
    ch_name = CHANNEL_NAMES.get(chat_id, f"Channel {chat_id}")
    
    # Parse timestamp to Vietnam time (UTC+7)
    try:
        clean_time = tele_time.split('+')[0].replace('Z', '')
        dt_utc = datetime.fromisoformat(clean_time)
        dt_ict = dt_utc + timedelta(hours=7)
        time_str = dt_ict.strftime('%H:%M:%S %d/%m/%Y')
    except Exception:
        time_str = str(tele_time)

    print(f"[{idx}] {ch_name} | Msg ID: {msg_id} | Giờ VN: {time_str}")
    if symbol:
        print(f"   🎯 TÍN HIỆU: {symbol} ({side}) | Trạng thái: {state}")
        if entries: print(f"      - Entry: {entries}")
        if sl: print(f"      - Stop Loss: {sl}")
        if tps: print(f"      - Take Profits: {tps}")
        if block_reason: print(f"      - Lý do chặn/chú thích: {block_reason}")
    else:
        print(f"   💬 TIN NHẮN CHAT / THÔNG BÁO / ADMIN:")
    
    # Print content snippet or full text
    content = raw_text.strip()
    lines = content.splitlines()
    for l in lines:
        print(f"      | {l}")
    print("-" * 80)

conn.close()

