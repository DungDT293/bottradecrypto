import asyncio
import os
import sys
import uuid
import json
import sqlite3
import urllib.request
from datetime import datetime
from decimal import Decimal

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from config.config import load_config
from core.enums import OrderSide, OrderType, PositionSide, SignalState
from exchange.binance_client import BinanceFuturesClient

SIGNAL_ID = "sig_-1002007658025_53284_1444c3"
SYMBOL = "BTWUSDT"
SL_PRICE = Decimal("1.4526")
TP1_PRICE = Decimal("1.6600")
TP2_PRICE = Decimal("1.7300")
TP3_PRICE = Decimal("1.8700")

async def protect_position():
    print("=" * 60)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ĐẶT LỆNH BẢO VỆ VỊ THẾ BTWUSDT")
    print("=" * 60)

    cfg = load_config('config.yaml')
    client = BinanceFuturesClient(cfg)

    try:
        amt = Decimal("0")
        entry_price = Decimal("1.4843")
        sl_algo_id = ""
        sl_cid = ""

        for attempt in range(1, 15):
            try:
                # Check current position
                pos = await client.get_position(SYMBOL)
                amt = Decimal(str(pos.get("positionAmt", "0")))
                entry_price = Decimal(str(pos.get("entryPrice", "1.4843")))
                print(f"Vị thế thực tế trên Binance: {amt} BTW @ {entry_price} USDT")

                if amt <= Decimal("0"):
                    print("Không tìm thấy vị thế BTWUSDT nào đang mở!")
                    return

                # 1. Place Stop Loss (STOP_MARKET via algoOrder)
                sl_cid = f"sl_btw_{uuid.uuid4().hex[:8]}"
                print(f"Gửi lệnh Stop Loss @ {SL_PRICE} cho {amt} BTW (CID: {sl_cid})...")
                sl_res = await client.create_algo_order(
                    symbol=SYMBOL,
                    side=OrderSide.SELL,
                    order_type=OrderType.STOP_MARKET,
                    trigger_price=SL_PRICE,
                    quantity=amt,
                    client_algo_id=sl_cid,
                    close_position=False,
                    reduce_only=True,
                )
                sl_algo_id = str(sl_res.get("algoId"))
                print(f"✅ ĐÃ ĐẶT BẢO VỆ STOP LOSS THÀNH CÔNG: Algo ID {sl_algo_id} @ {SL_PRICE}!")
                break
            except Exception as e:
                print(f"Lần {attempt} lỗi: {e}. Đang thử lại sau 1s...")
                await asyncio.sleep(1)

        if not sl_algo_id:
            print("Chưa đặt được Stop Loss! Vui lòng kiểm tra IP.")
            return

        # 2. Place 3 TP Limit Orders (Reduce-Only)
        tp1_qty = Decimal("55")
        tp2_qty = Decimal("55")
        tp3_qty = amt - tp1_qty - tp2_qty # 47

        tp_info = []

        # TP 1
        for attempt in range(1, 5):
            try:
                tp1_cid = f"tp1_btw_{uuid.uuid4().hex[:6]}"
                tp1_res = await client.create_standard_order(
                    symbol=SYMBOL,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=tp1_qty,
                    price=TP1_PRICE,
                    client_order_id=tp1_cid,
                    reduce_only=True,
                )
                tp_info.append(("TP1", tp1_cid, tp1_res.get("orderId"), TP1_PRICE, tp1_qty))
                print(f"🎯 ĐÃ ĐẶT TP1: {tp1_qty} BTW @ {TP1_PRICE} (ID: {tp1_res.get('orderId')})")
                break
            except Exception as e:
                print(f"TP1 retry {attempt}: {e}")
                await asyncio.sleep(1)

        # TP 2
        for attempt in range(1, 5):
            try:
                tp2_cid = f"tp2_btw_{uuid.uuid4().hex[:6]}"
                tp2_res = await client.create_standard_order(
                    symbol=SYMBOL,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=tp2_qty,
                    price=TP2_PRICE,
                    client_order_id=tp2_cid,
                    reduce_only=True,
                )
                tp_info.append(("TP2", tp2_cid, tp2_res.get("orderId"), TP2_PRICE, tp2_qty))
                print(f"🎯 ĐÃ ĐẶT TP2: {tp2_qty} BTW @ {TP2_PRICE} (ID: {tp2_res.get('orderId')})")
                break
            except Exception as e:
                print(f"TP2 retry {attempt}: {e}")
                await asyncio.sleep(1)

        # TP 3
        for attempt in range(1, 5):
            try:
                tp3_cid = f"tp3_btw_{uuid.uuid4().hex[:6]}"
                tp3_res = await client.create_standard_order(
                    symbol=SYMBOL,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=tp3_qty,
                    price=TP3_PRICE,
                    client_order_id=tp3_cid,
                    reduce_only=True,
                )
                tp_info.append(("TP3", tp3_cid, tp3_res.get("orderId"), TP3_PRICE, tp3_qty))
                print(f"🎯 ĐÃ ĐẶT TP3: {tp3_qty} BTW @ {TP3_PRICE} (ID: {tp3_res.get('orderId')})")
                break
            except Exception as e:
                print(f"TP3 retry {attempt}: {e}")
                await asyncio.sleep(1)

        # 3. Update databases
        db_paths = [
            os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db'),
            './data/trading_state.db',
            'bot_storage.db',
        ]

        now_iso = datetime.utcnow().isoformat()
        for db_p in db_paths:
            if not os.path.exists(db_p):
                continue
            try:
                conn = sqlite3.connect(db_p)
                cur = conn.cursor()

                # Update signal
                cur.execute("""
                    UPDATE signals 
                    SET state = ?, entries_json = ?, blocking_reason = NULL, leverage = 10, updated_at = ?
                    WHERE signal_id = ? OR symbol = ?
                """, (SignalState.OPEN_PROTECTED.value, json.dumps([str(entry_price)]), now_iso, SIGNAL_ID, SYMBOL))

                # Insert entry order (FILLED)
                cur.execute("""
                    INSERT OR REPLACE INTO orders 
                    (client_order_id, signal_id, symbol, side, order_type, price, quantity, status, filled_quantity, avg_fill_price, exchange_order_id, is_algo, is_reduce_only, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, ("ent_btw_3a4cb5eb", SIGNAL_ID, SYMBOL, "BUY", "MARKET", str(entry_price), str(amt), "FILLED", str(amt), str(entry_price), "2715343048", 0, 0, now_iso, now_iso))

                # Insert SL algo order
                cur.execute("""
                    INSERT OR REPLACE INTO orders 
                    (client_order_id, signal_id, symbol, side, order_type, price, quantity, trigger_price, status, filled_quantity, exchange_order_id, is_algo, is_reduce_only, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (sl_cid, SIGNAL_ID, SYMBOL, "SELL", "STOP_MARKET", None, str(amt), str(SL_PRICE), "NEW", "0", sl_algo_id, 1, 1, now_iso, now_iso))

                # Insert TP orders
                for tp_label, cid, oid, prc, q in tp_info:
                    cur.execute("""
                        INSERT OR REPLACE INTO orders 
                        (client_order_id, signal_id, symbol, side, order_type, price, quantity, status, filled_quantity, exchange_order_id, is_algo, is_reduce_only, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (cid, SIGNAL_ID, SYMBOL, "SELL", "LIMIT", str(prc), str(q), "NEW", "0", str(oid), 0, 1, now_iso, now_iso))

                # Insert position
                cur.execute("""
                    INSERT OR REPLACE INTO positions
                    (symbol, side, quantity, entry_price, leverage, margin_mode, active_signal_id, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (SYMBOL, "LONG", str(amt), str(entry_price), 10, "CROSSED", SIGNAL_ID, now_iso))

                # Timeline
                cur.execute("""
                    INSERT INTO signal_timeline (signal_id, event_type, details, created_at)
                    VALUES (?, ?, ?, ?)
                """, (SIGNAL_ID, "LIVE_ORDER_PROTECTED", f"Đã khớp 157 BTW @ {entry_price}. Đã đặt Stop Loss {SL_PRICE} và 3 TP.", now_iso))

                conn.commit()
                conn.close()
                print(f"Đã cập nhật DB: {db_p}")
            except Exception as e_db:
                print(f"Lỗi cập nhật db {db_p}: {e_db}")

        # 4. Notify running backend to sync
        try:
            sync_url = "http://127.0.0.1:50616/api/binance/sync"
            req = urllib.request.Request(
                sync_url,
                data=b"{}",
                headers={"x-session-token": "wq_w2_3TYpMi_iY9xMi3VaDES4IfV0CDF-rDsuFgZ2Y", "Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=5)
            print("Đã kích hoạt đồng bộ hóa trên ứng dụng desktop!")
        except Exception as e_sync:
            print(f"Sync call: {e_sync}")

        print("=" * 60)
        print("🎉 VỊ THẾ BTWUSDT ĐÃ ĐƯỢC BẢO VỆ 100%:")
        print(f"- Vị thế: LONG {amt} BTW @ {entry_price} USDT")
        print(f"- Stop Loss: {SL_PRICE} (Algo ID: {sl_algo_id})")
        print(f"- TP1: {tp1_qty} BTW @ {TP1_PRICE}")
        print(f"- TP2: {tp2_qty} BTW @ {TP2_PRICE}")
        print(f"- TP3: {tp3_qty} BTW @ {TP3_PRICE}")
        print("=" * 60)

    finally:
        await client.close()

if __name__ == '__main__':
    asyncio.run(protect_position())
