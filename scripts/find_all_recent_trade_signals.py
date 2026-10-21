import sqlite3
import json
import urllib.request
import os
import sys
from decimal import Decimal

sys.stdout.reconfigure(encoding='utf-8')

db = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db')
conn = sqlite3.connect(db)
cur = conn.cursor()

# 1. Fetch ALL live Binance Futures prices in ONE single batch call
print("Fetching all live Binance Futures prices...")
req = urllib.request.Request("https://fapi.binance.com/fapi/v1/ticker/price", headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req, timeout=10) as resp:
    all_tickers = json.loads(resp.read().decode('utf-8'))
live_prices = {item['symbol']: Decimal(str(item['price'])) for item in all_tickers}
print(f"Loaded {len(live_prices)} live prices from Binance Futures.\n")

# 2. Query all trade signals from today and yesterday (last 48h)
cur.execute("""
    SELECT signal_id, chat_id, message_id, symbol, side, state, entry_mode, entries_json, stop_loss, take_profits_json, leverage, blocking_reason, created_at
    FROM signals
    WHERE side IS NOT NULL 
      AND entries_json IS NOT NULL 
      AND stop_loss IS NOT NULL
      AND (created_at LIKE '2026-10-20%' OR created_at LIKE '2026-10-19%')
    ORDER BY created_at DESC
""")
rows = cur.fetchall()
print(f"Total structured trade signals found in last 48h: {len(rows)}\n")

qualifying_signals = []

for r in rows:
    sig_id, chat_id, msg_id, sym, side, state, mode, entries_raw, sl_raw, tps_raw, lev, reason, created_at = r
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

    # Check if admin had a cancellation message
    cur.execute("SELECT raw_text FROM message_versions WHERE chat_id = ? AND message_id > ? ORDER BY message_id ASC", (chat_id, msg_id))
    admin_updates = cur.fetchall()
    is_cancelled = False
    for (utxt,) in admin_updates:
        u_upper = utxt.upper()
        clean_coin = sym.replace("USDT","")
        if ("CANCEL" in u_upper or "CLOSE" in u_upper or "CANCELLED" in u_upper) and clean_coin in u_upper:
            is_cancelled = True
            break

    status = "UNKNOWN"
    can_trade = False

    if is_cancelled:
        status = "ADMIN ĐÃ HỦY / ĐÓNG KÈO"
    elif live_p:
        if side == "LONG":
            if live_p >= tp1:
                status = f"ĐÃ ĐẠT TP1 ({tp1}) [Thị giá: {live_p}]"
            elif live_p <= sl:
                status = f"ĐÃ THỦNG SL ({sl}) [Thị giá: {live_p}]"
            elif zone_min <= live_p <= zone_max:
                status = f"ĐANG TRONG VÙNG ENTRY [{zone_min} - {zone_max}]"
                can_trade = True
            elif live_p < zone_min:
                disc = (zone_min - live_p) / zone_min * 100
                status = f"DƯỚI VÙNG ENTRY GIÁ TỐT (-{disc:.2f}%)"
                can_trade = True
            elif live_p > zone_max:
                drift = (live_p - zone_max) / zone_max * 100
                if drift <= Decimal("1.0"):
                    status = f"SÁT TRẦN ENTRY (+{drift:.2f}% <= 1%)"
                    can_trade = True
                else:
                    status = f"TĂNG QUÁ VÙNG ENTRY (+{drift:.2f}%)"
        elif side == "SHORT":
            if live_p <= tp1:
                status = f"ĐÃ ĐẠT TP1 ({tp1}) [Thị giá: {live_p}]"
            elif live_p >= sl:
                status = f"ĐÃ VƯỢT SL ({sl}) [Thị giá: {live_p}]"
            elif zone_min <= live_p <= zone_max:
                status = f"ĐANG TRONG VÙNG ENTRY [{zone_min} - {zone_max}]"
                can_trade = True
            elif live_p > zone_max:
                pump = (live_p - zone_max) / zone_max * 100
                status = f"TRÊN VÙNG ENTRY GIÁ BÁN TỐT (+{pump:.2f}%)"
                can_trade = True
            elif live_p < zone_min:
                drift = (zone_min - live_p) / zone_min * 100
                if drift <= Decimal("1.0"):
                    status = f"SÁT ĐÁY ENTRY (-{drift:.2f}% <= 1%)"
                    can_trade = True
                else:
                    status = f"GIẢM QUÁ VÙNG ENTRY (-{drift:.2f}%)"
    else:
        status = "KHÔNG TÌM THẤY GIÁ TRÊN BINANCE FUTURES"

    res_item = {
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
        'created_at': created_at,
        'reason': reason
    }
    qualifying_signals.append(res_item)

print(f"{'SYMBOL':<10} | {'SIDE':<5} | {'STATE':<10} | {'LIVE P':<10} | {'ENTRY RANGE':<25} | {'STATUS'}")
print("-" * 115)
for q in qualifying_signals:
    z_str = f"[{q['zone_min']} - {q['zone_max']}]"
    lp_str = f"{q['live_p']:.4f}" if q['live_p'] is not None else "N/A"
    print(f"{q['symbol']:<10} | {q['side']:<5} | {q['state']:<10} | {lp_str:<10} | {z_str:<25} | {q['status']}")

print("\n" + "="*85)
print("DANH SÁCH KÈO ĐỦ ĐIỀU KIỆN VÀO LỆNH (CAN RE-ENTER):")
can_trade_list = [q for q in qualifying_signals if q['can_trade']]
if not can_trade_list:
    print("Hiện không có kèo nào đang trong vùng entry.")
else:
    for ct in can_trade_list:
        print(f"-> {ct['symbol']} ({ct['side']}) | ID: {ct['id']} | Giá: {ct['live_p']} | Vùng Entry: [{ct['zone_min']} - {ct['zone_max']}] | SL: {ct['sl']} | TP1: {ct['tp1']}")
print("="*85)

conn.close()

