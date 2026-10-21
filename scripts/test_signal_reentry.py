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

async def test_signal_execution(raw_text, chat_id, msg_id, source_name, execute=False):
    cfg = load_config('config.yaml')
    db_path = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db')
    if not os.path.exists(db_path):
        db_path = cfg.database_file
    db_mgr = DatabaseManager(db_path)
    sig_repo = SignalRepository(db_mgr)
    ord_repo = OrderRepository(db_mgr)

    client = BinanceFuturesClient(cfg)
    equity = await client.get_account_equity()

    pos_mgr = PositionManager(client, ord_repo)
    risk_eng = RiskEngine(cfg)
    order_mgr = OrderManager(client, ord_repo, sig_repo, pos_mgr, risk_eng, cfg)

    parser = SignalParser()
    validator = SignalValidator(cfg)

    meta = SourceMetadata(
        chat_id=chat_id,
        message_id=msg_id,
        source_name=source_name,
        telegram_timestamp=datetime.now(timezone.utc),
    )

    parsed = parser.parse(raw_text, meta)
    sig_repo.save_signal(parsed)
    source_override = cfg.sources.get(chat_id)
    parsed, validated = validator.validate_and_resolve(parsed, source_override)
    sig_repo.save_signal(parsed)

    print(f"\n=======================================================")
    print(f"KIỂM ĐỊNH THỰC TẾ: {validated.symbol} {validated.side.value}")
    print(f"Admin: {source_name} | Vùng Entry: {validated.entry_range}")
    print(f"SL: {validated.stop_loss} | TP1: {validated.take_profits[0][0]}")

    ticker = await client._request("GET", "/fapi/v1/ticker/price", params={"symbol": validated.symbol})
    current_price = Decimal(ticker.get("price", "0"))
    print(f"Thị giá live Binance: {current_price}")

    filters = await client.get_symbol_filter(validated.symbol)
    tick = filters.tick_size if filters and filters.tick_size else Decimal("0.0001")

    zone_min, zone_max = validated.entry_range if validated.entry_range else (validated.entries[0][0], validated.entries[0][0])
    can_proceed = False

    if validated.side == PositionSide.LONG:
        if zone_min <= current_price <= zone_max:
            rounded_entry = (current_price // tick) * tick
            validated.entries = [(rounded_entry, Decimal("1.0"))]
            print(f"-> [THÀNH CÔNG] Giá {current_price} NẰM TRONG VÙNG ENTRY [{zone_min} - {zone_max}]. Khớp tại {rounded_entry}!")
            can_proceed = True
        elif current_price < zone_min:
            rounded_entry = (current_price // tick) * tick
            validated.entries = [(rounded_entry, Decimal("1.0"))]
            print(f"-> [THÀNH CÔNG] Giá {current_price} < Vùng Entry [{zone_min} - {zone_max}] (Chiết khấu giá rẻ hơn)! Khớp tại {rounded_entry}!")
            can_proceed = True
        else:
            drift = (current_price - zone_max) / zone_max * 100
            if drift <= Decimal("1.0"):
                rounded_entry = (current_price // tick) * tick
                validated.entries = [(rounded_entry, Decimal("1.0"))]
                print(f"-> [THÀNH CÔNG] Giá {current_price} sát trần vùng Entry (+{drift:.2f}% <= 1%). Khớp tại {rounded_entry}!")
                can_proceed = True
            else:
                print(f"-> [TỪ CHỐI] Giá vượt trần (+{drift:.2f}%). Chặn mua đuổi.")
    elif validated.side == PositionSide.SHORT:
        if zone_min <= current_price <= zone_max:
            rounded_entry = (current_price // tick) * tick
            validated.entries = [(rounded_entry, Decimal("1.0"))]
            print(f"-> [THÀNH CÔNG] Giá {current_price} NẰM TRONG VÙNG ENTRY [{zone_min} - {zone_max}]. Khớp SHORT tại {rounded_entry}!")
            can_proceed = True
        elif current_price > zone_max:
            rounded_entry = (current_price // tick) * tick
            validated.entries = [(rounded_entry, Decimal("1.0"))]
            print(f"-> [THÀNH CÔNG] Giá {current_price} > Vùng Entry [{zone_min} - {zone_max}] (Bán được giá cao hơn)! Khớp SHORT tại {rounded_entry}!")
            can_proceed = True
        else:
            drift = (zone_min - current_price) / zone_min * 100
            if drift <= Decimal("1.0"):
                rounded_entry = (current_price // tick) * tick
                validated.entries = [(rounded_entry, Decimal("1.0"))]
                print(f"-> [THÀNH CÔNG] Giá {current_price} sát đáy vùng Entry (-{drift:.2f}% <= 1%). Khớp SHORT tại {rounded_entry}!")
                can_proceed = True
            else:
                print(f"-> [TỪ CHỐI] Giá giảm quá đáy (-{drift:.2f}%). Chặn bán đuổi.")

    if can_proceed:
        entry_sizes = order_mgr.risk_engine.calculate_position_sizes(
            signal=validated,
            current_equity=equity,
            open_risk_amount=Decimal("0.0"),
            step_size=filters.step_size,
            min_qty=filters.min_qty,
            min_notional=filters.min_notional,
            current_market_price=current_price,
        )
        print(f"Entry sizes: {entry_sizes}")
        for p, q in entry_sizes:
            notional = p * q
            margin = notional / validated.leverage
            print(f"  * Entry: {p} | Qty: {q} | Notional: {notional:.2f} USDT | Margin: {margin:.2f} USDT")

        if execute:
            print("\n[THỰC THI THẬT] Đặt lệnh lên sàn Binance...")
            try:
                await client.set_margin_type_cross(validated.symbol)
            except Exception:
                pass
            try:
                await client.set_leverage(validated.symbol, validated.leverage)
            except Exception:
                pass
            orders = await order_mgr.submit_entries(validated, entry_sizes, current_market_price=current_price)
            print(f"-> Đã đặt thành công {len(orders)} lệnh lên sàn!")
            for o in orders:
                print(f"   OrderId: {o.client_order_id} | Type: {o.order_type} | Qty: {o.quantity}")
        else:
            print("-> [DRY RUN] Sẵn sàng thực thi khi người dùng xác nhận!")

    await client.close()

if __name__ == "__main__":
    exec_flag = "--execute" in sys.argv
    # Test XRPUSDT
    xrp_text = '''
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
'''
    asyncio.run(test_signal_execution(xrp_text, -1001781413045, 237193, "Binance 360 VIP", execute=exec_flag))

    # Test CTRUSDT (commented out for now, test XRP first)
    # ctr_text = '''
    # ...
    # '''
    # asyncio.run(test_signal_execution(ctr_text, -1001781413045, 237144, "Binance 360 VIP", execute=exec_flag))
