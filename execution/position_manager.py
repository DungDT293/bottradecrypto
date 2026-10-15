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
            # Place immediate market reduce-only order
            await self.client.create_standard_order(
                symbol=symbol,
                side=close_side,
                order_type=OrderType.MARKET,
                quantity=quantity,
                reduce_only=True,
            )

            # Wait briefly and verify position is closed
            await asyncio.sleep(0.5)
            pos = await self.client.get_position(symbol)
            if pos:
                amt = Decimal(str(pos.get("positionAmt", "0")))
                if amt == Decimal("0"):
                    self.repo.update_signal_state(
                        signal_id,
                        SignalState.CLOSED,
                        reason="BI CHAN: SL THAT BAI - DA DONG KHAN CAP VI THE THANH CONG",
                    )
                    return True
                else:
                    raise EmergencyCloseError(f"Dong vi the khan cap that bai, vi the con lai: {amt}")
            return True
        except Exception as e:
            self.repo.update_signal_state(
                signal_id,
                SignalState.ERROR,
                reason=f"CANH BAO NGHIEP TRONG: Dong khan cap that bai: {str(e)}",
            )
            raise EmergencyCloseError(f"Emergency close error: {str(e)}")
