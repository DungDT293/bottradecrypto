from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field, field_validator

from core.enums import (
    EntryMode,
    FieldSource,
    MarginMode,
    MultiEntryWeightMode,
    MultiTPWeightMode,
    OrderSide,
    OrderType,
    PositionSide,
    SignalState,
)


class SourceMetadata(BaseModel):
    chat_id: int
    message_id: int
    sender_id: Optional[int] = None
    telegram_timestamp: datetime
    received_at: datetime = Field(default_factory=datetime.utcnow)
    edit_timestamp: Optional[datetime] = None
    is_edit: bool = False
    source_name: Optional[str] = None


class RawMessage(BaseModel):
    metadata: SourceMetadata
    raw_text: str
    normalized_text: str


class ParsedSignal(BaseModel):
    signal_id: str
    metadata: SourceMetadata
    symbol_raw: str
    symbol_candidate: Optional[str] = None
    side: Optional[PositionSide] = None
    entries: List[Decimal] = Field(default_factory=list)
    entry_mode: EntryMode = EntryMode.SINGLE
    entry_weights: Optional[List[Decimal]] = None
    stop_loss: Optional[Decimal] = None
    take_profits: List[Decimal] = Field(default_factory=list)
    tp_weights: Optional[List[Decimal]] = None
    margin_mode_requested: Optional[MarginMode] = None
    leverage_requested: Optional[int] = None
    leverage_range: Optional[Tuple[int, int]] = None
    capital_usage_text: Optional[str] = None
    breakeven_instruction: Optional[str] = None
    is_breakeven_mandatory: bool = False
    warnings: List[str] = Field(default_factory=list)
    validation_status: SignalState = SignalState.PARSED
    blocking_reason: Optional[str] = None
    field_sources: Dict[str, FieldSource] = Field(default_factory=dict)


class ValidatedSignal(BaseModel):
    signal_id: str
    symbol: str
    side: PositionSide
    entries: List[Tuple[Decimal, Decimal]]  # list of (price, weight_pct)
    stop_loss: Decimal
    take_profits: List[Tuple[Decimal, Decimal]]  # list of (price, weight_pct)
    leverage: int
    margin_mode: MarginMode
    is_breakeven_after_tp1: bool
    risk_pct: Decimal
    metadata: SourceMetadata


class Order(BaseModel):
    client_order_id: str
    signal_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    price: Optional[Decimal] = None
    quantity: Decimal
    trigger_price: Optional[Decimal] = None
    is_reduce_only: bool = False
    is_algo: bool = False
    exchange_order_id: Optional[str] = None
    status: str = "NEW"  # NEW, PARTIALLY_FILLED, FILLED, CANCELED, REJECTED, EXPIRED
    filled_quantity: Decimal = Decimal("0")
    avg_fill_price: Optional[Decimal] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Position(BaseModel):
    symbol: str
    side: PositionSide
    quantity: Decimal = Decimal("0")
    entry_price: Decimal = Decimal("0")
    leverage: int = 1
    margin_mode: MarginMode = MarginMode.ISOLATED
    liquidation_price: Optional[Decimal] = None
    unrealized_pnl: Decimal = Decimal("0")
    active_signal_id: Optional[str] = None

