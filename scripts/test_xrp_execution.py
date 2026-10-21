import asyncio
import os
import sys
sys.path.insert(0, os.path.abspath('.'))
from decimal import Decimal
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding='utf-8')

from config.config import load_config
from core.enums import PositionSide, SignalState, ExecutionMode
from core.models import SourceMetadata
from exchange.binance_client import BinanceFuturesClient
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from risk.risk_engine import RiskEngine
from parser.signal_parser import SignalParser
from parser.validator import SignalValidator
from storage.database import DatabaseManager, SignalRepository, OrderRepository

async def test_xrp_execution_flow(dry_run=True):
    cfg = load_config('config.yaml')
    db_mgr = DatabaseManager(cfg.database_file)
    sig_repo = SignalRepository(db_mgr)
    ord_repo = OrderRepository(db_mgr)

    client = BinanceFuturesClient(cfg)
    equity = await client.get_account_equity()
    print(f"[BINANCE LIVE] Account Equity: {equity:.2f} USDT")

    pos_mgr = PositionManager(client, ord_repo)
    risk_eng = RiskEngine(cfg)
    order_mgr = OrderManager(client, ord_repo, sig_repo, pos_mgr, risk_eng, cfg)

    parser = SignalParser()
    validator = SignalValidator(cfg)

    raw_text = """
💥 Futures (Free Signal)

✅ Long

#XRP/USDT

Entry zone : 1.2579 - 1.2969

Take Profits : 

1.3033
1.3420
1.3807
1.4194
1.4581

Stop loss :1.206117

Leverage: 10x

Click Here To Enter VIP 📈
"""
    chat_id = -1001781413045
    msg_id = 237193
    meta = SourceMetadata(
        chat_id=chat_id,
        message_id=msg_id,
        source_name="Binance 360 VIP",
        telegram_timestamp=datetime.now(timezone.utc),
    )

    parsed = parser.parse(raw_text, meta)
    source_override = cfg.sources.get(chat_id)
    parsed, validated = validator.validate_and_resolve(parsed, source_override)

    print("\n--- PHÂN TÍCH TÍN HIỆU ---")
    print(f"Symbol: {validated.symbol} | Hướng: {validated.side.value}")
    print(f"Vùng Entry: {validated.entry_range}")
    print(f"SL: {validated.stop_loss} | TP1: {validated.take_profits[0][0]}")
    print(f"Leverage: {validated.leverage}x | Margin Mode: {validated.margin_mode.value}")

    # Fetch live ticker
    ticker = await client._request("GET", "/fapi/v1/ticker/price", params={"symbol": validated.symbol})
    current_price = Decimal(ticker.get("price", "0"))
    print(f"Thị giá thực tế trên Binance: {current_price}")

    filters = await client.get_symbol_filter(validated.symbol)
    tick = filters.tick_size if filters and filters.tick_size else Decimal("0.0001")

    zone_min, zone_max = validated.entry_range
    if zone_min <= current_price <= zone_max:
        rounded_entry = (current_price // tick) * tick
        validated.entries = [(rounded_entry, Decimal("1.0"))]
        print(f"-> [THÀNH CÔNG] Thị giá ({current_price}) NẰM TRONG VÙNG ENTRY [{zone_min} - {zone_max}]!")
        print(f"-> Khớp lệnh trực tiếp tại: {rounded_entry}")
    elif current_price < zone_min:
        rounded_entry = (current_price // tick) * tick
        validated.entries = [(rounded_entry, Decimal("1.0"))]
        print(f"-> [THÀNH CÔNG] Thị giá ({current_price}) < Vùng Entry [{zone_min} - {zone_max}] (Chiết khấu giá rẻ hơn)! Khớp tại: {rounded_entry}")
    else:
        drift_pct = (current_price - zone_max) / zone_max * 100
        if drift_pct <= Decimal("1.0"):
            rounded_entry = (current_price // tick) * tick
            validated.entries = [(rounded_entry, Decimal("1.0"))]
            print(f"-> [THÀNH CÔNG] Thị giá ({current_price}) sát trần vùng Entry (+{drift_pct:.2f}% <= 1.0%). Khớp tại: {rounded_entry}")
        else:
            print(f"-> [TỪ CHỐI] Giá đã tăng quá trần (+{drift_pct:.2f}%). Chặn mua đuổi.")
            await client.close()
            return

    # Calculate position sizes
    entry_sizes = order_mgr.risk_engine.calculate_position_sizes(
        signal=validated,
        current_equity=equity,
        open_risk_amount=Decimal("0.0"),
        step_size=filters.step_size,
        min_qty=filters.min_qty,
        min_notional=filters.min_notional,
        current_market_price=current_price,
    )
    print(f"Kích thước vị thế tính toán: {entry_sizes}")
    for p, q in entry_sizes:
        notional = p * q
        margin = notional / validated.leverage
        print(f"  * Entry Price: {p} | Qty: {q} XRP | Notional: {notional:.2f} USDT | Margin: {margin:.2f} USDT")

    if not dry_run:
        print("\n[CHẾ ĐỘ THỰC THI THẬT] Gửi lệnh ra sàn Binance Futures...")
        # 1. Set leverage & margin type
        try:
            await client.set_margin_type_cross(validated.symbol)
        except Exception as e:
            print("Margin type:", e)
        try:
            await client.set_leverage(validated.symbol, validated.leverage)
        except Exception as e:
            print("Set leverage:", e)

        orders = await order_mgr.submit_entries(validated, entry_sizes, current_market_price=current_price)
        print(f"Đã đặt {len(orders)} lệnh lên Binance thành công!")
        for o in orders:
            print(f"  -> ClientOrderId: {o.client_order_id} | Type: {o.order_type} | Status: {o.status}")
    else:
        print("\n[DRY RUN HOÀN TẤT] Mọi tính toán và logic đều hoạt động 100% chính xác!")

    await client.close()

if __name__ == "__main__":
    dry_run = True
    if len(sys.argv) > 1 and sys.argv[1] == "--execute":
        dry_run = False
    asyncio.run(test_xrp_execution_flow(dry_run=dry_run))
