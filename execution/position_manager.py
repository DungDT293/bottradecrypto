import asyncio
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from core.enums import OrderSide, OrderType, PositionSide, SignalState
from core.exceptions import BotTradingError, EmergencyCloseError
from core.models import Position, ValidatedSignal
from storage.database import SignalRepository


class PositionManager:
    """
    Manages active positions with strict safeguards:
    - Exactly one active signal per symbol
    - Rejects entry if manual / non-bot position exists on symbol
    - Emergency close routine if protective SL fails
    """

    def __init__(self, exchange_client: Any, repo: SignalRepository):
        self.client = exchange_client
        self.repo = repo

    async def can_open_new_signal(self, symbol: str) -> Tuple[bool, Optional[str]]:
        # 1. Check local DB for active signals on this symbol
        active = self.repo.get_active_signal_for_symbol(symbol)
        if active:
            return False, f"Da co tin hieu dang hoat dong tren symbol {symbol} (Signal ID: {active['signal_id']})"

        # 2. Check exchange position to verify no foreign/manual positions exist
        pos = await self.client.get_position(symbol)
        if pos:
            amt = Decimal(str(pos.get("positionAmt", "0")))
            if amt != Decimal("0"):
                return False, f"BLOCKED: Phat hien vi the co san tren {symbol} (Amt: {amt}). Bot khong tu tiep quan hoac dong vi the thu cong."

        return True, None

    async def execute_emergency_close(self, symbol: str, quantity: Decimal, side: PositionSide, signal_id: str) -> bool:
        """
        FAIL-SAFE ROUTINE:
        If entry fills but protective SL fails:
        1. Cancels all pending bot entry orders on symbol
        2. Submits MARKET reduceOnly order to close the filled position immediately
        3. Verifies position is 0 on exchange
        """
        # Close side is opposite to position side
        close_side = OrderSide.SELL if side == PositionSide.LONG else OrderSide.BUY

        try:
            if hasattr(self.client, "cancel_all_symbol_orders"):
                try:
                    await self.client.cancel_all_symbol_orders(symbol)
                except Exception:
                    pass
            elif hasattr(self.client, "cancel_all_orders"):
                try:
                    await self.client.cancel_all_orders(symbol)
                except Exception:
                    pass

            close_qty = abs(Decimal(str(quantity)))
            if close_qty <= Decimal("0"):
                try:
                    pos = await self.client.get_position(symbol)
                    if pos:
                        close_qty = abs(Decimal(str(pos.get("positionAmt", "0"))))
                except Exception:
                    pass

            if close_qty <= Decimal("0"):
                self.repo.update_signal_state(
                    signal_id,
                    SignalState.CLOSED,
                    reason="DONG KHAN CAP: Vi the da bang 0",
                )
                return True

            filter_info = None
            try:
                filter_info = await self.client.get_symbol_filter(symbol)
                if filter_info and filter_info.step_size:
                    from risk.risk_engine import RiskEngine
                    close_qty = RiskEngine.round_step_size(close_qty, filter_info.step_size)
            except Exception:
                pass

            min_qty = filter_info.min_qty if filter_info and filter_info.min_qty else Decimal("0")
            for attempt in range(3):
                try:
                    pos = await self.client.get_position(symbol)
                    remaining = abs(Decimal(str(pos.get("positionAmt", "0")))) if pos else Decimal("0")
                    if remaining <= min_qty or remaining == Decimal("0"):
                        self.repo.update_signal_state(
                            signal_id,
                            SignalState.CLOSED,
                            reason="BI CHAN: SL THAT BAI - DA DONG KHAN CAP VI THE THANH CONG",
                        )
                        return True
                    close_qty = remaining
                    if filter_info and filter_info.step_size:
                        from risk.risk_engine import RiskEngine
                        close_qty = RiskEngine.round_step_size(close_qty, filter_info.step_size)
                    if close_qty <= Decimal("0"):
                        break
                    await self.client.create_standard_order(
                        symbol=symbol,
                        side=close_side,
                        order_type=OrderType.MARKET,
                        quantity=close_qty,
                        client_order_id=f"emg_{signal_id[:12]}_{attempt}",
                        reduce_only=True,
                    )
                    await asyncio.sleep(0.5 * (attempt + 1))
                except Exception:
                    if attempt == 2:
                        raise
            raise EmergencyCloseError(f"Dong vi the khan cap that bai, vi the con lai: {close_qty}")
        except Exception as e:
            self.repo.update_signal_state(
                signal_id,
                SignalState.ERROR,
                reason=f"CANH BAO NGHIEP TRONG: Dong khan cap that bai: {str(e)}",
            )
            raise EmergencyCloseError(f"Emergency close error: {str(e)}")
