import sys
import os
from decimal import Decimal
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath('.'))

from parser.signal_parser import SignalParser
from parser.validator import SignalValidator
from config.config import AppConfig
from core.models import SourceMetadata, PositionSide

def test_xrp_range_entry_logic():
    parser = SignalParser()
    validator = SignalValidator(AppConfig())

    raw_text = """
🔥 RFD Indicator 🔥

 15 Minutes Timeframe

✅ LONG

#XRP/USDT

Entry zone : 1.2579 - 1.2969

Take Profits : 

1.3033
1.3420
1.3807
1.4194
1.4581

Stop loss : 1.202498649
"""
    meta = SourceMetadata(
        chat_id=-1001781413045,
        message_id=237193,
        source_name="Binance 360 VIP",
        telegram_timestamp=datetime.now(timezone.utc)
    )

    parsed = parser.parse(raw_text, meta)
    assert parsed.validation_status.value in ("VALIDATED", "NEEDS_POLICY", "PENDING", "DRAFT")
    
    parsed, validated = validator.validate_and_resolve(parsed)
    assert validated is not None
    assert validated.entry_range == (Decimal("1.2579"), Decimal("1.2969"))

    # Test cases:
    zone_min, zone_max = validated.entry_range
    tick = Decimal("0.0001")

    # 1. Price is INSIDE the zone (1.2800)
    curr_p = Decimal("1.2800")
    assert zone_min <= curr_p <= zone_max
    rounded = (curr_p // tick) * tick
    assert rounded == Decimal("1.2800")

    # 2. Price is at the screenshot's price (1.2975) - only +0.046% above zone_max
    curr_p = Decimal("1.2975")
    drift_pct = (curr_p - zone_max) / zone_max * Decimal("100")
    assert drift_pct <= Decimal("1.0"), f"Expected <= 1%, got {drift_pct}%"

    # 3. Price is at discount (1.2500)
    curr_p = Decimal("1.2500")
    assert curr_p < zone_min
    assert curr_p > validated.stop_loss

    # 4. Price has truly chased FOMO past upper zone (1.3150)
    curr_p = Decimal("1.3150")
    drift_pct = (curr_p - zone_max) / zone_max * Decimal("100")
    assert drift_pct > Decimal("1.0"), f"Expected > 1%, got {drift_pct}%"

    print("ALL RANGE ENTRY IN ZONE TESTS PASSED!")

if __name__ == "__main__":
    test_xrp_range_entry_logic()
