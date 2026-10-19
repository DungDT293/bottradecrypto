import asyncio
import sys
import os
import uuid
import sqlite3
from decimal import Decimal

sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from config.config import load_config
from core.enums import OrderSide, OrderType
from exchange.binance_client import BinanceFuturesClient

async def rebalance_bat():
    cfg = load_config(r"C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\config.yaml")
    client = BinanceFuturesClient(cfg)
    db_p = r"C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\data\trading_state.db"

    try:
        print("=== 1. KIỂM TRA LỆNH CŨ CỦA BATUSDT TRÊN BINANCE ===")
        open_orders = await client.get_open_orders("BATUSDT")
        old_tp_orders = [o for o in (open_orders or []) if o.get("type") == "LIMIT" and o.get("side") == "SELL"]
        print(f"Tìm thấy {len(old_tp_orders)} lệnh TP cũ của BATUSDT.")
        for o in old_tp_orders:
            print(f"  * OrderId: {o.get('orderId')} | CID: {o.get('clientOrderId')} | Qty: {o.get('origQty')} @ {o.get('price')}")

        print("\n=== 2. HỦY CÁC LỆNH TP CŨ (GIỮ NGUYÊN STOP LOSS ALGO) ===")
        for o in old_tp_orders:
            cid = o.get("clientOrderId")
            try:
                res = await client.cancel_standard_order("BATUSDT", client_order_id=cid)
                print(f"  -> Đã hủy thành công lệnh cũ: {cid}")
            except Exception as e:
                print(f"  -> Lỗi khi hủy lệnh {cid}: {e}")

        print("\n=== 3. ĐẶT 3 LỆNH TP MỚI THEO TỶ LỆ CHUẨN 35% - 42.3% - 22.7% ===")
        # Total position: 27.4 coin
        # TP1 (35%): 9.6 coin @ 0.1900
        # TP2 (42.3%): 11.6 coin @ 0.2050
        # TP3 (22.7%): 6.2 coin @ 0.2250
        new_tps = [
            (Decimal("9.6"), Decimal("0.1900"), 1),
            (Decimal("11.6"), Decimal("0.2050"), 2),
            (Decimal("6.2"), Decimal("0.2250"), 3),
        ]

        placed_orders = []
        for qty, price, idx in new_tps:
            cid = f"tp_sig_-10020_{idx}_{uuid.uuid4().hex[:4]}"
            resp = await client.create_standard_order(
                symbol="BATUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=qty,
                price=price,
                client_order_id=cid,
                reduce_only=True,
            )
            print(f"  -> Đã đặt thành công TP #{idx}: Bán {qty} coin @ {price} | OrderId: {resp.get('orderId')} | CID: {cid}")
            placed_orders.append((cid, str(resp.get("orderId")), str(price), str(qty)))

        print("\n=== 4. CẬP NHẬT CƠ SỞ DỮ LIỆU LOCAL ===")
        conn = sqlite3.connect(db_p)
        # Mark old TP orders as CANCELED
        conn.execute("""
            UPDATE orders 
            SET status = 'CANCELED', updated_at = datetime('now')
            WHERE symbol = 'BATUSDT' AND order_type = 'LIMIT' AND status = 'NEW'
        """)
        # Insert new orders
        sig_id = "sig_-1002007658025_53175_369a48"
        for cid, oid, p, q in placed_orders:
            conn.execute("""
                INSERT INTO orders (client_order_id, exchange_order_id, signal_id, symbol, side, order_type, price, quantity, status, is_reduce_only, is_algo, created_at, updated_at)
                VALUES (?, ?, ?, 'BATUSDT', 'SELL', 'LIMIT', ?, ?, 'NEW', 1, 0, datetime('now'), datetime('now'))
            """, (cid, oid, sig_id, p, q))
        conn.commit()
        conn.close()
        print("Đã cập nhật cơ sở dữ liệu thành công.")

        print("\n=== 5. KIỂM TRA ĐỐI SOÁT TỔNG THỂ SAU KHI CẬP NHẬT ===")
        verify_orders = await client.get_open_orders("BATUSDT")
        verify_algos = await client.get_open_algo_orders("BATUSDT")
        print(f"Số lệnh TP Limit đang mở của BATUSDT: {len(verify_orders or [])}")
        total_tp = sum(float(o.get("origQty", 0)) for o in (verify_orders or []))
        print(f"Tổng khối lượng TP: {total_tp} (Khối lượng vị thế: 27.4)")

        print(f"Số lệnh SL Algo đang mở của BATUSDT: {len(verify_algos or [])}")
        for a in (verify_algos or []):
            print(f"  * SL Algo: {a.get('orderType')} {a.get('side')} Qty={a.get('quantity')} Trigger={a.get('triggerPrice')}")

    except Exception as e:
        print(f"Lỗi: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(rebalance_bat())

