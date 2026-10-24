import pytest
from decimal import Decimal
from execution.trailing_tp_manager import TrailingTakeProfitManager
from core.enums import PositionSide


def test_trailing_stop_long_activation_and_update():
    mgr = TrailingTakeProfitManager(
        pump_threshold_pct=Decimal("2.0"),
        trail_distance_pct=Decimal("1.5"),
    )
    ref_price = Decimal("100.0")
    current_sl = Decimal("95.0")
    key = "sig_long_1"

    # Price moves +1.0% to 101.0 -> Below 2.0% threshold -> No update
    update, new_sl, msg = mgr.calculate_trailing_stop(
        side=PositionSide.LONG,
        reference_price=ref_price,
        current_mark_price=Decimal("101.0"),
        current_sl=current_sl,
        key=key,
    )
    assert not update
    assert new_sl == current_sl

    # Price pumps +3.0% to 103.0 -> Exceeds 2.0% threshold -> Updates SL!
    # Trailing SL = 103.0 * (1 - 0.015) = 103.0 * 0.985 = 101.455
    update, new_sl, msg = mgr.calculate_trailing_stop(
        side=PositionSide.LONG,
        reference_price=ref_price,
        current_mark_price=Decimal("103.0"),
        current_sl=current_sl,
        key=key,
    )
    assert update
    assert new_sl == Decimal("101.455")
    assert new_sl > current_sl

    # Price pulls back to 102.0 -> Tracked peak remains 103.0 -> Trailing SL should not loosen!
    update, new_sl2, msg2 = mgr.calculate_trailing_stop(
        side=PositionSide.LONG,
        reference_price=ref_price,
        current_mark_price=Decimal("102.0"),
        current_sl=new_sl,
        key=key,
    )
    assert not update
    assert new_sl2 == new_sl

    # Price explodes higher to 110.0 -> Tracked peak updates to 110.0 -> SL moves higher!
    # Trailing SL = 110.0 * 0.985 = 108.35
    update, new_sl3, msg3 = mgr.calculate_trailing_stop(
        side=PositionSide.LONG,
        reference_price=ref_price,
        current_mark_price=Decimal("110.0"),
        current_sl=new_sl,
        key=key,
    )
    assert update
    assert new_sl3 == Decimal("108.35")
    assert new_sl3 > new_sl


def test_trailing_stop_short_activation_and_update():
    mgr = TrailingTakeProfitManager(
        pump_threshold_pct=Decimal("2.0"),
        trail_distance_pct=Decimal("1.5"),
    )
    ref_price = Decimal("100.0")
    current_sl = Decimal("105.0")
    key = "sig_short_1"

    # Price drops -1.0% to 99.0 -> Below 2.0% threshold -> No update
    update, new_sl, msg = mgr.calculate_trailing_stop(
        side=PositionSide.SHORT,
        reference_price=ref_price,
        current_mark_price=Decimal("99.0"),
        current_sl=current_sl,
        key=key,
    )
    assert not update

    # Price dumps -4.0% to 96.0 -> Exceeds 2.0% threshold -> Updates SL!
    # Trailing SL = 96.0 * (1 + 0.015) = 96.0 * 1.015 = 97.44
    update, new_sl, msg = mgr.calculate_trailing_stop(
        side=PositionSide.SHORT,
        reference_price=ref_price,
        current_mark_price=Decimal("96.0"),
        current_sl=current_sl,
        key=key,
    )
    assert update
    assert new_sl == Decimal("97.44")
    assert new_sl < current_sl
