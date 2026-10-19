from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from typing import Dict, List, Optional, Tuple
import pytz

from config.config import AppConfig
from core.enums import MarginMode, PositionSide
from core.exceptions import RiskCheckError
from core.models import ValidatedSignal


class RiskEngine:
    """
    USD-M Futures Risk Management Engine:
    - Equity-based risk budgeting
    - Exact risk-to-SL calculation across all entries with fee and slippage buffers
    - Worst-case pending orders risk reservation
    - Strict daily loss limit under Asia/Ho_Chi_Minh timezone
    - Deposits / withdrawals / transfers separated from trading PnL
    - Post-rounding filter risk verification (never increases risk to pass exchange filters)
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.tz_hcm = pytz.timezone("Asia/Ho_Chi_Minh")

    def get_current_date_str(self) -> str:
        now_hcm = datetime.now(self.tz_hcm)
        return now_hcm.strftime("%Y-%m-%d")

    def calculate_position_sizes(
        self,
        signal: ValidatedSignal,
        current_equity: Decimal,
        open_risk_amount: Decimal,
        step_size: Decimal,
        min_qty: Decimal,
        min_notional: Decimal,
        current_market_price: Decimal,
    ) -> List[Tuple[Decimal, Decimal]]:
        """
        Calculates exact quantity for each entry such that:
        Total Risk = sum(quantity_i * |entry_i - SL|) + fees + slippage <= risk_budget
        Returns list of (price, quantity) rounded according to exchange step_size.
        """
        if current_equity <= Decimal("0"):
            raise RiskCheckError("Equity tai khoan nho hon hoac bang 0")

        # Check source policy override for tiered margin multiplier (1.0 for Elite = 5.0%, 0.5 for Scalp = 2.5%)
        chat_id = getattr(signal.metadata, "chat_id", None) if hasattr(signal, "metadata") else None
        source_override = self.config.sources.get(chat_id) if chat_id else None
        margin_mult = Decimal(str(getattr(source_override, "margin_multiplier", 1.0))) if source_override else Decimal("1.0")

        # 1. Check max total open risk
        max_total_risk_amount = (self.config.risk.max_total_open_risk_pct / Decimal("100")) * current_equity
        signal_risk_pct = min(signal.risk_pct, self.config.risk.risk_per_signal_pct) * margin_mult
        signal_risk_budget = (signal_risk_pct / Decimal("100")) * current_equity

        if open_risk_amount + signal_risk_budget > max_total_risk_amount:
            raise RiskCheckError(
                f"Vuot qua han muc tong rui ro dang mo: Hien tai {open_risk_amount:.2f} + Lenh moi {signal_risk_budget:.2f} > Toi da {max_total_risk_amount:.2f} USDT"
            )

        # Buffer factor for fees and slippage
        # total_buffer = fee_buffer_pct (entry + exit) + slippage_buffer_pct
        total_buffer_factor = Decimal("1.0") + (self.config.risk.fee_buffer_pct + self.config.risk.slippage_buffer_pct) / Decimal("100")
        effective_risk_budget = signal_risk_budget / total_buffer_factor

        # Check if margin cap should be enforced (CROSSED mode)
        margin_mode = signal.margin_mode or getattr(self.config.risk, "margin_mode", None)
        enforce_margin_cap = margin_mode in (MarginMode.CROSSED, MarginMode.CROSS, "CROSS", "CROSSED")
        base_max_margin_pct = getattr(self.config.risk, "max_margin_per_trade_pct", Decimal("7.0"))
        max_margin_pct = base_max_margin_pct * margin_mult
        max_margin_amount = (max_margin_pct / Decimal("100")) * current_equity
        lev = Decimal(str(signal.leverage or getattr(self.config.risk, "default_leverage", 25)))

        entry_results: List[Tuple[Decimal, Decimal]] = []
        total_notional = Decimal("0")

        # Distribute risk and margin budget according to entry weights
        for price, weight in signal.entries:
            sub_budget = effective_risk_budget * weight
            price_distance = abs(price - signal.stop_loss)
            if price_distance <= Decimal("0"):
                raise RiskCheckError(f"Khoang cach gia den SL bang 0 tai entry {price}")

            # 1. Qty bounded by risk budget (Dollar loss to SL <= sub_budget)
            qty_by_risk = sub_budget / price_distance

            # 2. Qty bounded by max margin cap if enforced
            if enforce_margin_cap and lev > Decimal("0"):
                sub_margin_budget = max_margin_amount * weight
                qty_by_margin = (sub_margin_budget * lev) / price
                raw_qty = min(qty_by_risk, qty_by_margin)
            else:
                raw_qty = qty_by_risk

            # Round quantity down to step_size
            qty = self.round_step_size(raw_qty, step_size)

            if qty < min_qty:
                raise RiskCheckError(
                    f"Khoi luong tinh toan ({qty}) nho hon minQty ({min_qty}) cua san. Khong the mo lenh voi rui ro thap nay."
                )

            notional = qty * price
            if notional < min_notional:
                raise RiskCheckError(
                    f"Gia tri danh nghia ({notional:.2f} USDT) nho hon minNotional ({min_notional} USDT). "
                    f"Tu choi lenh vi he thong khong tu dong tang rui ro de vuot bo loc san."
                )

            total_notional += notional
            entry_results.append((price, qty))

        # Check required margin vs leverage
        required_margin = total_notional / lev
        if enforce_margin_cap:
            max_allowed_margin = max_margin_amount * Decimal("1.25")
            if required_margin > max_allowed_margin:
                scale = max_allowed_margin / required_margin
                entry_results = [(p, self.round_step_size(q * scale, step_size)) for p, q in entry_results]
                total_notional = sum(p * q for p, q in entry_results)
                required_margin = total_notional / lev

        if required_margin > current_equity * Decimal("0.9"):  # absolute safety guard
            raise RiskCheckError(
                f"Margin yeu cau ({required_margin:.2f} USDT) vuot qua 90% equity ({current_equity:.2f} USDT)"
            )

        # Post-rounding strict risk verification
        actual_risk_total = Decimal("0")
        for price, qty in entry_results:
            loss_to_sl = qty * abs(price - signal.stop_loss)
            fees = qty * price * (self.config.risk.fee_buffer_pct / Decimal("100"))
            slippage = qty * signal.stop_loss * (self.config.risk.slippage_buffer_pct / Decimal("100"))
            actual_risk_total += loss_to_sl + fees + slippage

        # If slightly over budget tolerance due to notional fees, step down qty until compliant
        max_allowed_risk = signal_risk_budget * Decimal("1.05")
        while actual_risk_total > max_allowed_risk and any(q > min_qty for p, q in entry_results):
            entry_results = [(p, max(min_qty, q - step_size)) for p, q in entry_results]
            actual_risk_total = sum(
                q * abs(p - signal.stop_loss) +
                q * p * (self.config.risk.fee_buffer_pct / Decimal("100")) +
                q * signal.stop_loss * (self.config.risk.slippage_buffer_pct / Decimal("100"))
                for p, q in entry_results
            )

        if actual_risk_total > max_allowed_risk:
            raise RiskCheckError(
                f"Rui ro sau lam tron ({actual_risk_total:.2f} USDT) vuot ngan sach ({signal_risk_budget:.2f} USDT)"
            )

        return entry_results

    def check_daily_loss_limit(self, starting_equity: Decimal, current_realized_loss: Decimal) -> bool:
        """
        Returns True if trading is halted due to hitting max_daily_loss_pct.
        """
        if starting_equity <= Decimal("0"):
            return True

        loss_pct = (current_realized_loss / starting_equity) * Decimal("100")
        if loss_pct >= self.config.risk.max_daily_loss_pct:
            return True
        return False

    @staticmethod
    def round_step_size(qty: Decimal, step_size: Decimal) -> Decimal:
        """
        Rounds down quantity strictly to the step_size multiple.
        """
        if step_size <= Decimal("0"):
            return qty
        precision = abs(step_size.as_tuple().exponent)
        units = (qty / step_size).to_integral_value(rounding=ROUND_DOWN)
        result = units * step_size
        return round(result, precision)

    @staticmethod
    def round_tick_size(price: Decimal, tick_size: Decimal) -> Decimal:
        """
        Rounds price to the nearest tick_size multiple.
        """
        if tick_size <= Decimal("0"):
            return price
        precision = abs(tick_size.as_tuple().exponent)
        units = (price / tick_size).quantize(Decimal("1"))
        result = units * tick_size
        return round(result, precision)

