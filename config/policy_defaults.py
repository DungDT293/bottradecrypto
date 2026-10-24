from typing import Any, List
from decimal import Decimal
from pydantic import BaseModel, field_validator
from core.enums import EntryRangePolicy, MarginMode, MultiEntryWeightMode, MultiTPWeightMode


def calculate_tp_weights(tp_count: int, tp1_pct: Any = Decimal("35.0")) -> List[Decimal]:
    """
    Calculates weights for multi-TP signals based on configurable TP1 ratio.
    - If 1 TP: [Decimal("1.0")]
    - If 2 TPs: [tp1_w, 1.0 - tp1_w]
    - If 3 TPs:
        - If tp1_w == 0.200: [0.200, 0.400, 0.400] (Chuẩn tối ưu lợi nhuận & khóa lãi nấc)
        - If tp1_w == 0.350: [0.350, 0.350, 0.300] (Chuẩn bảo vệ vốn cao)
        - Otherwise remainder is split 50/50 between TP2 and TP3
    - If >= 4 TPs: Remainder is distributed with geometric decay.
    Guarantees sum(weights) == Decimal("1.0").
    """
    if tp_count <= 0:
        return []
    if tp_count == 1:
        return [Decimal("1.0")]

    if not isinstance(tp1_pct, Decimal):
        tp1_pct = Decimal(str(tp1_pct))
    tp1_w = (tp1_pct / Decimal("100.0")).quantize(Decimal("0.001"))
    tp1_w = max(Decimal("0.100"), min(Decimal("0.900"), tp1_w))
    remainder = Decimal("1.0") - tp1_w

    if tp_count == 2:
        return [tp1_w, remainder]

    if tp_count == 3:
        if tp1_w == Decimal("0.200"):
            return [Decimal("0.200"), Decimal("0.400"), Decimal("0.400")]
        if tp1_w == Decimal("0.350"):
            return [Decimal("0.350"), Decimal("0.350"), Decimal("0.300")]
        tp2_w = (remainder * Decimal("0.65")).quantize(Decimal("0.001"))
        tp3_w = remainder - tp2_w
        return [tp1_w, tp2_w, tp3_w]

    weights = [tp1_w]
    decay_factors = [Decimal("0.6") ** i for i in range(tp_count - 1)]
    sum_factors = sum(decay_factors)
    accum = Decimal("0.0")
    for f in decay_factors[:-1]:
        w = (remainder * (f / sum_factors)).quantize(Decimal("0.001"))
        weights.append(w)
        accum += w
    last_w = remainder - accum
    weights.append(last_w)
    return weights


class RiskPolicy(BaseModel):
    risk_per_signal_pct: Decimal = Decimal("2.5")
    max_total_open_risk_pct: Decimal = Decimal("10.0")
    max_daily_loss_pct: Decimal = Decimal("10.0")
    max_active_signals: int = 5
    default_leverage: int = 20
    max_leverage: int = 25
    margin_mode: MarginMode = MarginMode.CROSSED
    target_margin_pct: Decimal = Decimal("5.0")
    max_margin_per_trade_pct: Decimal = Decimal("7.0")
    signal_max_age_seconds: int = 300
    entry_order_ttl_seconds: int = 900
    breakeven_after_tp1_default: bool = True
    fee_buffer_pct: Decimal = Decimal("0.1")
    slippage_buffer_pct: Decimal = Decimal("0.1")
    sl_buffer_pct: Decimal = Decimal("0.3")

    @field_validator("margin_mode", mode="before")
    @classmethod
    def normalize_margin_mode(cls, v):
        if isinstance(v, str):
            v_upper = v.upper().strip()
            if v_upper in ("CROSS", "CROSSED"):
                return MarginMode.CROSSED
            if v_upper == "ISOLATED":
                return MarginMode.ISOLATED
        return v


class ExecutionPolicyConfig(BaseModel):
    multi_entry_default_weight_mode: MultiEntryWeightMode = MultiEntryWeightMode.EQUAL_QUANTITY
    entry_range_policy: EntryRangePolicy = EntryRangePolicy.SPLIT_2_LIMITS
    multi_tp_default_weight_mode: MultiTPWeightMode = MultiTPWeightMode.FIXED_20_40_40
    tp1_target_weight_pct: Decimal = Decimal("20.0")
    breakeven_trigger_tp_index: int = 1
    breakeven_offset_pct: Decimal = Decimal("0.05")
    min_sl_distance_pct: Decimal = Decimal("0.2")
    max_sl_distance_pct: Decimal = Decimal("15.0")
    min_rr_tp1: Decimal = Decimal("0.20")
    sl_failure_emergency_close_timeout_seconds: int = 5
    allow_below_pattern_as_valid: bool = False

    @field_validator("entry_range_policy", mode="before")
    @classmethod
    def normalize_entry_range(cls, v):
        if isinstance(v, str):
            v_upper = v.upper().strip()
            if v_upper in ("MID", "MID_POINT", "MIDPOINT"):
                return EntryRangePolicy.MID_POINT
            if v_upper in ("BEST", "BEST_PRICE"):
                return EntryRangePolicy.BEST_PRICE
            if v_upper in ("SPLIT", "SPLIT_2_LIMITS", "SPLIT_2"):
                return EntryRangePolicy.SPLIT_2_LIMITS
            if v_upper == "NEEDS_POLICY":
                return EntryRangePolicy.NEEDS_POLICY
        return v

    @field_validator("multi_tp_default_weight_mode", mode="before")
    @classmethod
    def normalize_multi_tp(cls, v):
        if isinstance(v, str):
            v_upper = v.upper().strip()
            if v_upper in ("EQUAL", "EQUAL_SPLIT"):
                return MultiTPWeightMode.EQUAL_SPLIT
            if v_upper in ("CUSTOM", "CUSTOM_TP1_RATIO"):
                return MultiTPWeightMode.CUSTOM_TP1_RATIO
            if v_upper in ("FRONT", "FRONT_LOADED_50_30_20"):
                return MultiTPWeightMode.FRONT_LOADED_50_30_20
            if v_upper == "EXPLICIT":
                return MultiTPWeightMode.EXPLICIT
            if v_upper == "NEEDS_POLICY":
                return MultiTPWeightMode.NEEDS_POLICY
        return v


class SourcePolicyOverride(BaseModel):
    chat_id: int
    name: str
    allow_multi_entry_equal_split: bool = False
    allow_range_midpoint: bool = False
    allow_range_split_limits: bool = False
    allow_tp_equal_split: bool = False
    allow_below_pattern: bool = False
    allow_buy_as_short_exception: bool = False  # e.g. for channel ATOM if user approved
    max_leverage_override: int | None = None
    default_leverage_override: int | None = None
    margin_multiplier: Decimal = Decimal("1.0")

