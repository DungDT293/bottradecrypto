import sqlite3
import json
import urllib.request
import os
import sys
from decimal import Decimal
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding='utf-8')

db = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db')
conn = sqlite3.connect(db)
cur = conn.cursor()

# Get live prices
req = urllib.request.Request("https://fapi.binance.com/fapi/v1/ticker/price", headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req, timeout=10) as resp:
    all_tickers = json.loads(resp.read().decode('utf-8'))
live_prices = {item['symbol']: Decimal(str(item['price'])) for item in all_tickers}

# Query signals joining message_versions on chat_id & message_id
cur.execute("""
    SELECT s.signal_id, s.chat_id, s.message_id, s.symbol, s.side, s.state, s.entries_json, s.stop_loss, s.take_profits_json, s.leverage, s.blocking_reason, s.created_at, m.event_date, m.raw_text
    FROM signals s
    JOIN message_versions m ON s.chat_id = m.chat_id AND s.message_id = m.message_id AND m.version = 1
    WHERE s.side IS NOT NULL 
      AND s.entries_json IS NOT NULL 
      AND s.stop_loss IS NOT NULL
      AND m.event_date >= '2026-10-19 00:00:00'
    ORDER BY m.event_date DESC
""")
rows = cur.fetchall()
print(f"Signals with Telegram timestamp in the last 24-48h (since 2026-10-19): {len(rows)}")

qualifying = []
for r in rows:
    sig_id, chat_id, msg_id, sym, side, state, entries_raw, sl_raw, tps_raw, lev, reason, created_at, ev_date, raw_txt = r
    try:
        entries = [Decimal(str(x)) for x in json.loads(entries_raw)]
    except:
        entries = []
    sl = Decimal(str(sl_raw)) if sl_raw else None
    try:
        tps = [Decimal(str(x)) for x in json.loads(tps_raw)]
    except:
        tps = []
    
    if not entries or not sl or not tps:
        continue

    zone_min = min(entries)
    zone_max = max(entries)
    tp1 = tps[0]
    live_p = live_prices.get(sym)

    can_trade = False
    status = "UNKNOWN"

    if live_p:
        if side == "LONG":
            if live_p >= tp1:
                status = f"ĐÃ CHẠM TP1 ({tp1}) [Live: {live_p}]"
            elif live_p <= sl:
                status = f"ĐÃ THỦNG SL ({sl}) [Live: {live_p}]"
            elif zone_min <= live_p <= zone_max:
                status = f"ĐANG TRONG VÙNG ENTRY [{zone_min} - {zone_max}] (Live: {live_p})"
                can_trade = True
            elif live_p < zone_min:
                disc = (zone_min - live_p) / zone_min * 100
                status = f"DƯỚI VÙNG ENTRY (-{disc:.2f}%) & TRÊN SL (Live: {live_p})"
                can_trade = True
            elif live_p > zone_max:
                drift = (live_p - zone_max) / zone_max * 100
                if drift <= Decimal("1.0"):
                    status = f"SÁT TRẦN ENTRY (+{drift:.2f}% <= 1%) (Live: {live_p})"
                    can_trade = True
                else:
                    status = f"VƯỢT TRẦN ENTRY (+{drift:.2f}%) (Live: {live_p})"
        elif side == "SHORT":
            if live_p <= tp1:
                status = f"ĐÃ CHẠM TP1 ({tp1}) [Live: {live_p}]"
            elif live_p >= sl:
                status = f"ĐÃ VƯỢT SL ({sl}) [Live: {live_p}]"
            elif zone_min <= live_p <= zone_max:
                status = f"ĐANG TRONG VÙNG ENTRY [{zone_min} - {zone_max}] (Live: {live_p})"
                can_trade = True
            elif live_p > zone_max:
                pump = (live_p - zone_max) / zone_max * 100
                status = f"TRÊN VÙNG ENTRY (+{pump:.2f}%) & DƯỚI SL (Live: {live_p})"
                can_trade = True
            elif live_p < zone_min:
                drift = (zone_min - live_p) / zone_min * 100
                if drift <= Decimal("1.0"):
                    status = f"SÁT ĐÁY ENTRY (-{drift:.2f}% <= 1%) (Live: {live_p})"
                    can_trade = True
                else:
                    status = f"GIẢM QUÁ ĐÁY ENTRY (-{drift:.2f}%) (Live: {live_p})"

    qualifying.append({
        'id': sig_id,
        'chat_id': chat_id,
        'msg_id': msg_id,
        'symbol': sym,
        'side': side,
        'state': state,
        'zone_min': zone_min,
        'zone_max': zone_max,
        'sl': sl,
        'tp1': tp1,
        'live_p': live_p,
        'status': status,
        'can_trade': can_trade,
        'ev_date': ev_date,
        'reason': reason
    })

print(f"\n{'TIME (TELEGRAM)':<20} | {'SYMBOL':<9} | {'SIDE':<5} | {'STATE':<10} | {'LIVE P':<10} | {'ENTRY RANGE':<25} | {'STATUS'}")
print("-" * 120)
for q in qualifying:
    z_str = f"[{q['zone_min']} - {q['zone_max']}]"
    lp_str = f"{q['live_p']:.4f}" if q['live_p'] is not None else "N/A"
    t_str = str(q['ev_date'])[:19]
    print(f"{t_str:<20} | {q['symbol']:<9} | {q['side']:<5} | {q['state']:<10} | {lp_str:<10} | {z_str:<25} | {q['status']}")

print("\n" + "="*85)
print("DANH SÁCH KÈO HÔM NAY THỎA MÃN ĐIỀU KIỆN VÀO LỆNH THỰC TẾ:")
active_candidates = [q for q in qualifying if q['can_trade']]
if not active_candidates:
    print("Không có kèo nào thỏa mãn.")
else:
    for ac in active_candidates:
        print(f"-> Symbol: {ac['symbol']} {ac['side']}")
        print(f"   Signal ID: {ac['id']}")
        print(f"   Telegram Time: {ac['ev_date']}")
        print(f"   Thị giá hiện tại: {ac['live_p']}")
        print(f"   Vùng Entry admin: [{ac['zone_min']} - {ac['zone_max']}]")
        print(f"   Stop Loss: {ac['sl']} | Take Profit 1: {ac['tp1']}")
        print(f"   Trạng thái: {ac['status']}")
        print(f"   Lý do trước đó: {ac['reason']}")
        print("-" * 50)
print("="*85)

conn.close()

