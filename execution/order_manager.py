import asyncio
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from config.config import AppConfig
from core.enums import OrderSide, OrderType, PositionSide, SignalState
from core.exceptions import BotTradingError, EmergencyCloseError, ExchangeAdapterError
from core.models import Order, ValidatedSignal
from execution.position_manager import PositionManager
from risk.risk_engine import RiskEngine
from storage.database import OrderRepository, SignalRepository


class OrderManager:
    """
    Manages the lifecycle of standard and algo orders:
    - Submits entry limit orders
    - Submits protective SL via algoOrder endpoint
    - Handles partial fills and TP placement
    - Breakeven SL trailing after TP1
    - FAIL-SAFE: Closes filled position immediately if SL fails
    """

    def __init__(
        self,
        client: Any,
        order_repo: OrderRepository,
        signal_repo: SignalRepository,
        position_manager: PositionManager,
        risk_engine: RiskEngine,
        config: AppConfig,
    ):
        self.client = client
        self.order_repo = order_repo
        self.signal_repo = signal_repo
        self.position_manager = position_manager
        self.risk_engine = risk_engine
        self.config = config

    async def submit_entries(
        self,
        signal: ValidatedSignal,
        entry_sizes: List[Tuple[Decimal, Decimal]],
    ) -> List[Order]:
        """
        Submits entry orders using exchange filters and unique clientOrderIds.
        """
        created_orders: List[Order] = []
        entry_side = OrderSide.BUY if signal.side == PositionSide.LONG else OrderSide.SELL

        for idx, (price, qty) in enumerate(entry_sizes):
            cid = f"ent_{signal.signal_id[:10]}_{idx}_{uuid.uuid4().hex[:4]}"
            order = Order(
                client_order_id=cid,
                signal_id=signal.signal_id,
                symbol=signal.symbol,
                side=entry_side,
                order_type=OrderType.LIMIT,
                price=price,
                quantity=qty,
                is_reduce_only=False,
                is_algo=False,
                status="NEW",
            )
            self.order_repo.save_order(order)

            # Send order to exchange with up to 3 automatic fast retries
            resp = None
            last_err = None
            for attempt in range(1, 4):
                try:
                    resp = await self.client.create_standard_order(
                        symbol=signal.symbol,
                        side=entry_side,
                        order_type=OrderType.LIMIT,
                        quantity=qty,
                        price=price,
                        client_order_id=cid,
                    )
                    break
                except Exception as e_order:
                    last_err = e_order
                    await asyncio.sleep(attempt * 0.4)

            if not resp:
                raise last_err or ExchangeAdapterError(f"Khong the dat lenh {signal.symbol} sau 3 lan thu")

            order.exchange_order_id = str(resp.get("orderId"))
            self.order_repo.save_order(order)
            created_orders.append(order)

        self.signal_repo.update_signal_state(signal.signal_id, SignalState.ENTRY_PENDING)
        return created_orders

    async def on_entry_filled(
        self,
        signal: ValidatedSignal,
        filled_qty: Decimal,
        avg_entry_price: Decimal,
    ) -> Optional[Order]:
        """
        Called when an entry is filled (partially or fully).
        Crucial: Must submit protective Stop Loss via Algo Order API immediately!
        If SL placement fails, triggers FAIL-SAFE emergency close.
        """
        sl_side = OrderSide.SELL if signal.side == PositionSide.LONG else OrderSide.BUY
        sl_cid = f"sl_{signal.signal_id[:10]}_{uuid.uuid4().hex[:4]}"

        sl_price = signal.stop_loss
        if hasattr(self.client, "get_symbol_filter"):
            try:
                f = await self.client.get_symbol_filter(signal.symbol)
                sl_price = (sl_price // f.tick_size) * f.tick_size
                filled_qty = (filled_qty // f.step_size) * f.step_size
            except Exception:
                pass

        sl_order = Order(
            client_order_id=sl_cid,
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            side=sl_side,
            order_type=OrderType.STOP_MARKET,
            trigger_price=sl_price,
            quantity=filled_qty,
            is_reduce_only=True,
            is_algo=True,
            status="NEW",
        )
        self.order_repo.save_order(sl_order)

        # Attempt to place Algo Order SL
        sl_placed = False
        last_error = ""

        # Retry up to 2 times
        for attempt in range(2):
            try:
                resp = await self.client.create_algo_order(
                    symbol=signal.symbol,
                    side=sl_side,
                    order_type=OrderType.STOP_MARKET,
                    trigger_price=sl_price,
                    quantity=filled_qty,
                    client_algo_id=sl_cid,
                    close_position=False,
                )
                sl_order.exchange_order_id = str(resp.get("algoId"))
                self.order_repo.save_order(sl_order)
                sl_placed = True
                break
            except Exception as e:
                last_error = str(e)
                await asyncio.sleep(0.5)

        if not sl_placed:
            # FAIL-SAFE ACTIVATION: Entry filled but SL rejected!
            # 1. Cancel remaining pending entries for this signal
            await self.cancel_pending_entries_for_signal(signal.signal_id, signal.symbol)
            # 2. Immediately emergency close the unprotected filled position
            await self.position_manager.execute_emergency_close(
                symbol=signal.symbol,
                quantity=filled_qty,
                side=signal.side,
                signal_id=signal.signal_id,
            )
            raise EmergencyCloseError(f"Entry fill khong dat duoc SL ({last_error}). Da kich hoat fail-safe dong vi the.")

        # Place Take Profit Limit Orders (Reduce-Only) on Binance
        tp_side = OrderSide.SELL if signal.side == PositionSide.LONG else OrderSide.BUY
        for idx, (tp_price, tp_weight) in enumerate(signal.take_profits):
            tp_qty = filled_qty * tp_weight
            if hasattr(self.client, "get_symbol_filter"):
                try:
                    f = await self.client.get_symbol_filter(signal.symbol)
                    tp_qty = (tp_qty // f.step_size) * f.step_size
                    tp_price = (tp_price // f.tick_size) * f.tick_size
                    if tp_qty < f.min_qty:
                        continue
                except Exception:
                    pass
            if tp_qty <= Decimal("0"):
                continue

            tp_cid = f"tp_{signal.signal_id[:8]}_{idx+1}_{uuid.uuid4().hex[:4]}"
            tp_order = Order(
                client_order_id=tp_cid,
                signal_id=signal.signal_id,
                symbol=signal.symbol,
                side=tp_side,
                order_type=OrderType.LIMIT,
                price=tp_price,
                quantity=tp_qty,
                is_reduce_only=True,
                is_algo=False,
                status="NEW",
            )
            self.order_repo.save_order(tp_order)
            try:
                resp = await self.client.create_standard_order(
                    symbol=signal.symbol,
                    side=tp_side,
                    order_type=OrderType.LIMIT,
                    quantity=tp_qty,
                    price=tp_price,
                    client_order_id=tp_cid,
                    reduce_only=True,
                )
                tp_order.exchange_order_id = str(resp.get("orderId"))
                self.order_repo.save_order(tp_order)
            except Exception as e:
                print(f"[CANH BAO] Khong the gui lenh TP{idx+1} ({tp_price}) len san: {e}")

        self.signal_repo.update_signal_state(signal.signal_id, SignalState.OPEN_PROTECTED)
        return sl_order

    async def cancel_pending_entries_for_signal(self, signal_id: str, symbol: str) -> None:
        orders = self.order_repo.get_orders_for_signal(signal_id)
        for ord in orders:
            if not ord.is_reduce_only and ord.status in ["NEW", "PARTIALLY_FILLED"]:
                try:
                    await self.client.cancel_standard_order(symbol, ord.client_order_id)
                    self.order_repo.update_order_fill(ord.client_order_id, "CANCELED", ord.filled_quantity, ord.avg_fill_price)
                except Exception:
                    pass

    async def move_sl_to_breakeven(
        self,
        signal: ValidatedSignal,
        position_qty: Decimal,
        avg_entry_price: Decimal,
        existing_sl_algo_id: Optional[str] = None,
    ) -> Order:
        """
        Moves SL to breakeven (entry price + fee buffer) after TP1:
        1. Cancels remaining pending entries
        2. Submits new BE Algo SL
        3. Once confirmed, cancels old SL
        """
        # Cancel remaining pending entries
        await self.cancel_pending_entries_for_signal(signal.signal_id, signal.symbol)

        # Calculate BE price including fee buffer
        fee_mult = self.config.risk.fee_buffer_pct / Decimal("100")
        if signal.side == PositionSide.LONG:
            be_price = avg_entry_price * (Decimal("1.0") + fee_mult)
        else:
            be_price = avg_entry_price * (Decimal("1.0") - fee_mult)

        sl_side = OrderSide.SELL if signal.side == PositionSide.LONG else OrderSide.BUY
        new_sl_cid = f"be_{signal.signal_id[:10]}_{uuid.uuid4().hex[:4]}"

        if hasattr(self.client, "get_symbol_filter"):
            try:
                f = await self.client.get_symbol_filter(signal.symbol)
                be_price = (be_price // f.tick_size) * f.tick_size
                position_qty = (position_qty // f.step_size) * f.step_size

                # Guard against Binance -2021: Order would immediately trigger
                pos = await self.client.get_position(signal.symbol)
                if pos and float(pos.get("markPrice", 0)) > 0:
                    current_mark = Decimal(str(pos.get("markPrice")))
                    if signal.side == PositionSide.LONG and be_price >= current_mark:
                        be_price = ((current_mark - (f.tick_size * Decimal("2"))) // f.tick_size) * f.tick_size
                    elif signal.side == PositionSide.SHORT and be_price <= current_mark:
                        be_price = ((current_mark + (f.tick_size * Decimal("2"))) // f.tick_size) * f.tick_size
            except Exception:
                pass

        new_sl = Order(
            client_order_id=new_sl_cid,
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            side=sl_side,
            order_type=OrderType.STOP_MARKET,
            trigger_price=be_price,
            quantity=position_qty,
            is_reduce_only=True,
            is_algo=True,
            status="NEW",
        )

        # Place new Algo SL first
        resp = await self.client.create_algo_order(
            symbol=signal.symbol,
            side=sl_side,
            order_type=OrderType.STOP_MARKET,
            trigger_price=be_price,
            quantity=position_qty,
            client_algo_id=new_sl_cid,
            close_position=False,
        )
        new_sl.exchange_order_id = str(resp.get("algoId"))
        self.order_repo.save_order(new_sl)

        # Cancel old SL if provided
        if existing_sl_algo_id:
            try:
                await self.client.cancel_algo_order(signal.symbol, client_algo_id=existing_sl_algo_id)
            except Exception:
                pass

        return new_sl

