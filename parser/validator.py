from decimal import Decimal
from typing import List, Optional, Tuple

from config.config import AppConfig
from config.policy_defaults import SourcePolicyOverride
from core.enums import (
    EntryMode,
    EntryRangePolicy,
    FieldSource,
    MarginMode,
    MultiEntryWeightMode,
    MultiTPWeightMode,
    PositionSide,
    SignalState,
)
from core.exceptions import SignalValidationError
from core.models import ParsedSignal, ValidatedSignal


class SignalValidator:
    """
    Validates logical consistency of parsed signals and resolves policies.
    Enforces strict invariants:
    - LONG: SL < min(entries), TP > max(entries)
    - SHORT: SL > max(entries), TP < min(entries)
    - Resolves multi-entry and multi-tp policies or flags as NEEDS_POLICY
    - Clamps leverage to system maximum (does not copy dangerous 200x)
    """

    def __init__(self, config: AppConfig):
        self.config = config

    def validate_and_resolve(
        self,
        signal: ParsedSignal,
        source_override: Optional[SourcePolicyOverride] = None,
    ) -> Tuple[ParsedSignal, Optional[ValidatedSignal]]:
        # If already marked NEEDS_REVIEW or REJECTED during parsing, return immediately
        if signal.validation_status in [SignalState.NEEDS_REVIEW, SignalState.REJECTED]:
            return signal, None

        # 1. Check Symbol & Basic Fields
        if not signal.symbol_candidate:
            signal.validation_status = SignalState.REJECTED
            signal.blocking_reason = f"Symbol '{signal.symbol_raw}' khong hop le hoac khong co cap USDT"
            return signal, None

        if not signal.side:
            signal.validation_status = SignalState.REJECTED
            signal.blocking_reason = "Khong xac dinh duoc huong lenh"
            return signal, None

        if not signal.entries or not signal.stop_loss or not signal.take_profits:
            signal.validation_status = SignalState.REJECTED
            signal.blocking_reason = "Thieu mot trong cac thong so bat buoc: Entry, SL, TP"
            return signal, None

        # 2. Semantic Logic Checks: SL & TP vs Entry
        min_entry = min(signal.entries)
        max_entry = max(signal.entries)

        if signal.side == PositionSide.LONG:
            if signal.stop_loss >= min_entry:
                signal.validation_status = SignalState.REJECTED
                signal.blocking_reason = f"Logic loi: LONG nhung SL ({signal.stop_loss}) >= Entry thap nhat ({min_entry})"
                return signal, None
            for tp in signal.take_profits:
                if tp <= max_entry:
                    signal.validation_status = SignalState.REJECTED
                    signal.blocking_reason = f"Logic loi: LONG nhung TP ({tp}) <= Entry cao nhat ({max_entry})"
                    return signal, None
        elif signal.side == PositionSide.SHORT:
            if signal.stop_loss <= max_entry:
                signal.validation_status = SignalState.REJECTED
                signal.blocking_reason = f"Logic loi: SHORT nhung SL ({signal.stop_loss}) <= Entry cao nhat ({max_entry})"
                return signal, None
            for tp in signal.take_profits:
                if tp >= min_entry:
                    signal.validation_status = SignalState.REJECTED
                    signal.blocking_reason = f"Logic loi: SHORT nhung TP ({tp}) >= Entry thap nhat ({min_entry})"
                    return signal, None

        # 3. SL Distance Safety Checks
        avg_entry = sum(signal.entries) / len(signal.entries)
        sl_dist_pct = (abs(avg_entry - signal.stop_loss) / avg_entry) * Decimal("100")
        if sl_dist_pct < self.config.execution.min_sl_distance_pct:
            signal.validation_status = SignalState.REJECTED
            signal.blocking_reason = f"Khoang cach SL qua hep ({sl_dist_pct:.2f}% < {self.config.execution.min_sl_distance_pct}%)"
            return signal, None
        if sl_dist_pct > self.config.execution.max_sl_distance_pct:
            signal.validation_status = SignalState.REJECTED
            signal.blocking_reason = f"Khoang cach SL qua xa ({sl_dist_pct:.2f}% > {self.config.execution.max_sl_distance_pct}%)"
            return signal, None

        # 4. Resolve Range Entry Policy
        resolved_entries: List[Tuple[Decimal, Decimal]] = []
        if signal.entry_mode == EntryMode.RANGE:
            range_policy = self.config.execution.entry_range_policy
            if source_override and source_override.allow_range_midpoint:
                range_policy = EntryRangePolicy.MID_POINT

            if range_policy == EntryRangePolicy.NEEDS_POLICY:
                signal.validation_status = SignalState.NEEDS_POLICY
                signal.blocking_reason = "Vung entry (range) can policy duyet truoc khi thuc thi"
                return signal, None
            elif range_policy == EntryRangePolicy.MID_POINT:
                mid_price = (signal.entries[0] + signal.entries[1]) / Decimal("2")
                resolved_entries = [(mid_price, Decimal("1.0"))]
                signal.field_sources["entry_range_resolved"] = FieldSource.GLOBAL_POLICY
            elif range_policy == EntryRangePolicy.BEST_PRICE:
                # For LONG best entry is min; for SHORT best entry is max
                best_price = min(signal.entries) if signal.side == PositionSide.LONG else max(signal.entries)
                resolved_entries = [(best_price, Decimal("1.0"))]
                signal.field_sources["entry_range_resolved"] = FieldSource.GLOBAL_POLICY
            elif range_policy == EntryRangePolicy.SPLIT_2_LIMITS:
                resolved_entries = [(signal.entries[0], Decimal("0.5")), (signal.entries[1], Decimal("0.5"))]
                signal.field_sources["entry_range_resolved"] = FieldSource.GLOBAL_POLICY

        # 5. Resolve Multiple Entry Weights Policy
        elif signal.entry_mode == EntryMode.MULTIPLE:
            if signal.entry_weights:
                resolved_entries = list(zip(signal.entries, signal.entry_weights))
            else:
                weight_policy = self.config.execution.multi_entry_default_weight_mode
                if source_override and source_override.allow_multi_entry_equal_split:
                    weight_policy = MultiEntryWeightMode.EQUAL_QUANTITY

                if weight_policy == MultiEntryWeightMode.NEEDS_POLICY:
                    signal.validation_status = SignalState.NEEDS_POLICY
                    signal.blocking_reason = "Tin co nhieu entry nhung thieu trong so va chua co policy duyet"
                    return signal, None
                elif weight_policy in [MultiEntryWeightMode.EQUAL_QUANTITY, MultiEntryWeightMode.EQUAL_NOTIONAL]:
                    count = len(signal.entries)
                    equal_w = Decimal("1.0") / Decimal(str(count))
                    resolved_entries = [(p, equal_w) for p in signal.entries]
                    signal.field_sources["entry_weights"] = FieldSource.GLOBAL_POLICY
        else:
            # Single entry
            resolved_entries = [(signal.entries[0], Decimal("1.0"))]

        # 6. Resolve Multiple TP Weights Policy
        resolved_tps: List[Tuple[Decimal, Decimal]] = []
        if signal.tp_weights:
            resolved_tps = list(zip(signal.take_profits, signal.tp_weights))
        elif len(signal.take_profits) == 1:
            resolved_tps = [(signal.take_profits[0], Decimal("1.0"))]
        else:
            tp_policy = self.config.execution.multi_tp_default_weight_mode
            if source_override and source_override.allow_tp_equal_split:
                tp_policy = MultiTPWeightMode.EQUAL_SPLIT

            if tp_policy == MultiTPWeightMode.NEEDS_POLICY:
                signal.validation_status = SignalState.NEEDS_POLICY
                signal.blocking_reason = "Tin co nhieu TP nhung thieu ty le chot loi va chua co policy duyet"
                return signal, None
            elif tp_policy == MultiTPWeightMode.EQUAL_SPLIT:
                count = len(signal.take_profits)
                equal_w = Decimal("1.0") / Decimal(str(count))
                resolved_tps = [(p, equal_w) for p in signal.take_profits]
                signal.field_sources["tp_weights"] = FieldSource.GLOBAL_POLICY
            elif tp_policy == MultiTPWeightMode.FRONT_LOADED_50_30_20:
                if len(signal.take_profits) == 3:
                    weights = [Decimal("0.5"), Decimal("0.3"), Decimal("0.2")]
                    resolved_tps = list(zip(signal.take_profits, weights))
                    signal.field_sources["tp_weights"] = FieldSource.GLOBAL_POLICY
                else:
                    signal.validation_status = SignalState.NEEDS_POLICY
                    signal.blocking_reason = "Chinh sach FRONT_LOADED_50_30_20 chi ap dung cho 3 TP"
                    return signal, None

        # 7. Clamp Leverage
        max_allowed_lev = self.config.risk.max_leverage
        if source_override and source_override.max_leverage_override:
            max_allowed_lev = min(max_allowed_lev, source_override.max_leverage_override)

        # Select leverage: never pick highest of range, take lower or default
        if signal.leverage_range:
            chosen_lev = signal.leverage_range[0]  # lower bound of range
        elif signal.leverage_requested:
            chosen_lev = signal.leverage_requested
        else:
            chosen_lev = self.config.risk.default_leverage

        # Clamp to max policy (e.g. 200X clamped to 5X)
        final_leverage = min(chosen_lev, max_allowed_lev)
        if final_leverage != signal.leverage_requested:
            signal.warnings.append(f"Don bay yeu cau ({signal.leverage_requested}x) duoc ap tran an toan thanh {final_leverage}x")

        # 8. Force ISOLATED margin mode per requirement
        final_margin_mode = MarginMode.ISOLATED
        if signal.margin_mode_requested and signal.margin_mode_requested != MarginMode.ISOLATED:
            signal.warnings.append("Che do margin duoc chuyen ve ISOLATED theo chinh sach an toan he thong")

        # 9. Breakeven handling
        is_be = signal.is_breakeven_mandatory or self.config.risk.breakeven_after_tp1_default

        # All passed!
        signal.validation_status = SignalState.VALIDATED
        signal.blocking_reason = None

        validated = ValidatedSignal(
            signal_id=signal.signal_id,
            symbol=signal.symbol_candidate,
            side=signal.side,
            entries=resolved_entries,
            stop_loss=signal.stop_loss,
            take_profits=resolved_tps,
            leverage=final_leverage,
            margin_mode=final_margin_mode,
            is_breakeven_after_tp1=is_be,
            risk_pct=self.config.risk.risk_per_signal_pct,
            metadata=signal.metadata,
        )

        return signal, validated

