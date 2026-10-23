from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class LedgerSummary:
    realized_pnl: Decimal
    commission_cost: Decimal
    funding_signed: Decimal
    other_cash: Decimal
    cash_flow: Decimal
    net_pnl: Decimal
    event_count: int
    completeness: str


def summarize_events(events: Iterable[dict[str, Any]], *, complete: bool = True) -> LedgerSummary:
    realized = Decimal("0")
    commission_cost = Decimal("0")
    funding = Decimal("0")
    other = Decimal("0")
    cash_flow = Decimal("0")
    count = 0
    for event in events:
        count += 1
        amount = Decimal(str(event["amount"]))
        event_type = str(event.get("event_type", "")).upper()
        if event_type in {"REALIZED_PNL", "TRADE_FILL"}:
            realized += amount
        elif event_type in {"FEE", "COMMISSION"}:
            commission_cost += abs(amount)
        elif event_type in {"FUNDING", "FUNDING_FEE"}:
            funding += amount
        elif event_type in {"DEPOSIT", "WITHDRAWAL", "TRANSFER"}:
            cash_flow += amount
        else:
            other += amount
    net = realized - commission_cost + funding + other
    completeness = "FULL" if complete and count else ("UNKNOWN" if not count else "PARTIAL")
    return LedgerSummary(realized, commission_cost, funding, other, cash_flow, net, count, completeness)


def classify_position_outcome(net_pnl: Decimal, *, tolerance: Decimal = Decimal("0.00000001")) -> str:
    if abs(net_pnl) <= tolerance:
        return "BE"
    return "WIN" if net_pnl > 0 else "LOSS"


def weighted_average(qty_price_pairs: Iterable[tuple[Decimal, Decimal]]) -> Optional[Decimal]:
    total_qty = Decimal("0")
    total_notional = Decimal("0")
    for qty, price in qty_price_pairs:
        if qty <= 0:
            continue
        total_qty += qty
        total_notional += qty * price
    return total_notional / total_qty if total_qty else None
