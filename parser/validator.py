from decimal import Decimal
from typing import List, Optional, Tuple

from config.config import AppConfig
from config.policy_defaults import SourcePolicyOverride, calculate_tp_weights
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
        # If already marked NEEDS_REVIEW or REJECTED during parsing:
        # Check if signal was marked NEEDS_REVIEW due to 'Short BELOW' and policy allows it
        if signal.validation_status == SignalState.NEEDS_REVIEW:
            allow_below = getattr(self.config.execution, "allow_below_pattern_as_valid", False) or \
                          (source_override and getattr(source_override, "allow_below_pattern", False))
            if allow_below and "BELOW" in (signal.blocking_reason or ""):
                signal.validation_status = SignalState.PARSED
                signal.blocking_reason = None
                signal.entry_mode = EntryMode.RANGE
            else:
                return signal, None
        elif signal.validation_status == SignalState.REJECTED:
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

        # 3. SL Distance Safety Checks & Anti-Wick Hunt Buffer
        raw_sl = signal.stop_loss
        avg_entry = sum(signal.entries) / len(signal.entries)
        sl_dist_pct = (abs(avg_entry - raw_sl) / avg_entry) * Decimal("100")
        if sl_dist_pct < self.config.execution.min_sl_distance_pct:
            signal.validation_status = SignalState.REJECTED
            signal.blocking_reason = f"Khoang cach SL qua hep ({sl_dist_pct:.2f}% < {self.config.execution.min_sl_distance_pct}%)"
            return signal, None
        if sl_dist_pct > self.config.execution.max_sl_distance_pct:
            signal.validation_status = SignalState.REJECTED
            signal.blocking_reason = f"Khoang cach SL qua xa ({sl_dist_pct:.2f}% > {self.config.execution.max_sl_distance_pct}%)"
            return signal, None

        sl_buffer_pct = getattr(self.config.risk, "sl_buffer_pct", Decimal("1.0"))
        buffered_sl = raw_sl
        if sl_buffer_pct and sl_buffer_pct > Decimal("0") and raw_sl:
            buffer_mult = sl_buffer_pct / Decimal("100")
            if signal.side == PositionSide.LONG:
                buffered_sl = raw_sl * (Decimal("1.0") - buffer_mult)
            else:
                buffered_sl = raw_sl * (Decimal("1.0") + buffer_mult)
            signal.warnings.append(
                f"Kich hoat dem chong quet rau Binance ({sl_buffer_pct}%): Noi SL tu {raw_sl} -> {buffered_sl:.6f} de tranh bi quet boi rau nen san khac."
            )
            signal.stop_loss = buffered_sl


        # 4. Resolve Range Entry Policy
        resolved_entries: List[Tuple[Decimal, Decimal]] = []
        entry_range_val = (min(signal.entries), max(signal.entries)) if (signal.entry_mode == EntryMode.RANGE and len(signal.entries) >= 2) else None
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

            policy_str = str(tp_policy.value if hasattr(tp_policy, "value") else tp_policy).upper()

            if tp_policy == MultiTPWeightMode.NEEDS_POLICY or policy_str == "NEEDS_POLICY":
                signal.validation_status = SignalState.NEEDS_POLICY
                signal.blocking_reason = "Tin co nhieu TP nhung thieu ty le chot loi va chua co policy duyet"
                return signal, None
            elif tp_policy == MultiTPWeightMode.EQUAL_SPLIT or policy_str in ["EQUAL_SPLIT", "EQUAL"]:
                count = len(signal.take_profits)
                equal_w = Decimal("1.0") / Decimal(str(count))
                resolved_tps = [(p, equal_w) for p in signal.take_profits]
                signal.field_sources["tp_weights"] = FieldSource.GLOBAL_POLICY
            elif tp_policy == MultiTPWeightMode.FRONT_LOADED_50_30_20 and len(signal.take_profits) == 3:
                weights = [Decimal("0.5"), Decimal("0.3"), Decimal("0.2")]
                resolved_tps = list(zip(signal.take_profits, weights))
                signal.field_sources["tp_weights"] = FieldSource.GLOBAL_POLICY
            elif tp_policy == MultiTPWeightMode.CUSTOM_TP1_RATIO or policy_str in [
                "CUSTOM_TP1_RATIO",
                "CUSTOM",
                "FRONT_LOADED",
                "FRONT_LOADED_50_30_20",
            ]:
                tp1_target = getattr(self.config.execution, "tp1_target_weight_pct", Decimal("60.0"))
                weights = calculate_tp_weights(len(signal.take_profits), tp1_target)
                resolved_tps = list(zip(signal.take_profits, weights))
                signal.field_sources["tp_weights"] = FieldSource.GLOBAL_POLICY
            else:
                count = len(signal.take_profits)
                equal_w = Decimal("1.0") / Decimal(str(count))
                resolved_tps = [(p, equal_w) for p in signal.take_profits]
                signal.field_sources["tp_weights"] = FieldSource.GLOBAL_POLICY

        # 7. Clamp Leverage
        max_allowed_lev = self.config.risk.max_leverage
        if source_override and source_override.max_leverage_override:
            max_allowed_lev = min(max_allowed_lev, source_override.max_leverage_override)

        # Select leverage: pick optimal target (e.g. 20x) within range, or respect requested
        if signal.leverage_range:
            lower, upper = min(signal.leverage_range), max(signal.leverage_range)
            target_lev = getattr(source_override, "default_leverage_override", None) or self.config.risk.default_leverage
            # Select target leverage within [lower, upper] range
            chosen_lev = max(lower, min(upper, target_lev))
        elif signal.leverage_requested:
            chosen_lev = signal.leverage_requested
        else:
            if source_override and getattr(source_override, "default_leverage_override", None):
                chosen_lev = source_override.default_leverage_override
            else:
                chosen_lev = self.config.risk.default_leverage

        # Clamp to max policy (e.g. 50X/100X clamped to 25X)
        final_leverage = min(chosen_lev, max_allowed_lev)
        if signal.leverage_requested and final_leverage != signal.leverage_requested:
            signal.warnings.append(f"Don bay yeu cau ({signal.leverage_requested}x) duoc ap tran an toan thanh {final_leverage}x")

        # Smart Safety Clamp: Leverage must never cause liquidation price to be tighter than Stop Loss!
        # In isolated margin: liquidation occurs at ~ (1 / leverage) * maintenance_buffer (~0.75).
        # Safe leverage <= 0.75 / sl_distance_pct.
        if signal.stop_loss and resolved_entries:
            ref_entry = resolved_entries[0][0]
            sl_dist_pct = abs(ref_entry - signal.stop_loss) / ref_entry
            if sl_dist_pct > Decimal("0"):
                max_safe_lev = int(Decimal("0.75") / sl_dist_pct)
                if max_safe_lev < final_leverage:
                    orig_lev = final_leverage
                    final_leverage = max(1, max_safe_lev)
                    signal.warnings.append(
                        f"Don bay {orig_lev}x qua cao so voi khoang cach SL ({sl_dist_pct*100:.1f}%). Tu dong ha xuong {final_leverage}x de dam bao khong bi thanh ly truoc khi cham SL."
                    )

        # 8. Margin mode determination (use signal margin mode if specified, otherwise fall back to config)
        final_margin_mode = signal.margin_mode_requested or getattr(self.config.risk, "margin_mode", MarginMode.CROSSED)

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
            entry_range=entry_range_val,
        )

        return signal, validated

