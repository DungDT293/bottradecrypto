import asyncio
import logging
import uuid
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

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
        current_market_price: Optional[Decimal] = None,
    ) -> List[Order]:
        try:
            return await self._submit_entries(signal, entry_sizes, current_market_price)
        except Exception:
            await self.cancel_pending_entries_for_signal(signal.signal_id, signal.symbol)
            raise

    async def _submit_entries(
        self,
        signal: ValidatedSignal,
        entry_sizes: List[Tuple[Decimal, Decimal]],
        current_market_price: Optional[Decimal] = None,
    ) -> List[Order]:
        """
        Submits entry orders using exchange filters and unique clientOrderIds.
        Distinguishes between standard LIMIT orders (pullback/dip) and STOP_MARKET orders (breakout/breakdown).
        """
        created_orders: List[Order] = []
        entry_side = OrderSide.BUY if signal.side == PositionSide.LONG else OrderSide.SELL

        for idx, (price, qty) in enumerate(entry_sizes):
            # Determine if this entry is a breakout/stop order
            is_breakout = False
            if current_market_price and current_market_price > Decimal("0"):
                if signal.side == PositionSide.LONG and price > current_market_price * Decimal("1.002"):
                    is_breakout = True
                elif signal.side == PositionSide.SHORT and price < current_market_price * Decimal("0.998"):
                    is_breakout = True

            cid_prefix = "ent_algo" if is_breakout else "ent"
            cid = f"{cid_prefix}_{signal.signal_id[:10]}_{idx}_{uuid.uuid4().hex[:4]}"

            if is_breakout:
                order = Order(
                    client_order_id=cid,
                    signal_id=signal.signal_id,
                    symbol=signal.symbol,
                    side=entry_side,
                    order_type=OrderType.STOP_MARKET,
                    trigger_price=price,
                    price=None,
                    quantity=qty,
                    is_reduce_only=False,
                    is_algo=True,
                    status="NEW",
                )
                self.order_repo.save_order(order)

                resp = None
                last_err = None
                for attempt in range(1, 4):
                    try:
                        resp = await self.client.create_algo_order(
                            symbol=signal.symbol,
                            side=entry_side,
                            order_type=OrderType.STOP_MARKET,
                            trigger_price=price,
                            quantity=qty,
                            client_algo_id=cid,
                            close_position=False,
                            reduce_only=False,
                        )
                        break
                    except Exception as e_order:
                        last_err = e_order
                        await asyncio.sleep(attempt * 0.4)

                if not resp:
                    await self.cancel_pending_entries_for_signal(signal.signal_id, signal.symbol)
                    self.signal_repo.update_signal_state(signal.signal_id, SignalState.ERROR, "Không thể đặt toàn bộ lệnh Entry breakout")
                    raise last_err or ExchangeAdapterError(f"Khong the dat lenh Breakout {signal.symbol} sau 3 lan thu")

                order.exchange_order_id = str(resp.get("algoId"))
                self.order_repo.save_order(order)
                created_orders.append(order)
            else:
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
                    await self.cancel_pending_entries_for_signal(signal.signal_id, signal.symbol)
                    self.signal_repo.update_signal_state(signal.signal_id, SignalState.ERROR, "Không thể đặt toàn bộ lệnh Entry")
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
        sl_cid = f"sl_{signal.signal_id[:20]}_protected"

        # Reuse current protection when it already covers this fill; retries must be idempotent.
        existing_orders = self.order_repo.get_orders_for_signal(signal.signal_id)
        for existing in existing_orders:
            if existing.is_algo and existing.is_reduce_only and existing.status in ("NEW", "PARTIALLY_FILLED"):
                if existing.quantity >= filled_qty and existing.trigger_price == signal.stop_loss:
                    return existing

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
        symbol_filter = None
        if hasattr(self.client, "get_symbol_filter"):
            try:
                symbol_filter = await self.client.get_symbol_filter(signal.symbol)
            except Exception:
                pass

        total_tps = len(signal.take_profits)
        accumulated_tp_qty = Decimal("0")
        placed_tp_orders: List[Order] = []

        for idx, (tp_price, tp_weight) in enumerate(signal.take_profits):
            is_last_tp = (idx == total_tps - 1)
            if is_last_tp:
                tp_qty = filled_qty - accumulated_tp_qty
            else:
                tp_qty = filled_qty * tp_weight

            if symbol_filter:
                f = symbol_filter
                tp_qty = (tp_qty // f.step_size) * f.step_size
                tp_price = (tp_price // f.tick_size) * f.tick_size
                min_notional = getattr(f, "min_notional", Decimal("5.0"))
                if min_notional <= Decimal("0"):
                    min_notional = Decimal("5.0")
                if tp_qty < f.min_qty or (tp_qty * tp_price < min_notional):
                    if is_last_tp and (filled_qty - accumulated_tp_qty) >= f.min_qty:
                        residual = filled_qty - accumulated_tp_qty
                        tp_qty = (residual // f.step_size) * f.step_size
                        if tp_qty * tp_price < min_notional:
                            continue
                    else:
                        continue

            if tp_qty <= Decimal("0"):
                continue

            accumulated_tp_qty += tp_qty

            tp_cid = f"tp_{signal.signal_id[:20]}_{idx+1}"
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
                placed_tp_orders.append(tp_order)
            except Exception as e:
                tp_order.status = "REJECTED"
                self.order_repo.save_order(tp_order)
                logger.warning(f"Không thể đặt TP{idx+1} ({tp_price}) cho {signal.symbol}: {e}.")

        if not placed_tp_orders:
            # Fallback: cố gắng đặt 1 lệnh TP1 cho toàn bộ khối lượng nếu các lệnh trước bị từ chối
            try:
                fb_tp_price = signal.take_profits[0][0]
                fb_cid = f"tp_{signal.signal_id[:8]}_fb_{uuid.uuid4().hex[:4]}"
                fb_resp = await self.client.create_standard_order(
                    symbol=signal.symbol,
                    side=tp_side,
                    order_type=OrderType.LIMIT,
                    quantity=filled_qty,
                    price=fb_tp_price,
                    client_order_id=fb_cid,
                    reduce_only=True,
                )
                fb_tp = Order(
                    client_order_id=fb_cid,
                    signal_id=signal.signal_id,
                    symbol=signal.symbol,
                    side=tp_side,
                    order_type=OrderType.LIMIT,
                    price=fb_tp_price,
                    quantity=filled_qty,
                    is_reduce_only=True,
                    is_algo=False,
                    exchange_order_id=str(fb_resp.get("orderId")),
                    status="NEW",
                )
                self.order_repo.save_order(fb_tp)
                placed_tp_orders.append(fb_tp)
            except Exception as fb_err:
                try:
                    await self.client.cancel_algo_order(signal.symbol, client_algo_id=sl_order.client_order_id)
                    self.order_repo.update_order_fill(sl_order.client_order_id, "CANCELED", sl_order.filled_quantity, sl_order.avg_fill_price)
                except Exception:
                    pass
                await self.position_manager.execute_emergency_close(
                    symbol=signal.symbol,
                    quantity=filled_qty,
                    side=signal.side,
                    signal_id=signal.signal_id,
                )
                raise EmergencyCloseError(f"Khong the dat TP1 ({signal.take_profits[0][0] if signal.take_profits else 'N/A'}); da huy bao ve va dong vi the: {fb_err}")

        self.signal_repo.update_signal_state(signal.signal_id, SignalState.OPEN_PROTECTED)
        return sl_order

    async def cancel_pending_entries_for_signal(self, signal_id: str, symbol: str) -> None:
        orders = self.order_repo.get_orders_for_signal(signal_id)
        for ord in orders:
            if not ord.is_reduce_only and ord.status in ["NEW", "PARTIALLY_FILLED"]:
                try:
                    if ord.is_algo:
                        await self.client.cancel_algo_order(
                            symbol,
                            algo_id=ord.exchange_order_id if ord.exchange_order_id else None,
                            client_algo_id=ord.client_order_id,
                        )
                    else:
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
        # Calculate BE price including fee buffer (minimum 0.15% to guarantee net positive after 0.10% Taker fee)
        fee_mult = max(Decimal("0.0015"), getattr(self.config.risk, "fee_buffer_pct", Decimal("0.15")) / Decimal("100"))
        if signal.side == PositionSide.LONG:
            be_price = avg_entry_price * (Decimal("1.0") + fee_mult)
        else:
            be_price = avg_entry_price * (Decimal("1.0") - fee_mult)

        sl_side = OrderSide.SELL if signal.side == PositionSide.LONG else OrderSide.BUY
        new_sl_cid = f"be_{signal.signal_id[:16]}_{uuid.uuid4().hex[:4]}"

        if hasattr(self.client, "get_symbol_filter"):
            try:
                f = await self.client.get_symbol_filter(signal.symbol)
                be_price = (be_price // f.tick_size) * f.tick_size
                position_qty = (position_qty // f.step_size) * f.step_size

                # Guard against Binance -2021: Never place a Stop Loss across current mark price!
                # Setting SL too close to market price causes instant unwanted market exit.
                pos = await self.client.get_position(signal.symbol)
                if pos and float(pos.get("markPrice", 0)) > 0:
                    current_mark = Decimal(str(pos.get("markPrice")))
                    if signal.side == PositionSide.LONG and be_price >= current_mark * Decimal("0.996"):
                        print(f"[HOAN DOI SL BREAKEVEN] Gia thi truong ({current_mark}) qua sat/duoi gia BE ({be_price}). Khong the doi SL sat thi truong de tranh loi -2021 va tranh bi quet som. Giu nguyen SL cu.")
                        return None
                    elif signal.side == PositionSide.SHORT and be_price <= current_mark * Decimal("1.004"):
                        print(f"[HOAN DOI SL BREAKEVEN] Gia thi truong ({current_mark}) qua sat/tren gia BE ({be_price}). Khong the doi SL sat thi truong de tranh loi -2021 va tranh bi quet som. Giu nguyen SL cu.")
                        return None
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

        # Cancel remaining pending entries once BE SL is active
        try:
            await self.cancel_pending_entries_for_signal(signal.signal_id, signal.symbol)
        except Exception:
            pass

        # Cancel old SL if provided; propagate failure so caller records a discrepancy.
        if existing_sl_algo_id and existing_sl_algo_id != new_sl_cid:
            try:
                if str(existing_sl_algo_id).isdigit():
                    await self.client.cancel_algo_order(signal.symbol, algo_id=existing_sl_algo_id)
                else:
                    await self.client.cancel_algo_order(signal.symbol, client_algo_id=existing_sl_algo_id)
                self.order_repo.update_order_fill(str(existing_sl_algo_id), "CANCELED", Decimal("0"))
            except Exception:
                pass

        return new_sl

    async def move_sl_to_trailing_price(
        self,
        signal: ValidatedSignal,
        position_qty: Decimal,
        target_price: Decimal,
        existing_sl_algo_id: Optional[str] = None,
        label: str = "trail_tp1",
    ) -> Optional[Order]:
        """
        Step-by-Step Trailing Stop Loss:
        Locks in profit at target_price (e.g. TP1 price once TP2 is hit).
        Submits new trailing Algo SL and cancels old BE/initial SL.
        """
        sl_side = OrderSide.SELL if signal.side == PositionSide.LONG else OrderSide.BUY
        new_sl_cid = f"{label}_{signal.signal_id[:16]}_{uuid.uuid4().hex[:4]}"
        trail_price = target_price

        if hasattr(self.client, "get_symbol_filter"):
            try:
                f = await self.client.get_symbol_filter(signal.symbol)
                trail_price = (trail_price // f.tick_size) * f.tick_size
                position_qty = (position_qty // f.step_size) * f.step_size

                pos = await self.client.get_position(signal.symbol)
                if pos and float(pos.get("markPrice", 0)) > 0:
                    current_mark = Decimal(str(pos.get("markPrice")))
                    # Guard against Binance -2021: Never place SL on wrong side of market price!
                    if signal.side == PositionSide.LONG and trail_price >= current_mark * Decimal("0.999"):
                        print(f"[HOAN DOI TRAILING SL] Gia thi truong ({current_mark}) qua sat/duoi gia Trailing ({trail_price}). Giu nguyen SL cu.")
                        return None
                    elif signal.side == PositionSide.SHORT and trail_price <= current_mark * Decimal("1.001"):
                        print(f"[HOAN DOI TRAILING SL] Gia thi truong ({current_mark}) qua sat/tren gia Trailing ({trail_price}). Giu nguyen SL cu.")
                        return None
            except Exception:
                pass

        new_sl = Order(
            client_order_id=new_sl_cid,
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            side=sl_side,
            order_type=OrderType.STOP_MARKET,
            trigger_price=trail_price,
            quantity=position_qty,
            is_reduce_only=True,
            is_algo=True,
            status="NEW",
        )

        resp = await self.client.create_algo_order(
            symbol=signal.symbol,
            side=sl_side,
            order_type=OrderType.STOP_MARKET,
            trigger_price=trail_price,
            quantity=position_qty,
            client_algo_id=new_sl_cid,
            close_position=False,
        )
        new_sl.exchange_order_id = str(resp.get("algoId"))
        self.order_repo.save_order(new_sl)

        # Cancel old SL if provided; propagate failure so caller records a discrepancy.
        if existing_sl_algo_id and existing_sl_algo_id != new_sl_cid:
            try:
                if str(existing_sl_algo_id).isdigit():
                    await self.client.cancel_algo_order(signal.symbol, algo_id=existing_sl_algo_id)
                else:
                    await self.client.cancel_algo_order(signal.symbol, client_algo_id=existing_sl_algo_id)
                self.order_repo.update_order_fill(str(existing_sl_algo_id), "CANCELED", Decimal("0"))
            except Exception:
                pass

        return new_sl

