import sqlite3
import json
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

db_paths = [
    os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db'),
    'data/trading_state.db'
]

# Pick the active one with the most records
chosen_db = None
max_count = -1
for p in db_paths:
    if os.path.exists(p):
        conn = sqlite3.connect(p)
        c = conn.cursor()
        c.execute("SELECT count(*) FROM signals")
        cnt = c.fetchone()[0]
        conn.close()
        if cnt > max_count:
            max_count = cnt
            chosen_db = p

print(f"Using database: {chosen_db} (Total signals: {max_count})")

conn = sqlite3.connect(chosen_db)
cur = conn.cursor()

# Query signals from today (2026-10-20)
# Look for created_at like '2026-10-20%' or today's date
cur.execute("""
    SELECT signal_id, chat_id, message_id, symbol, side, state, entry_mode, entries_json, stop_loss, take_profits_json, leverage, blocking_reason, created_at
    FROM signals
    WHERE created_at LIKE '2026-10-20%'
    ORDER BY created_at DESC
""")
rows = cur.fetchall()

print(f"Found {len(rows)} signals from today (2026-10-20)\n")

# Get live prices from Binance
def get_live_price(symbol):
    try:
        url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return Decimal(str(data.get('price', '0')))
    except Exception as e:
        return None

results = []
for r in rows:
    sig_id, chat_id, msg_id, sym, side, state, mode, entries_raw, sl_raw, tps_raw, lev, reason, created_at = r
    try:
        entries = [Decimal(str(x)) for x in json.loads(entries_raw)] if entries_raw else []
    except:
        entries = []
    sl = Decimal(str(sl_raw)) if sl_raw else None
    try:
        tps = [Decimal(str(x)) for x in json.loads(tps_raw)] if tps_raw else []
    except:
        tps = []
    
    live_p = get_live_price(sym)

    status_assessment = "CHƯA XÁC ĐỊNH"
    can_re_enter = False
    zone_min = min(entries) if entries else None
    zone_max = max(entries) if entries else None
    tp1 = tps[0] if tps else None

    if live_p and entries and sl and tp1:
        if side == "LONG":
            if live_p >= tp1:
                status_assessment = f"ĐÃ CHẠM TP1 ({tp1}) -> BỎ QUA"
            elif live_p <= sl:
                status_assessment = f"ĐÃ THỦNG SL ({sl}) -> BỎ QUA"
            elif zone_min <= live_p <= zone_max:
                status_assessment = f"ĐANG TRONG VÙNG ENTRY [{zone_min} - {zone_max}] -> ĐỦ ĐIỀU KIỆN VÀO LỆNH!"
                can_re_enter = True
            elif live_p < zone_min:
                discount_pct = (zone_min - live_p) / zone_min * 100
                status_assessment = f"RẺ HƠN VÙNG ENTRY (-{discount_pct:.2f}%) & TRÊN SL -> ĐỦ ĐIỀU KIỆN VÀO LỆNH (GIÁ TỐT)!"
                can_re_enter = True
            elif live_p > zone_max:
                drift_pct = (live_p - zone_max) / zone_max * 100
                if drift_pct <= Decimal("1.0"):
                    status_assessment = f"SÁT TRẦN VÙNG ENTRY (+{drift_pct:.2f}% <= 1.0%) -> ĐỦ ĐIỀU KIỆN VÀO LỆNH!"
                    can_re_enter = True
                else:
                    status_assessment = f"TĂNG QUÁ VÙNG ENTRY (+{drift_pct:.2f}% > 1%) -> CHẶN FOMO"
        elif side == "SHORT":
            if live_p <= tp1:
                status_assessment = f"ĐÃ CHẠM TP1 ({tp1}) -> BỎ QUA"
            elif live_p >= sl:
                status_assessment = f"ĐÃ VƯỢT SL ({sl}) -> BỎ QUA"
            elif zone_min <= live_p <= zone_max:
                status_assessment = f"ĐANG TRONG VÙNG ENTRY [{zone_min} - {zone_max}] -> ĐỦ ĐIỀU KIỆN VÀO LỆNH!"
                can_re_enter = True
            elif live_p > zone_max:
                pump_pct = (live_p - zone_max) / zone_max * 100
                status_assessment = f"CAO HƠN VÙNG ENTRY (+{pump_pct:.2f}%) & DƯỚI SL -> ĐỦ ĐIỀU KIỆN VÀO LỆNH (GIÁ BÁN TỐT)!"
                can_re_enter = True
            elif live_p < zone_min:
                drift_pct = (zone_min - live_p) / zone_min * 100
                if drift_pct <= Decimal("1.0"):
                    status_assessment = f"SÁT ĐÁY VÙNG ENTRY (-{drift_pct:.2f}% <= 1.0%) -> ĐỦ ĐIỀU KIỆN VÀO LỆNH!"
                    can_re_enter = True
                else:
                    status_assessment = f"GIẢM QUÁ VÙNG ENTRY (-{drift_pct:.2f}% > 1%) -> CHẶN BÁN ĐUỔI"

    results.append({
        'signal_id': sig_id,
        'chat_id': chat_id,
        'msg_id': msg_id,
        'symbol': sym,
        'side': side,
        'state': state,
        'mode': mode,
        'entries': entries,
        'zone_min': zone_min,
        'zone_max': zone_max,
        'sl': sl,
        'tp1': tp1,
        'live_p': live_p,
        'reason': reason,
        'created_at': created_at,
        'assessment': status_assessment,
        'can_re_enter': can_re_enter
    })

print(f"{'SYMBOL':<10} | {'SIDE':<5} | {'STATE':<10} | {'ENTRY ZONE':<22} | {'LIVE PRICE':<10} | {'ASSESSMENT'}")
print("-" * 100)
for r in results:
    sym_str = str(r['symbol'] or 'UNKNOWN')
    side_str = str(r['side'] or 'N/A')
    state_str = str(r['state'] or 'N/A')
    zone_str = f"[{r['zone_min']} - {r['zone_max']}]" if r['zone_min'] else "N/A"
    live_str = f"{r['live_p']:.4f}" if r['live_p'] is not None else "N/A"
    print(f"{sym_str:<10} | {side_str:<5} | {state_str:<10} | {zone_str:<25} | {live_str:<10} | {r['assessment']}")

conn.close()
