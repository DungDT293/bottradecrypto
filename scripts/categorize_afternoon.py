import sqlite3
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

db_path = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db')
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("""
    SELECT s.signal_id, s.chat_id, s.message_id, s.symbol, s.side, s.state, s.blocking_reason, s.created_at,
           m.raw_text, s.entries_json, s.stop_loss, s.take_profits_json
    FROM signals s
    LEFT JOIN messages m ON s.message_id = m.message_id AND s.chat_id = m.chat_id
    WHERE s.created_at >= '2026-10-20T05:00:00'
    ORDER BY s.created_at ASC
""")
rows = c.fetchall()

print(f"Total signals received between 12:00 PM and 15:00 PM VN: {len(rows)}\n")

categories = {
    "PROFIT_BOASTING": [],  # Tin khoe lãi / báo cắn TP
    "VIP_PROMO": [],        # Tin quảng cáo VIP, không có entry/sl
    "TOUCHED_TP1": [],      # Kèo gửi trễ, giá thị trường đã bay qua TP1
    "OUTSIDE_ENTRY": [],    # Giá thị trường giảm/tăng quá xa vùng entry
    "VALID_ACCEPTED": [],   # Kèo hợp lệ được duyệt
    "OTHER": []
}

for r in rows:
    sig_id, chat_id, msg_id, sym, side, state, reason, created_at, raw_text, entries, sl, tps = r
    raw_text_clean = (raw_text or "").strip()
    reason_clean = reason or "None"
    
    if "Take-Profit target" in raw_text_clean or "All targets achieved" in raw_text_clean or "Reached" in raw_text_clean or "Profit:" in raw_text_clean:
        categories["PROFIT_BOASTING"].append((sym, chat_id, created_at, raw_text_clean[:70]))
    elif "Join Fast" in raw_text_clean or "CONTACT ADMIN" in raw_text_clean or "Khong co muc gia entry" in reason_clean:
        categories["VIP_PROMO"].append((sym, chat_id, created_at, raw_text_clean[:70]))
    elif "đã chạm TP1" in reason_clean or "đã đạt/thấp hơn TP1" in reason_clean:
        categories["TOUCHED_TP1"].append((sym, side, created_at, reason_clean))
    elif "quá" in reason_clean or "xa" in reason_clean:
        categories["OUTSIDE_ENTRY"].append((sym, side, created_at, reason_clean))
    elif state in ["VALIDATED", "OPEN_PROTECTED", "ACTIVE"]:
        categories["VALID_ACCEPTED"].append((sym, side, created_at, state))
    else:
        categories["OTHER"].append((sym, side, created_at, reason_clean, raw_text_clean[:70]))

print(f"1. Tin khoe lãi / báo cắn TP: {len(categories['PROFIT_BOASTING'])}")
for x in categories["PROFIT_BOASTING"][:5]:
    print(f"   - {x[0]} ({x[2]}): {x[3]}")

print(f"\n2. Tin quảng cáo VIP / mồi chài (không có setup): {len(categories['VIP_PROMO'])}")
for x in categories["VIP_PROMO"][:5]:
    print(f"   - {x[0]} ({x[2]}): {x[3]}")

print(f"\n3. Kèo thật NHƯNG gửi trễ (giá đã cắn TP1 trước khi bot nhận được): {len(categories['TOUCHED_TP1'])}")
for x in categories["TOUCHED_TP1"]:
    print(f"   - {x[0]} {x[1]} ({x[2]}): {x[3]}")

print(f"\n4. Kèo thật nhưng giá ngoài vùng Entry: {len(categories['OUTSIDE_ENTRY'])}")
for x in categories["OUTSIDE_ENTRY"]:
    print(f"   - {x[0]} {x[1]} ({x[2]}): {x[3]}")

print(f"\n5. Kèo hợp lệ: {len(categories['VALID_ACCEPTED'])}")
for x in categories["VALID_ACCEPTED"]:
    print(f"   - {x[0]} {x[1]} ({x[2]}): {x[3]}")

print(f"\n6. Các tin khác: {len(categories['OTHER'])}")
for x in categories["OTHER"][:5]:
    print(f"   - {x[0]} {x[1]} ({x[2]}): Reason: {x[3]} | Text: {x[4]}")

conn.close()

