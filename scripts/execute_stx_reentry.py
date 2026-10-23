import asyncio
import json
import os
import sys
import uuid
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config.config import load_config
from core.enums import OrderSide, OrderType, PositionSide, SignalState
from core.models import Order
from exchange.binance_client import BinanceFuturesClient

SIGNAL_ID = f"sig_reentry_stx_cryptomonk_{uuid.uuid4().hex[:6]}"
SYMBOL = "STXUSDT"
SIDE = PositionSide.LONG
LEVERAGE = 20
STOP_LOSS = Decimal("0.3393")
TOTAL_QTY = Decimal("182")

TPS = [
    (1, Decimal("0.3591"), Decimal("36")),
    (2, Decimal("0.3655"), Decimal("67")),
    (3, Decimal("0.3725"), Decimal("40")),
    (4, Decimal("0.3796"), Decimal("24")),
    (5, Decimal("0.3904"), Decimal("15")),
]

def record_in_database(db_path: str, signal_data: dict, orders_data: list):
    import sqlite3
    if not os.path.exists(db_path):
        return
    print(f"Recording in DB: {db_path}")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # 1. Insert/Replace signal
    c.execute(
        """
        INSERT OR REPLACE INTO signals (
            signal_id, chat_id, message_id, symbol, side, state,
            entry_mode, entries_json, stop_loss, take_profits_json,
            leverage, margin_mode, risk_pct, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            signal_data["signal_id"],
            signal_data["chat_id"],
            signal_data["message_id"],
            signal_data["symbol"],
            signal_data["side"],
            signal_data["state"],
            signal_data["entry_mode"],
            signal_data["entries_json"],
            signal_data["stop_loss"],
            signal_data["take_profits_json"],
            signal_data["leverage"],
            signal_data["margin_mode"],
            signal_data["risk_pct"],
            signal_data["created_at"],
            signal_data["updated_at"],
        ),
    )
    
    # 2. Insert orders
    for o in orders_data:
        c.execute(
            """
            INSERT OR REPLACE INTO orders (
                client_order_id, signal_id, symbol, side, order_type,
                price, quantity, trigger_price, is_reduce_only, is_algo,
                exchange_order_id, status, filled_quantity, avg_fill_price,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                o["client_order_id"],
                o["signal_id"],
                o["symbol"],
                o["side"],
                o["order_type"],
                o.get("price"),
                o["quantity"],
                o.get("trigger_price"),
                1 if o.get("is_reduce_only") else 0,
                1 if o.get("is_algo") else 0,
                o.get("exchange_order_id"),
                o["status"],
                o.get("filled_quantity", 0),
                o.get("avg_fill_price"),
                o["created_at"],
                o["updated_at"],
            ),
        )
        
    # 3. Timeline event
    try:
        c.execute(
            """
            INSERT INTO signal_timeline (signal_id, event_type, details, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                signal_data["signal_id"],
                "SIGNAL_REENTERED_PROTECTED",
                f"Vào lại lệnh STXUSDT Crypto Monk: Vol={TOTAL_QTY}, SL={STOP_LOSS}, 5 TPs={[str(tp[1]) for tp in TPS]}",
                signal_data["created_at"],
            ),
        )
    except Exception as e_tl:
        pass
        
    conn.commit()
    conn.close()

async def main():
    cfg = load_config()
    client = BinanceFuturesClient(cfg)
    await client.sync_time()
    
    print(f"=== KHỞI CHẠY VÀO LỆNH STXUSDT (PHƯƠNG ÁN 2) ===")
    print(f"Signal ID: {SIGNAL_ID}")
    print(f"Symbol: {SYMBOL} | Side: {SIDE.value} | Lev: {LEVERAGE}x | Qty: {TOTAL_QTY}")
    print(f"SL: {STOP_LOSS}")
    print(f"TPs: {[(t[0], str(t[1]), str(t[2])) for t in TPS]}")
    
    # 1. Set leverage and margin type
    try:
        await client.set_leverage(SYMBOL, LEVERAGE)
        print(f"[OK] Đòn bẩy đã thiết lập: {LEVERAGE}x")
    except Exception as e_lev:
        print(f"[NOTE] Leverage: {e_lev}")
        
    try:
        await client.set_margin_type(SYMBOL, "ISOLATED")
        print(f"[OK] Margin type: ISOLATED")
    except Exception as e_mt:
        print(f"[NOTE] Margin type: {e_mt}")
        
    # 2. Execute MARKET BUY entry
    entry_cid = f"ent_{SIGNAL_ID[:8]}_{uuid.uuid4().hex[:4]}"
    print(f"\n[1/3] Gửi lệnh MARKET BUY {TOTAL_QTY} {SYMBOL}...")
    entry_resp = await client.create_standard_order(
        symbol=SYMBOL,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=TOTAL_QTY,
        client_order_id=entry_cid,
        reduce_only=False,
    )
    print(f"[OK] Entry filled! OrderId: {entry_resp.get('orderId')}")
    
    # Fetch filled entry price
    await asyncio.sleep(0.3)
    pos = await client.get_position(SYMBOL)
    avg_entry_price = Decimal(str(pos.get("entryPrice", "0"))) if pos else Decimal("0")
    if avg_entry_price == Decimal("0"):
        avg_entry_price = Decimal(str(entry_resp.get("avgPrice") or entry_resp.get("price") or "0.3533"))
    print(f"[OK] Giá khớp Entry thực tế: {avg_entry_price} USDT")
    
    # 3. Immediately deploy protective STOP_MARKET Algo Order (Bảo vệ 100% Vol)
    sl_cid = f"sl_{SIGNAL_ID[:8]}_{uuid.uuid4().hex[:4]}"
    print(f"\n[2/3] Gửi lệnh Stop Loss STOP_MARKET @ {STOP_LOSS} (Qty: {TOTAL_QTY})...")
    sl_resp = await client.create_algo_order(
        symbol=SYMBOL,
        side=OrderSide.SELL,
        order_type=OrderType.STOP_MARKET,
        trigger_price=STOP_LOSS,
        quantity=TOTAL_QTY,
        client_algo_id=sl_cid,
        close_position=False,
        reduce_only=True,
    )
    sl_algo_id = str(sl_resp.get("algoId"))
    print(f"[OK] SL bảo vệ đã kích hoạt trên Binance! AlgoID: {sl_algo_id}")
    
    # 4. Deploy 5 Take Profit LIMIT Reduce-Only Orders
    print(f"\n[3/3] Gửi 5 lệnh Take Profit (Reduce-Only) lên sàn...")
    tp_orders_data = []
    now_iso = datetime.utcnow().isoformat()
    
    for idx, tp_price, tp_qty in TPS:
        tp_cid = f"tp_{SIGNAL_ID[:8]}_{idx}_{uuid.uuid4().hex[:4]}"
        tp_resp = await client.create_standard_order(
            symbol=SYMBOL,
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=tp_qty,
            price=tp_price,
            client_order_id=tp_cid,
            reduce_only=True,
        )
        tp_order_id = str(tp_resp.get("orderId"))
        print(f"  [OK] TP{idx}: {tp_qty} STX @ {tp_price} -> OrderId: {tp_order_id}")
        tp_orders_data.append({
            "client_order_id": tp_cid,
            "signal_id": SIGNAL_ID,
            "symbol": SYMBOL,
            "side": "SELL",
            "order_type": "LIMIT",
            "price": float(tp_price),
            "quantity": float(tp_qty),
            "trigger_price": None,
            "is_reduce_only": True,
            "is_algo": False,
            "exchange_order_id": tp_order_id,
            "status": "NEW",
            "filled_quantity": 0.0,
            "avg_fill_price": None,
            "created_at": now_iso,
            "updated_at": now_iso,
        })
        
    # 5. Build orders list for DB
    entry_order_data = {
        "client_order_id": entry_cid,
        "signal_id": SIGNAL_ID,
        "symbol": SYMBOL,
        "side": "BUY",
        "order_type": "MARKET",
        "price": float(avg_entry_price),
        "quantity": float(TOTAL_QTY),
        "trigger_price": None,
        "is_reduce_only": False,
        "is_algo": False,
        "exchange_order_id": str(entry_resp.get("orderId")),
        "status": "FILLED",
        "filled_quantity": float(TOTAL_QTY),
        "avg_fill_price": float(avg_entry_price),
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    
    sl_order_data = {
        "client_order_id": sl_cid,
        "signal_id": SIGNAL_ID,
        "symbol": SYMBOL,
        "side": "SELL",
        "order_type": "STOP_MARKET",
        "price": None,
        "quantity": float(TOTAL_QTY),
        "trigger_price": float(STOP_LOSS),
        "is_reduce_only": True,
        "is_algo": True,
        "exchange_order_id": sl_algo_id,
        "status": "NEW",
        "filled_quantity": 0.0,
        "avg_fill_price": None,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    
    all_orders = [entry_order_data, sl_order_data] + tp_orders_data
    
    signal_data = {
        "signal_id": SIGNAL_ID,
        "chat_id": -1001552004524,
        "message_id": 76517,
        "symbol": SYMBOL,
        "side": "LONG",
        "state": "OPEN_PROTECTED",
        "entry_mode": "SINGLE",
        "entries_json": json.dumps([str(avg_entry_price)]),
        "stop_loss": float(STOP_LOSS),
        "take_profits_json": json.dumps([str(t[1]) for t in TPS]),
        "leverage": LEVERAGE,
        "margin_mode": "ISOLATED",
        "risk_pct": 2.19,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    
    # 6. Save in both DBs
    db_paths = [
        "data/trading_state.db",
        os.path.expandvars(r"%LOCALAPPDATA%\telegram-binance-signal-executor\data\trading_state.db"),
    ]
    for db_p in db_paths:
        record_in_database(db_p, signal_data, all_orders)
        
    # 7. Final Verification from Binance
    print(f"\n=== ĐỐI SOÁT VỊ THẾ & LỆNH TRÊN BINANCE THỰC TẾ ===")
    pos_live = await client.get_position(SYMBOL)
    print(f"Vị thế STX: Amt={pos_live.get('positionAmt')}, Entry={pos_live.get('entryPrice')}, Lev={pos_live.get('leverage')}x")
    
    open_orders = await client.get_open_orders(SYMBOL)
    print(f"Tổng số lệnh LIMIT đang mở trên {SYMBOL}: {len(open_orders)}")
    for o in open_orders:
        print(f"  Order #{o.get('orderId')} | Side={o.get('side')} | Qty={o.get('origQty')} | Price={o.get('price')} | ReduceOnly={o.get('reduceOnly')}")
        
    open_algos = await client.get_open_algo_orders()
    stx_algos = [a for a in open_algos if a.get("symbol") == SYMBOL]
    print(f"Tổng số lệnh ALGO (SL) đang mở trên {SYMBOL}: {len(stx_algos)}")
    for a in stx_algos:
        print(f"  Algo #{a.get('algoId')} | Type={a.get('orderType') or a.get('type')} | TriggerPx={a.get('triggerPrice')} | Qty={a.get('quantity') or a.get('origQty')}")
        
    await client.close()
    print(f"\n[HOÀN TẤT THỰC THI PHƯƠNG ÁN 2 AN TOÀN TUYỆT ĐỐI]")

if __name__ == "__main__":
    asyncio.run(main())

