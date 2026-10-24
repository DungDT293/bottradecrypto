"""
execution/trailing_tp_manager.py
Trụ Cột 3: Trailing Take-Profit Moonbag 30% Manager.
Tối đa hóa lợi nhuận khi coin pump mạnh (Moonbag 30% cuối cùng)
thông qua cơ chế Trailing Stop tự động dời bám theo đỉnh giá trên máy chủ Binance.
"""

import logging
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Optional, Tuple

from core.enums import OrderSide, OrderType, PositionSide
from core.models import Order, ValidatedSignal

logger = logging.getLogger("trailing_tp_manager")


class TrailingTakeProfitManager:
    """
    Manages trailing stop-loss for the final 30% moonbag allocation.
    
    Quy tắc hoạt động:
    1. Khi lệnh đã chốt TP1 (35%) và TP2 (35%), còn lại 30% moonbag.
    2. Nếu giá tiếp tục di chuyển thuận lợi >= 2.0% (pump_threshold_pct):
       Kích hoạt cơ chế Trailing Stop.
    3. Trailing Stop duy trì khoảng cách 1.5% (trail_distance_pct) phía sau đỉnh giá cao nhất (LONG)
       hoặc đáy giá thấp nhất (SHORT).
    4. BẤT BIẾN RỦI RO (Invariant): SL chỉ được phép dời theo chiều có lợi (khóa lãi),
       tuyệt đối KHÔNG BAO GIỜ dời lùi làm tăng rủi ro.
    5. Cập nhật trực tiếp lên Binance Futures thông qua STOP_MARKET Algo Order.
    """

    def __init__(
        self,
        pump_threshold_pct: Decimal = Decimal("2.0"),
        trail_distance_pct: Decimal = Decimal("1.5"),
    ):
        self.pump_threshold_pct = pump_threshold_pct
        self.trail_distance_pct = trail_distance_pct
        # symbol/signal_id -> extreme price tracked
        self._tracked_peaks: Dict[str, Decimal] = {}

    def get_tracked_peak(self, key: str) -> Optional[Decimal]:
        return self._tracked_peaks.get(key)

    def reset_tracked_peak(self, key: str) -> None:
        self._tracked_peaks.pop(key, None)

    def calculate_trailing_stop(
        self,
        side: PositionSide,
        reference_price: Decimal,
        current_mark_price: Decimal,
        current_sl: Decimal,
        key: Optional[str] = None,
    ) -> Tuple[bool, Decimal, str]:
        """
        Pure calculation method for testing and evaluation.
        Returns: (should_update, new_sl_price, rationale)
        """
        track_key = key or "default"
        is_long = (side == PositionSide.LONG or str(side).upper() in ("LONG", "BUY"))

        if is_long:
            # Update tracked highest peak
            highest = self._tracked_peaks.get(track_key, reference_price)
            if current_mark_price > highest:
                highest = current_mark_price
                self._tracked_peaks[track_key] = highest

            # Check pump threshold (>= 2.0% above reference price)
            gain_pct = ((highest - reference_price) / reference_price) * Decimal("100")
            if gain_pct < self.pump_threshold_pct:
                return False, current_sl, f"Chưa đạt ngưỡng kích hoạt trailing (+{gain_pct:.2f}% < +{self.pump_threshold_pct}%)"

            # Trailing stop price = highest * (1 - trail_distance_pct / 100)
            trail_price = highest * (Decimal("1.0") - (self.trail_distance_pct / Decimal("100")))

            # Invariant: Must strictly lock in higher profit than current SL
            if trail_price > current_sl:
                return (
                    True,
                    trail_price,
                    f"LONG Moonbag trailing: Đỉnh mới {highest:.4f} (+{gain_pct:.2f}%), dời SL lên {trail_price:.4f} (-{self.trail_distance_pct}% sau đỉnh)"
                )
            else:
                return False, current_sl, "Trailing SL tính toán không cao hơn SL hiện tại, giữ nguyên."

        else:
            # SHORT
            lowest = self._tracked_peaks.get(track_key, reference_price)
            if current_mark_price < lowest:
                lowest = current_mark_price
                self._tracked_peaks[track_key] = lowest

            gain_pct = ((reference_price - lowest) / reference_price) * Decimal("100")
            if gain_pct < self.pump_threshold_pct:
                return False, current_sl, f"Chưa đạt ngưỡng kích hoạt trailing (+{gain_pct:.2f}% < +{self.pump_threshold_pct}%)"

            # Trailing stop price = lowest * (1 + trail_distance_pct / 100)
            trail_price = lowest * (Decimal("1.0") + (self.trail_distance_pct / Decimal("100")))

            # Invariant: Must strictly lock in lower price than current SL
            if trail_price < current_sl:
                return (
                    True,
                    trail_price,
                    f"SHORT Moonbag trailing: Đáy mới {lowest:.4f} (+{gain_pct:.2f}%), dời SL xuống {trail_price:.4f} (+{self.trail_distance_pct}% trên đáy)"
                )
            else:
                return False, current_sl, "Trailing SL tính toán không thấp hơn SL hiện tại, giữ nguyên."

    async def update_trailing_moonbag(
        self,
        order_manager: Any,
        signal: ValidatedSignal,
        remaining_qty: Decimal,
        current_mark_price: Decimal,
        existing_sl_algo_id: Optional[str] = None,
        reference_price: Optional[Decimal] = None,
    ) -> Optional[Order]:
        """
        Executes trailing SL order update via order_manager and Binance client.
        """
        if remaining_qty <= Decimal("0"):
            return None

        ref_price = reference_price or (signal.take_profits[1][0] if len(signal.take_profits) >= 2 else signal.entries[0][0])
        key = signal.signal_id

        should_update, new_sl_price, rationale = self.calculate_trailing_stop(
            side=signal.side,
            reference_price=ref_price,
            current_mark_price=current_mark_price,
            current_sl=signal.stop_loss,
            key=key,
        )

        if not should_update:
            return None

        logger.info(f"[MOONBAG TRAILING SL] {signal.symbol} | {rationale}")
        try:
            new_order = await order_manager.move_sl_to_trailing_price(
                signal=signal,
                position_qty=remaining_qty,
                target_price=new_sl_price,
                existing_sl_algo_id=existing_sl_algo_id,
                label="moonbag_trail",
            )
            if new_order:
                signal.stop_loss = new_sl_price
            return new_order
        except Exception as e:
            logger.error(f"[MOONBAG TRAILING ERROR] Không thể dời SL lên {new_sl_price}: {e}")
            return None


global_trailing_tp_manager = TrailingTakeProfitManager()
