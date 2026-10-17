import json
import os
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
db_path = os.path.join(PROJECT_ROOT, "data", "trading_state.db")
conn = sqlite3.connect(db_path)
c = conn.cursor()

# Channel mapping dict
KNOWN_CHANNELS = {
    -1002266035358: "THE MASTER (CRYPTO)",
    -1002191067035: "Crypto Hunters",
    -1002135058198: "Channel_-1002135058198",
    -1002052872813: "CRYPTO LEOPARD'S",
    -1002007658025: "THE WOLF (CRYPTO)®",
    -1001895315984: "Crypto spider 🕷️ scalper",
    -1001656921849: "ESTR - EAT SLEEP TRADE REPEAT",
    -1001652601224: "Crypto World Updates",
    -1001590450482: "THE CRYPTO TRADER",
    -1001370457350: "Crypto Neon",
    -1001164308989: "KING CRYPTO ️",
    -1001161683441: "Global Crypto Research",
    -1002428467696: "RUSKOL GROUP",
    -1001231377117: "HashSeer 🪂",
    -1002125085599: "TRẠM Crypto | Chat",
    -1002402643856: "TRẠM Trây | Channel",
    -1002118550472: "World Wide Futures",
    -1002116318787: "CRYPTO NEXUS | CNX7S",
    -1002078531832: "Crypto Mermaids",
    -1001969210392: "🌹VIP Rose Signal🍀",
    -1001894873816: "The Crypto World (ᴛᴄᴡ)",
    -1001892730371: "The Crypto Lab™",
    -1001810740411: "Mặt nạ đen ( BM ) | Channel",
    -1001783301467: "Crypto Safe Calls™",
    -1001755199088: "Crypto Heaven®",
    -1001754095061: "Crypto Radar",
    -1001712857185: "TH Capital | Channel",
    -1001669911123: "Green Rock Signal™",
    -1001641060449: "••𝗧𝗵𝗲 𝗕𝗶𝘁𝗰𝗼𝗶𝗻 𝗖𝗮𝗿𝘁𝗲𝗹••",
    -1001552004524: "CRYPTO MONK",
    -1001486981201: "A.R.S. CRYPTO | FOREX™",
    -1001401256688: "Airdrop Mỗi Ngày",
    -1001338293070: "𝗝𝗨𝗦𝗧 𝗣𝗥𝗢𝗙𝗜𝗧 NEVER DO",
    -1001294641953: "Green Trading ™",
}

c.execute("""
    SELECT m.chat_id, COUNT(m.message_id) as total_msgs,
           MIN(m.telegram_timestamp) as min_date,
           MAX(m.telegram_timestamp) as max_date
    FROM messages m
    GROUP BY m.chat_id
    ORDER BY total_msgs DESC
""")
rows = c.fetchall()

total_all_msgs = sum(r[1] for r in rows)

print("=" * 80)
print(f"📊 BÁO CÁO TOÀN DIỆN DỮ LIỆU 3 THÁNG QUA (TỔNG {total_all_msgs} TIN NHẮN TRÊN {len(rows)} KÊNH)")
print("=" * 80)

for cid, count, min_d, max_d in rows:
    title = KNOWN_CHANNELS.get(cid, f"Channel_{cid}")
    c.execute("SELECT COUNT(*) FROM signals WHERE chat_id = ?", (cid,))
    sigs = c.fetchone()[0]
    
    c.execute("SELECT state, COUNT(*) FROM signals WHERE chat_id = ? GROUP BY state", (cid,))
    st_dict = dict(c.fetchall())
    
    c.execute("SELECT event_type, COUNT(*) FROM signal_timeline WHERE payload_json LIKE ? GROUP BY event_type", (f'%"chat_id": {cid}%',))
    updates_dict = dict(c.fetchall())
    total_upd = sum(updates_dict.values())
    
    print(f"📌 {title} (ID: {cid}):")
    print(f"   • Số tin nhắn: {count} tin (Từ {min_d[:10]} đến {max_d[:10]})")
    print(f"   • Tín hiệu: {sigs} (Chờ duyệt: {st_dict.get('NEEDS_POLICY', 0) + st_dict.get('VALIDATED', 0)}, Từ chối/Bẫy: {st_dict.get('REJECTED', 0)}, Cần xem xét: {st_dict.get('NEEDS_REVIEW', 0)})")
    if total_upd > 0:
        print(f"   • Cập nhật admin: {total_upd} (Chốt lời/TP Hit: {updates_dict.get('RESULT_TP_REPORTED', 0)}, Lời bình/VIP: {updates_dict.get('COMMENTARY', 0)})")

print("\n" + "=" * 80)
c.execute("SELECT COUNT(*) FROM signals")
total_sigs = c.fetchone()[0]
c.execute("SELECT state, COUNT(*) FROM signals GROUP BY state")
state_totals = dict(c.fetchall())
c.execute("SELECT COUNT(*) FROM signal_timeline")
timeline_total = c.fetchone()[0]
c.execute("SELECT event_type, COUNT(*) FROM signal_timeline GROUP BY event_type")
event_totals = dict(c.fetchall())

print("TỔNG KẾT TOÀN HỆ THỐNG:")
print(f" - Tổng tin nhắn đã lưu: {total_all_msgs}")
print(f" - Tổng tín hiệu bóc tách: {total_sigs}")
print(f"   + Bị loại bỏ (Anti-VIP bait / lỗi cấu trúc): {state_totals.get('REJECTED', 0)}")
print(f"   + Chờ duyệt chính sách (DCA / Nhiều TP): {state_totals.get('NEEDS_POLICY', 0)}")
print(f"   + Cần xem xét (Needs Review): {state_totals.get('NEEDS_REVIEW', 0)}")
print(f"   + Chuẩn tắc ngay (Validated): {state_totals.get('VALIDATED', 0)}")
print(f" - Tổng cập nhật Admin & Tiến trình: {timeline_total}")
print(f"   + Tin khoe chốt lời (RESULT_TP_REPORTED - Vô hiệu hóa): {event_totals.get('RESULT_TP_REPORTED', 0)}")
print(f"   + Tin mời chào VIP / Bình luận (COMMENTARY - Bỏ qua): {event_totals.get('COMMENTARY', 0)}")
print(f"   + Đóng lệnh một phần (CLOSE_PARTIAL): {event_totals.get('CLOSE_PARTIAL', 0)}")
print("=" * 80)

