from decimal import Decimal
from typing import Any, Dict, List
from core.enums import SignalState
from core.exceptions import ReconciliationError
from storage.database import DatabaseManager, OrderRepository, SignalRepository


class ReconciliationEngine:
    """
    State reconciliation between Local SQLite DB and Binance USD-M Futures.
    Ensures that restarting the bot does not open duplicate orders or leave orphaned orders.
    """

    def __init__(self, exchange_client: Any, db: DatabaseManager):
        self.client = exchange_client
        self.signal_repo = SignalRepository(db)
        self.order_repo = OrderRepository(db)

    async def reconcile_all(self) -> Dict[str, Any]:
        report: Dict[str, Any] = {
            "account_one_way": False,
            "equity": "0",
            "active_signals_checked": 0,
            "orphaned_cleaned": 0,
            "discrepancies": [],
        }

        # 1. Verify One-Way Position Mode
        await self.client.check_position_mode_one_way()
        report["account_one_way"] = True

        equity = await self.client.get_account_equity()
        report["equity"] = str(equity)

        # 2. Check active signals from local DB
        with self.signal_repo.db.get_connection() as conn:
            active_rows = conn.execute(
                """
                SELECT * FROM signals
                WHERE state IN ('ENTRY_PENDING', 'PARTIALLY_FILLED', 'OPEN_PROTECTED', 'EXITING')
                """
            ).fetchall()

        for row in active_rows:
            report["active_signals_checked"] += 1
            sig_id = row["signal_id"]
            symbol = row["symbol"]
            state = row["state"]

            # Query exchange position
            pos = await self.client.get_position(symbol)
            amt = Decimal(str(pos.get("positionAmt", "0"))) if pos else Decimal("0")

            if state in ["OPEN_PROTECTED", "PARTIALLY_FILLED"] and amt == Decimal("0"):
                # Position was closed outside or hit SL/TP while bot was offline
                report["discrepancies"].append(
                    f"Vi the {symbol} da dong tren san (amt=0) nhung local dang o {state}. Cap nhat sang CLOSED."
                )
                # Clean remaining orders
                orders = self.order_repo.get_orders_for_signal(sig_id)
                for ord in orders:
                    if ord.status in ["NEW", "PARTIALLY_FILLED"]:
                        try:
                            if ord.is_algo:
                                await self.client.cancel_algo_order(symbol, client_algo_id=ord.client_order_id)
                            else:
                                await self.client.cancel_standard_order(symbol, ord.client_order_id)
                            report["orphaned_cleaned"] += 1
                        except Exception:
                            pass
                self.signal_repo.update_signal_state(
                    sig_id,
                    SignalState.CLOSED,
                    reason="Doi chieu: Vi the da dong tren san trong luc bot offline",
                )

        return report

