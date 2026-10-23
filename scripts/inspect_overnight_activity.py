import asyncio
import sys
import os
import sqlite3
import json
import datetime

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from config.config import load_config
from exchange.binance_client import BinanceFuturesClient

async def check():
    print("================================================================================")
    print(f"KIỂM TRA HOẠT ĐỘNG VÀ CÁC LỆNH ĐÃ MỞ / ĐÃ ĐÓNG TỪ SAU LỆNH BTW")
    print(f"Thời gian hiện tại: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("================================================================================\n")

    cfg = load_config('config.yaml')
    client = BinanceFuturesClient(cfg)

    # 1. Check Binance Live
    try:
        for attempt in range(1, 10):
            try:
                eq = await client.get_account_equity()
                print(f"💰 TÀI KHOẢN BINANCE EQUITY: {eq} USDT")
                
                positions = await client.get_open_positions()
                print(f"\n📊 VỊ THẾ ĐANG MỞ ({len(positions)}):")
                if not positions:
                    print("  (Không có vị thế nào đang mở)")
                for p in positions:
                    sym = p.get('symbol')
                    amt = p.get('positionAmt')
                    entry = p.get('entryPrice')
                    pnl = p.get('unRealizedProfit')
                    mark = p.get('markPrice')
                    lev = p.get('leverage')
                    liq = p.get('liquidationPrice')
                    print(f"  - {sym}: {amt} coin @ Entry {entry} (Mark: {mark}, PnL: {pnl} USDT, Lev: {lev}x, Liq: {liq})")

                open_orders = await client.get_open_orders()
                print(f"\n📝 LỆNH CHỜ (STANDARD) ĐANG TREO ({len(open_orders)}):")
                if not open_orders:
                    print("  (Không có lệnh chờ nào)")
                for o in open_orders:
                    sym = o.get('symbol')
                    side = o.get('side')
                    qty = o.get('origQty')
                    price = o.get('price')
                    otype = o.get('type')
                    oid = o.get('orderId')
                    print(f"  - {sym}: {side} {qty} @ {price} ({otype}, ID: {oid})")

                open_algos = await client.get_open_algo_orders()
                print(f"\n🛡️ LỆNH ĐIỀU KIỆN (ALGO/STOP LOSS) ĐANG TREO ({len(open_algos)}):")
                if not open_algos:
                    print("  (Không có lệnh algo nào)")
                for a in open_algos:
                    sym = a.get('symbol')
                    side = a.get('side')
                    trig = a.get('triggerPrice')
                    atype = a.get('algoType')
                    aid = a.get('algoId')
                    print(f"  - {sym}: {side} {atype} @ {trig} (Algo ID: {aid})")

                # Trades since BTW (from 22:45 Oct 21 -> timestamp 1792597500000)
                trades = await client._request('GET', '/fapi/v1/userTrades', params={'startTime': 1792597500000, 'limit': 50}, signed=True)
                print(f"\n📜 LỊCH SỬ KHỚP LỆNH THỰC TẾ TRÊN BINANCE (Từ sau BTW - {len(trades)} lượt khớp):")
                if not trades:
                    print("  (Không có giao dịch nào khớp sau lệnh BTW)")
                for t in trades:
                    dt = datetime.datetime.fromtimestamp(t['time']/1000).strftime('%Y-%m-%d %H:%M:%S')
                    print(f"  - [{dt}] {t['symbol']}: {t['side']} {t['qty']} coin @ {t['price']} | Realized PnL: {t['realizedPnl']} USDT | Commission: {t['commission']} {t['commissionAsset']}")

                # Income records
                income = await client._request('GET', '/fapi/v1/income', params={'startTime': 1792597500000, 'limit': 50}, signed=True)
                print(f"\n💵 BIẾN ĐỘNG SỐ DƯ & LÃI LỖ ĐÃ CHỐT (INCOME) TRÊN BINANCE:")
                for inc in income:
                    dt = datetime.datetime.fromtimestamp(inc['time']/1000).strftime('%Y-%m-%d %H:%M:%S')
                    print(f"  - [{dt}] {inc.get('symbol', 'TỔNG')}: {inc['incomeType']} = {inc['income']} {inc['asset']}")

                break
            except Exception as e:
                print(f"Lần {attempt} lỗi kết nối Binance: {e}")
                await asyncio.sleep(1)
    finally:
        await client.close()

    # 2. Check Database: signals, orders, messages overnight
    print("\n" + "=" * 80)
    print("KIỂM TRA CƠ SỞ DỮ LIỆU APP & TIN NHẮN ĐÊM QUA")
    print("=" * 80)

    db_paths = [
        os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db'),
        './data/trading_state.db',
    ]

    for p in db_paths:
        if not os.path.exists(p):
            continue
        print(f"\n--- Database: {p} ---")
        conn = sqlite3.connect(p)
        cur = conn.cursor()

        # Signals created since 22:45 Oct 21
        cur.execute("""
            SELECT signal_id, symbol, side, state, entries_json, stop_loss, take_profits_json, leverage, blocking_reason, created_at
            FROM signals
            WHERE created_at >= '2026-10-21T15:45:00'
            ORDER BY created_at ASC
        """)
        sigs = cur.fetchall()
        print(f"Tín hiệu mới phát sinh ({len(sigs)}):")
        for s in sigs:
            print(f"  Signal ID: {s[0]} | {s[1]} ({s[2]}) | State: {s[3]} | SL: {s[5]} | Entries: {s[4]} | Created: {s[9]}")
            if s[8]:
                print(f"    Ghi chú/Chặn: {s[8]}")

        # Orders created since 22:45 Oct 21
        cur.execute("""
            SELECT client_order_id, signal_id, symbol, side, order_type, price, quantity, status, filled_quantity, avg_fill_price, exchange_order_id, created_at
            FROM orders
            WHERE created_at >= '2026-10-21T15:45:00'
            ORDER BY created_at ASC
        """)
        ords = cur.fetchall()
        print(f"\nLệnh bot đã tạo ({len(ords)}):")
        for o in ords:
            print(f"  Order: {o[2]} {o[3]} {o[4]} {o[6]} coin @ {o[5]} | Status: {o[7]} (Filled: {o[8]} @ {o[9]}) | ExchID: {o[10]} | Time: {o[11]}")

        # Count of telegram messages overnight
        cur.execute("SELECT count(*), max(telegram_timestamp) FROM messages WHERE telegram_timestamp >= '2026-10-21T15:45:00'")
        msg_count, max_tele = cur.fetchone()
        print(f"\nTin nhắn Telegram nhận đêm qua: {msg_count} tin (Tin gần nhất: {max_tele})")

        conn.close()

if __name__ == '__main__':
    asyncio.run(check())

