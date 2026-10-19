import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from config.config import load_config
from exchange.binance_client import BinanceFuturesClient

async def check():
    cfg = load_config(r"C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\config.yaml")
    client = BinanceFuturesClient(cfg)
    try:
        positions = await client.get_open_positions()
        orders = await client.get_open_orders()
        algos = await client.get_open_algo_orders()

        print("================================================================================")
        print(" 1. VỊ THẾ MỞ TRÊN BINANCE (OPEN POSITIONS)")
        print("================================================================================")
        active_positions = [p for p in (positions or []) if float(p.get("positionAmt", 0)) != 0]
        if not active_positions:
            print("Không có vị thế mở nào trên sàn.")
        for p in active_positions:
            amt = float(p.get("positionAmt", 0))
            side_str = "LONG" if amt > 0 else "SHORT"
            print(f"Symbol: {p['symbol']} | Side: {side_str} | Vol: {p['positionAmt']} | Entry: {p['entryPrice']} | Mark: {p['markPrice']} | Liq: {p['liquidationPrice']} | Lev: {p['leverage']}x | uPnL: {p['unRealizedProfit']} USDT")

        print("\n================================================================================")
        print(" 2. LỆNH ĐIỀU KIỆN (ALGO ORDERS - STOP LOSS)")
        print("================================================================================")
        if not algos:
            print("CẢNH BÁO: KHÔNG CÓ LỆNH ALGO ORDER NÀO ĐANG CHỜ KÍCH HOẠT!")
        for a in (algos or []):
            print(f"AlgoId: {a.get('algoId')} | CID: {a.get('clientAlgoId')} | Symbol: {a.get('symbol')} | Side: {a.get('side')} | Type: {a.get('orderType')} | TriggerPrice: {a.get('triggerPrice')} | Qty: {a.get('quantity')} | ClosePos: {a.get('closePosition')} | ReduceOnly: {a.get('reduceOnly')}")

        print("\n================================================================================")
        print(" 3. LỆNH CHỜ KHỚP (STANDARD ORDERS - TAKE PROFIT LIMIT)")
        print("================================================================================")
        if not orders:
            print("Không có lệnh Limit order nào đang chờ khớp.")
        for o in (orders or []):
            print(f"OrderId: {o.get('orderId')} | CID: {o.get('clientOrderId')} | Symbol: {o.get('symbol')} | Side: {o.get('side')} | Type: {o.get('type')} | Price: {o.get('price')} | OrigQty: {o.get('origQty')} | ReduceOnly: {o.get('reduceOnly')}")

        print("\n================================================================================")
        print(" 4. KIỂM TRA TÍNH TOÀN VẸN & ĐỐI SOÁT BẢO VỆ (AUDIT CHECKS)")
        print("================================================================================")
        for p in active_positions:
            sym = p["symbol"]
            amt = abs(float(p["positionAmt"]))
            entry_p = float(p.get("entryPrice", 0))
            mark_p = float(p.get("markPrice", 0))
            is_long = float(p["positionAmt"]) > 0

            sym_algos = [a for a in (algos or []) if a.get("symbol") == sym]
            sym_orders = [o for o in (orders or []) if o.get("symbol") == sym]

            total_sl_qty = sum(float(a.get("quantity") or a.get("origQty") or 0) for a in sym_algos)
            total_tp_qty = sum(float(o.get("origQty") or 0) for o in sym_orders)

            print(f"\n* CẶP {sym} (Vị thế: {amt} coin, Entry: {entry_p}, Mark: {mark_p}):")

            # Check SL
            if len(sym_algos) == 0:
                print(f"  [BẤT THƯỜNG] KHÔNG CÓ LỆNH STOP LOSS BẢO VỆ!")
            elif total_sl_qty < amt:
                print(f"  [BẤT THƯỜNG] SL THIẾU KHỐI LƯỢNG: Chỉ có {total_sl_qty}/{amt} coin được bảo vệ!")
            else:
                sl_trigger = float(sym_algos[0].get("triggerPrice", 0))
                sl_dist_pct = abs(entry_p - sl_trigger) / entry_p * 100
                print(f"  [AN TOÀN] Stop Loss hợp lệ: {sym_algos[0].get('side')} {sym_algos[0].get('orderType')} @ {sl_trigger} (cách Entry {sl_dist_pct:.2f}%). Vol: {total_sl_qty}/{amt}")

                # Check SL direction logic
                if is_long and sl_trigger >= mark_p:
                    print(f"  [BẤT THƯỜNG] Long nhưng SL ({sl_trigger}) >= Mark Price ({mark_p})! Sẽ bị kích hoạt ngay!")
                elif not is_long and sl_trigger <= mark_p:
                    print(f"  [BẤT THƯỜNG] Short nhưng SL ({sl_trigger}) <= Mark Price ({mark_p})! Sẽ bị kích hoạt ngay!")

            # Check TP
            if len(sym_orders) == 0:
                print(f"  [CẢNH BÁO] Không có lệnh Take Profit limit!")
            else:
                print(f"  [THÔNG TIN] Có {len(sym_orders)} lệnh Take Profit. Tổng khối lượng TP: {total_tp_qty:.2f} (Khối lượng vị thế: {amt:.2f})")
                for i, o in enumerate(sym_orders, 1):
                    tp_price = float(o.get("price", 0))
                    tp_qty = float(o.get("origQty", 0))
                    tp_dist_pct = (tp_price - entry_p) / entry_p * 100 if is_long else (entry_p - tp_price) / entry_p * 100
                    print(f"     TP #{i}: Bán {tp_qty} @ {tp_price} ({tp_dist_pct:+.2f}% so với Entry) | ReduceOnly={o.get('reduceOnly')}")

            # Check Liquidation
            liq_p = float(p.get("liquidationPrice") or 0)
            print(f"  [THANH LÝ] Giá thanh lý: {liq_p} ({'KHÔNG CÓ RỦI RO THANH LÝ (Liq=0)' if liq_p == 0 else f'Liq={liq_p}'})")

    except Exception as e:
        print(f"Lỗi: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(check())

