from decimal import Decimal
from pydantic import BaseModel
from core.enums import EntryRangePolicy, MarginMode, MultiEntryWeightMode, MultiTPWeightMode


class RiskPolicy(BaseModel):
    risk_per_signal_pct: Decimal = Decimal("0.5")
    max_total_open_risk_pct: Decimal = Decimal("2.0")
    max_daily_loss_pct: Decimal = Decimal("3.0")
    max_active_signals: int = 2
    default_leverage: int = 3
    max_leverage: int = 5
    margin_mode: MarginMode = MarginMode.ISOLATED
    signal_max_age_seconds: int = 300
    entry_order_ttl_seconds: int = 900
    breakeven_after_tp1_default: bool = False
    fee_buffer_pct: Decimal = Decimal("0.1")
    slippage_buffer_pct: Decimal = Decimal("0.1")


class ExecutionPolicyConfig(BaseModel):
    multi_entry_default_weight_mode: MultiEntryWeightMode = MultiEntryWeightMode.NEEDS_POLICY
    entry_range_policy: EntryRangePolicy = EntryRangePolicy.NEEDS_POLICY
    multi_tp_default_weight_mode: MultiTPWeightMode = MultiTPWeightMode.NEEDS_POLICY
    min_sl_distance_pct: Decimal = Decimal("0.2")
    max_sl_distance_pct: Decimal = Decimal("30.0")
    sl_failure_emergency_close_timeout_seconds: int = 5


class SourcePolicyOverride(BaseModel):
    chat_id: int
    name: str
    allow_multi_entry_equal_split: bool = False
    allow_range_midpoint: bool = False
    allow_tp_equal_split: bool = False
    allow_buy_as_short_exception: bool = False  # e.g. for channel ATOM if user approved
    max_leverage_override: int | None = None

