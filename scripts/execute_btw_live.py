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
SIDE = PositionSide.LONG
SL_PRICE = Decimal("1.4526")
TP1_PRICE = Decimal("1.6600")
TP2_PRICE = Decimal("1.7300")
TP3_PRICE = Decimal("1.8700")
LEVERAGE = 20

async def execute_trade():
    print("=" * 60)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] KÍCH HOẠT VÀO LỆNH LIVE: {SYMBOL} (LONG 20x)")
    print("=" * 60)

    cfg = load_config('config.yaml')
    client = BinanceFuturesClient(cfg)

    try:
        # 1. Pre-flight checks & filters
        filters = await client.get_symbol_filter(SYMBOL)
        print(f"Filters: min_qty={filters.min_qty}, step_size={filters.step_size}, tick_size={filters.tick_size}, min_notional={filters.min_notional}")

        # Set margin type & leverage
        try:
            await client.set_margin_type_cross(SYMBOL)
            print("Margin Type: CROSSED (Đã thiết lập)")
        except Exception as e:
            print(f"Margin Type check: {e}")

        try:
            lev_res = await client.set_leverage(SYMBOL, LEVERAGE)
            print(f"Leverage: {lev_res}x")
        except Exception as e:
            print(f"Set leverage: {e}")

        # 2. Account balance & risk sizing
        equity = await client.get_account_equity()
        print(f"Tài khoản Binance Equity: {equity} USDT")

        ticker = await client._request('GET', '/fapi/v1/ticker/price', params={'symbol': SYMBOL})
        cur_price = Decimal(ticker['price'])
        print(f"Giá thị trường BTWUSDT: {cur_price}")

        risk_pct = Decimal("0.04") # 4%
        max_loss = equity * risk_pct
        risk_per_unit = cur_price - SL_PRICE

        if risk_per_unit <= Decimal("0"):
            raise ValueError(f"Giá thị trường ({cur_price}) đã thấp hơn Stop Loss ({SL_PRICE})! Không thể vào lệnh an toàn.")

        calc_qty = max_loss / risk_per_unit
        # Round down to step_size
        step = filters.step_size
        order_qty = (calc_qty // step) * step

        notional_val = order_qty * cur_price
        req_margin = notional_val / Decimal(str(LEVERAGE))
        actual_risk = order_qty * risk_per_unit

        print("-" * 50)
        print(f"TÍNH TOÁN QUẢN TRỊ RỦI RO:")
        print(f"- Mức rủi ro tối đa (4% vốn): {max_loss:.2f} USDT")
        print(f"- Khoảng cách tới SL {SL_PRICE}: {risk_per_unit:.4f} ({(risk_per_unit/cur_price*100):.2f}%)")
        print(f"- Khối lượng đặt: {order_qty} BTW")
        print(f"- Giá trị vị thế: {notional_val:.2f} USDT")
        print(f"- Ký quỹ yêu cầu (20x): {req_margin:.2f} USDT")
        print(f"- Lỗ tối đa nếu dính SL: {actual_risk:.2f} USDT ({(actual_risk/equity*100):.2f}% tài khoản)")
        print("-" * 50)

        if notional_val < filters.min_notional:
            raise ValueError(f"Giá trị vị thế {notional_val} nhỏ hơn min_notional {filters.min_notional}")

        # 3. Submit Entry Order (MARKET BUY)
        entry_cid = f"ent_btw_{uuid.uuid4().hex[:8]}"
        print(f"Đang gửi lệnh MARKET BUY {order_qty} BTW (CID: {entry_cid})...")
        entry_res = await client.create_standard_order(
            symbol=SYMBOL,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=order_qty,
            client_order_id=entry_cid,
        )

        entry_order_id = str(entry_res.get("orderId"))
        executed_qty = Decimal(str(entry_res.get("executedQty", order_qty)))
        cum_quote = Decimal(str(entry_res.get("cumQuote", "0")))
        avg_price = (cum_quote / executed_qty) if executed_qty > 0 and cum_quote > 0 else cur_price
        avg_price = (avg_price // filters.tick_size) * filters.tick_size

        print(f"✅ KHỚP LỆNH ENTRY THÀNH CÔNG!")
        print(f"- Exchange Order ID: {entry_order_id}")
        print(f"- Khối lượng khớp: {executed_qty} BTW")
        print(f"- Giá khớp trung bình: {avg_price} USDT")

        # 4. Submit Protective Stop Loss (STOP_MARKET Algo Order)
        sl_cid = f"sl_btw_{uuid.uuid4().hex[:8]}"
        print(f"Đang gửi lệnh bảo vệ Stop Loss @ {SL_PRICE} (CID: {sl_cid})...")
        sl_res = await client.create_algo_order(
            symbol=SYMBOL,
            side=OrderSide.SELL,
            order_type=OrderType.STOP_MARKET,
            trigger_price=SL_PRICE,
            quantity=executed_qty,
            client_algo_id=sl_cid,
            close_position=False,
            reduce_only=True,
        )
        sl_algo_id = str(sl_res.get("algoId"))
        print(f"🛡️ ĐÃ ĐẶT BẢO VỆ STOP LOSS THÀNH CÔNG! AlgoId: {sl_algo_id} @ {SL_PRICE}")

        # 5. Submit 3 Take Profit Limit Orders
        # 35% / 35% / 30%
        tp1_qty = (executed_qty * Decimal("0.35") // step) * step
        tp2_qty = (executed_qty * Decimal("0.35") // step) * step
        tp3_qty = executed_qty - tp1_qty - tp2_qty

        tp_orders_info = []

        # TP 1
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
        tp_orders_info.append(("TP1", tp1_cid, tp1_res.get("orderId"), TP1_PRICE, tp1_qty))
        print(f"🎯 ĐÃ ĐẶT TP1: {tp1_qty} BTW @ {TP1_PRICE} (ID: {tp1_res.get('orderId')})")

        # TP 2
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
        tp_orders_info.append(("TP2", tp2_cid, tp2_res.get("orderId"), TP2_PRICE, tp2_qty))
        print(f"🎯 ĐÃ ĐẶT TP2: {tp2_qty} BTW @ {TP2_PRICE} (ID: {tp2_res.get('orderId')})")

        # TP 3
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
        tp_orders_info.append(("TP3", tp3_cid, tp3_res.get("orderId"), TP3_PRICE, tp3_qty))
        print(f"🎯 ĐÃ ĐẶT TP3: {tp3_qty} BTW @ {TP3_PRICE} (ID: {tp3_res.get('orderId')})")

        # 6. Record everything into both local & appdata SQLite databases
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
                    SET state = ?, entries_json = ?, blocking_reason = NULL, updated_at = ?
                    WHERE signal_id = ? OR symbol = ?
                """, (SignalState.OPEN_PROTECTED.value, json.dumps([str(avg_price)]), now_iso, SIGNAL_ID, SYMBOL))

                # Insert entry order
                cur.execute("""
                    INSERT OR REPLACE INTO orders 
                    (client_order_id, signal_id, symbol, side, order_type, price, quantity, status, filled_quantity, avg_fill_price, exchange_order_id, is_algo, is_reduce_only, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (entry_cid, SIGNAL_ID, SYMBOL, "BUY", "MARKET", str(avg_price), str(executed_qty), "FILLED", str(executed_qty), str(avg_price), entry_order_id, 0, 0, now_iso, now_iso))

                # Insert SL algo order
                cur.execute("""
                    INSERT OR REPLACE INTO orders 
                    (client_order_id, signal_id, symbol, side, order_type, price, quantity, trigger_price, status, filled_quantity, exchange_order_id, is_algo, is_reduce_only, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (sl_cid, SIGNAL_ID, SYMBOL, "SELL", "STOP_MARKET", None, str(executed_qty), str(SL_PRICE), "NEW", "0", sl_algo_id, 1, 1, now_iso, now_iso))

                # Insert TP orders
                for tp_label, cid, oid, prc, q in tp_orders_info:
                    cur.execute("""
                        INSERT OR REPLACE INTO orders 
                        (client_order_id, signal_id, symbol, side, order_type, price, quantity, status, filled_quantity, exchange_order_id, is_algo, is_reduce_only, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (cid, SIGNAL_ID, SYMBOL, "SELL", "LIMIT", str(prc), str(q), "NEW", "0", str(oid), 0, 1, now_iso, now_iso))

                # Update position
                cur.execute("""
                    INSERT OR REPLACE INTO positions
                    (symbol, side, quantity, entry_price, leverage, margin_mode, active_signal_id, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (SYMBOL, "LONG", str(executed_qty), str(avg_price), LEVERAGE, "CROSSED", SIGNAL_ID, now_iso))

                # Timeline events
                cur.execute("""
                    INSERT INTO signal_timeline (signal_id, event_type, details, created_at)
                    VALUES (?, ?, ?, ?)
                """, (SIGNAL_ID, "LIVE_ORDER_EXECUTED", f"Khớp lệnh MARKET LONG {executed_qty} BTW giá {avg_price}. Đã đặt SL {SL_PRICE} và 3 TP.", now_iso))

                conn.commit()
                conn.close()
                print(f"Đã cập nhật cơ sở dữ liệu: {db_p}")
            except Exception as e_db:
                print(f"Lỗi cập nhật db {db_p}: {e_db}")

        # 7. Notify running backend to sync
        try:
            sync_url = "http://127.0.0.1:50616/api/binance/sync"
            req = urllib.request.Request(
                sync_url,
                data=b"{}",
                headers={"x-session-token": "wq_w2_3TYpMi_iY9xMi3VaDES4IfV0CDF-rDsuFgZ2Y", "Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=5)
            print("Đã kích hoạt đồng bộ hóa tức thời trên ứng dụng desktop!")
        except Exception as e_sync:
            print(f"Sync call: {e_sync}")

        print("=" * 60)
        print("🎉 KÈO BTWUSDT ĐÃ VÀO VỊ THẾ HOÀN TẤT & ĐƯỢC BẢO VỆ TOÀN DIỆN!")
        print(f"- Vị thế: LONG {executed_qty} BTW @ {avg_price} USDT")
        print(f"- Stop Loss: {SL_PRICE} (Bảo vệ rủi ro < 4% vốn)")
        print(f"- Take Profit: TP1({TP1_PRICE}) | TP2({TP2_PRICE}) | TP3({TP3_PRICE})")
        print("=" * 60)

    finally:
        await client.close()

if __name__ == '__main__':
    asyncio.run(execute_trade())
