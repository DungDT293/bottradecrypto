import time
import pytest
from decimal import Decimal
from datetime import datetime, timezone

from core.enums import MarginMode, PositionSide
from core.models import SourceMetadata, ValidatedSignal
from services.signal_queue_service import SignalQueueService


def create_dummy_signal(symbol: str = "SOLUSDT", side: PositionSide = PositionSide.LONG) -> ValidatedSignal:
    meta = SourceMetadata(
        chat_id=-1001520053536,
        message_id=1234,
        telegram_timestamp=datetime.now(timezone.utc),
    )
    return ValidatedSignal(
        signal_id=f"sig_{symbol}",
        symbol=symbol,
        side=side,
        entries=[(Decimal("150.0"), Decimal("1.0"))],
        stop_loss=Decimal("142.0"),
        take_profits=[(Decimal("160.0"), Decimal("1.0"))],
        leverage=20,
        margin_mode=MarginMode.ISOLATED,
        is_breakeven_after_tp1=True,
        risk_pct=Decimal("1.5"),
        metadata=meta,
    )


def test_smart_queue_enqueue_priority_order():
    q = SignalQueueService(default_ttl_seconds=600)
    sig_tier2 = create_dummy_signal("ADAUSDT")
    sig_tier1_1 = create_dummy_signal("SOLUSDT")
    sig_tier1_2 = create_dummy_signal("ETHUSDT")

    # Enqueue Tier 2 first
    assert q.enqueue(sig_tier2, chat_id=-1001391574614, channel_name="Bitcoin Bulls", priority=2)
    # Enqueue Tier 1 items
    assert q.enqueue(sig_tier1_1, chat_id=-1001520053536, channel_name="Coin Chief", priority=1)
    assert q.enqueue(sig_tier1_2, chat_id=-1001700314832, channel_name="WHALES CIRCLE", priority=1)

    assert q.size() == 3

    # Dequeue must return Tier 1 first (priority 1), in FIFO order
    next_1 = q.dequeue_next()
    assert next_1.signal.symbol == "SOLUSDT"
    assert next_1.priority == 1

    next_2 = q.dequeue_next()
    assert next_2.signal.symbol == "ETHUSDT"
    assert next_2.priority == 1

    next_3 = q.dequeue_next()
    assert next_3.signal.symbol == "ADAUSDT"
    assert next_3.priority == 2

    assert q.dequeue_next() is None


def test_smart_queue_ttl_expiration():
    q = SignalQueueService(default_ttl_seconds=1)
    sig = create_dummy_signal("DOGEUSDT")

    # Enqueue with 1s TTL
    assert q.enqueue(sig, chat_id=-1001520053536, channel_name="Coin Chief", priority=1, ttl_seconds=1)
    assert q.size() == 1

    # Sleep past expiration
    time.sleep(1.1)

    # Dequeue should purge and return None
    assert q.dequeue_next() is None
    assert q.size() == 0


def test_smart_queue_no_duplicate_symbols():
    q = SignalQueueService(default_ttl_seconds=600)
    sig1 = create_dummy_signal("BTCUSDT")
    sig2 = create_dummy_signal("BTCUSDT")

    assert q.enqueue(sig1, chat_id=-1001520053536, channel_name="Coin Chief", priority=1)
    # Duplicate symbol should be rejected
    assert not q.enqueue(sig2, chat_id=-1001700314832, channel_name="WHALES CIRCLE", priority=1)
    assert q.size() == 1
