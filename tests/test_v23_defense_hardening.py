"""
tests/test_v23_defense_hardening.py
=============================================================================
BỘ KIỂM THỬ 3 CƠ CHẾ PHÒNG VỆ CỐT LÕI (V2.3 DEFENSE HARDENING)
=============================================================================
1. GIỚI HẠN TỶ TRỌNG CÙNG CHIỀU (Directional Exposure Cap / Anti-Skew Shield)
   - Max 3 SHORTs, Max 3 LONGs mở đồng thời.
   - Red Team rút thẻ đỏ VETO với lý do chuẩn xác DIRECTIONAL_CAP_VETO.
2. BỘ ĐỆM LÀM NGUỘI THỊ TRƯỜNG (Market Cooldown Buffer / Anti-Overtrading Shield)
   - Per-symbol Cooldown >= 30 phút (1800s) sau khi đóng lệnh.
   - Global Trade Interval >= 15 phút (900s) giữa 2 lần mở lệnh mới (ngoại trừ consensus >= 9.2 / 92).
3. TRAILING STOP ĐỘNG THEO BIẾN ĐỘNG / ATR (Dynamic ATR-based Trailing Stop)
   - Tham số atr_distance_pct và cơ chế tính toán động (2.0% - 4.5%, mặc định an toàn 2.5% - 3.0%).
   - Bất biến rủi ro: SL chỉ dời theo chiều có lợi (khóa lãi), không bao giờ dời lùi.
=============================================================================
"""

import asyncio
from decimal import Decimal
import time
from typing import Any, Dict
import pytest

from core.enums import PositionSide
from execution.trailing_tp_manager import TrailingTakeProfitManager
from services.quantum_council_harness import (
    CouncilVote,
    RedTeamSkepticAgent,
    QuantumCouncilArbiter,
)
from services.gemini_autonomous_trader import GeminiAutonomousTrader


# =============================================================================
# 1. KIỂM THỬ GIỚI HẠN TỶ TRỌNG CÙNG CHIỀU (DIRECTIONAL EXPOSURE CAP)
# =============================================================================

@pytest.mark.asyncio
async def test_red_team_directional_cap_veto_shorts():
    """
    Candidate là SHORT nhưng hiện có >= 3 lệnh SHORT đang mở
    -> Red Team PHẢI rút THẺ ĐỎ VETO với đúng lý do:
       'DIRECTIONAL_CAP_VETO: Đã đạt trần tối đa 3 vị thế SHORT. Chặn để phòng ngừa rủi ro Short Squeeze khi thị trường đảo chiều!'
    """
    agent = RedTeamSkepticAgent()
    market_data = {
        "current_price": 100.0,
        "entry_price": 100.0,
        "stop_loss": 105.0,
        "leverage": 10,
        "open_positions": [
            {"symbol": "ETHUSDT", "positionAmt": "-1.5"},   # SHORT 1
            {"symbol": "SOLUSDT", "positionAmt": "-10.0"},  # SHORT 2
            {"symbol": "BNBUSDT", "positionAmt": "-5.0"},   # SHORT 3
        ],
    }
    trade_params = {"entry_price": 100.0, "stop_loss": 105.0, "leverage": 10}

    opinion = await agent.evaluate("BTCUSDT", "SHORT", market_data, trade_params)

    assert opinion.vote == CouncilVote.VETO
    assert opinion.confidence == 0
    assert "DIRECTIONAL_CAP_VETO: Đã đạt trần tối đa 3 vị thế SHORT" in opinion.rationale
    assert "Short Squeeze" in opinion.rationale


@pytest.mark.asyncio
async def test_red_team_directional_cap_veto_longs():
    """
    Candidate là LONG nhưng hiện có >= 3 lệnh LONG đang mở
    -> Red Team PHẢI rút THẺ ĐỎ VETO với đúng lý do:
       'DIRECTIONAL_CAP_VETO: Đã đạt trần tối đa 3 vị thế LONG. Chặn để phòng ngừa rủi ro Long Squeeze khi thị trường đảo chiều!'
    """
    agent = RedTeamSkepticAgent()
    market_data = {
        "current_price": 100.0,
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "leverage": 10,
        "open_positions": [
            {"symbol": "ETHUSDT", "positionAmt": "2.0"},   # LONG 1
            {"symbol": "SOLUSDT", "positionAmt": "15.0"},  # LONG 2
            {"symbol": "ADAUSDT", "positionAmt": "100.0"}, # LONG 3
        ],
    }
    trade_params = {"entry_price": 100.0, "stop_loss": 95.0, "leverage": 10}

    opinion = await agent.evaluate("BTCUSDT", "LONG", market_data, trade_params)

    assert opinion.vote == CouncilVote.VETO
    assert opinion.confidence == 0
    assert "DIRECTIONAL_CAP_VETO: Đã đạt trần tối đa 3 vị thế LONG" in opinion.rationale
    assert "Long Squeeze" in opinion.rationale


@pytest.mark.asyncio
async def test_red_team_directional_cap_pass_under_threshold():
    """
    Candidate là SHORT nhưng chỉ có 2 lệnh SHORT đang mở (< 3)
    -> Vượt qua kiểm tra trần tỷ trọng cùng chiều.
    """
    agent = RedTeamSkepticAgent()
    market_data = {
        "current_price": 100.0,
        "entry_price": 100.0,
        "stop_loss": 105.0,
        "leverage": 10,
        "vol_ratio": 1.0,
        "change_24h": -2.0,
        "open_positions": [
            {"symbol": "ETHUSDT", "positionAmt": "-1.5"},   # SHORT 1
            {"symbol": "SOLUSDT", "positionAmt": "-10.0"},  # SHORT 2
            {"symbol": "DOGEUSDT", "positionAmt": "500.0"}, # LONG 1
        ],
    }
    trade_params = {"entry_price": 100.0, "stop_loss": 105.0, "leverage": 10}

    opinion = await agent.evaluate("BTCUSDT", "SHORT", market_data, trade_params)

    # Không bị VETO bởi DIRECTIONAL_CAP
    assert "DIRECTIONAL_CAP_VETO" not in (opinion.red_flag or "")
    assert opinion.vote == CouncilVote.APPROVED


# =============================================================================
# 2. KIỂM THỬ BỘ ĐỆM LÀM NGUỘI THỊ TRƯỜNG (MARKET COOLDOWN BUFFER)
# =============================================================================

@pytest.mark.asyncio
async def test_red_team_per_symbol_cooldown_veto():
    """
    Coin X vừa đóng vị thế 600s trước (< 1800s)
    -> Red Team PHẢI rút THẺ ĐỎ VETO chống Revenge Trading.
    """
    agent = RedTeamSkepticAgent()
    now_ts = time.time()
    market_data = {
        "current_price": 50.0,
        "entry_price": 50.0,
        "stop_loss": 48.0,
        "leverage": 10,
        "vol_ratio": 1.0,
        "change_24h": 1.5,
        "last_closed_at": now_ts - 600,  # Vừa đóng 10 phút trước
    }
    trade_params = {"entry_price": 50.0, "stop_loss": 48.0, "leverage": 10}

    opinion = await agent.evaluate("LINKUSDT", "LONG", market_data, trade_params)

    assert opinion.vote == CouncilVote.VETO
    assert "COOLDOWN_VETO" in (opinion.red_flag or "")
    assert "Revenge Trading" in opinion.rationale


@pytest.mark.asyncio
async def test_arbiter_global_trade_interval_veto_low_consensus():
    """
    Vừa mở lệnh 300s trước (< 900s) và setup có consensus 86/100 (< 92)
    -> Arbiter PHẢI VETO vì vi phạm khoảng cách 15 phút giữa 2 lệnh.
    """
    arbiter = QuantumCouncilArbiter()
    arbiter.record_trade_opened("ETHUSDT", time.time() - 300)  # Mở 5 phút trước

    # Setup có R:R chuẩn nhưng không đạt consensus >= 92
    market_data = {
        "symbol": "WLFIUSDT",
        "direction": "SHORT",
        "current_price": 0.1200,
        "entry_price": 0.1200,
        "stop_loss": 0.1250,
        "take_profit_1": 0.1130,
        "take_profit_2": 0.1080,
        "take_profit_3": 0.1000,
        "leverage": 15,
        "vol_ratio": 1.1,
        "change_24h": -2.5,
        "ema20": 0.1220,
        "ema50": 0.1250,
        "upper_wick_ratio": 0.35,
        "rsi": 45.0,
        "btc_regime": {"status": "NEUTRAL", "reason": "BTC bình thường"},
        "headlines": ["WLFI news neutral"],
    }

    result = await arbiter.deliberate("WLFIUSDT", market_data)

    assert result.is_approved is False
    assert "GLOBAL_INTERVAL_VETO" in (result.veto_reason or "")
    assert "chưa đủ 15 phút" in (result.veto_reason or "")


@pytest.mark.asyncio
async def test_arbiter_global_trade_interval_exemption_high_consensus():
    """
    Vừa mở lệnh 300s trước (< 900s) NHƯNG setup đạt consensus >= 92 (9.2+)
    -> Được đặc cách (exemption) phê duyệt mở lệnh!
    """
    arbiter = QuantumCouncilArbiter()
    arbiter.record_trade_opened("ETHUSDT", time.time() - 300)

    # Setup siêu đẹp với tin tức cực tốt (BOOSTED) giúp consensus vượt 92
    market_data = {
        "symbol": "WLFIUSDT",
        "direction": "LONG",
        "current_price": 0.1200,
        "entry_price": 0.1200,
        "stop_loss": 0.1150,
        "take_profit_1": 0.1270,
        "take_profit_2": 0.1330,
        "take_profit_3": 0.1400,
        "leverage": 15,
        "vol_ratio": 1.2,
        "change_24h": 3.0,
        "ema20": 0.1180,
        "ema50": 0.1150,
        "lower_wick_ratio": 0.45,
        "rsi": 58.0,
        "btc_regime": {"status": "BULLISH_TREND", "reason": "BTC uptrend mạnh"},
        "headlines": ["WLFI mainnet launch officially announced with tier-1 partners"],  # Catalyst -> BOOSTED
    }

    result = await arbiter.deliberate("WLFIUSDT", market_data)

    assert result.consensus_score >= 92
    assert result.is_approved is True


# =============================================================================
# 3. KIỂM THỬ TRAILING STOP ĐỘNG THEO BIẾN ĐỘNG / ATR
# =============================================================================

def test_trailing_stop_default_safe_distance():
    """
    Khoảng cách mặc định được nâng an toàn từ 1.5% lên 2.5% - 3.0%.
    """
    mgr = TrailingTakeProfitManager()
    assert mgr.trail_distance_pct >= Decimal("2.5")
    assert mgr.min_trail_distance_pct == Decimal("2.0")
    assert mgr.max_trail_distance_pct == Decimal("4.5")


def test_trailing_stop_dynamic_atr_clamping():
    """
    Khoảng cách trailing động tuân thủ trần sàn: tối thiểu >= 2.0% và tối đa <= 4.5%.
    """
    mgr = TrailingTakeProfitManager()

    # Case 1: ATR distance quá hẹp (1.2% < 2.0%) -> kẹp về trần sàn 2.0%
    eff1 = mgr.get_effective_trail_distance(atr_distance_pct=Decimal("1.2"))
    assert eff1 == Decimal("2.0")

    # Case 2: ATR distance quá rộng (5.5% > 4.5%) -> kẹp về trần trên 4.5%
    eff2 = mgr.get_effective_trail_distance(atr_distance_pct=Decimal("5.5"))
    assert eff2 == Decimal("4.5")

    # Case 3: ATR distance hợp lệ (3.2%) -> giữ nguyên 3.2%
    eff3 = mgr.get_effective_trail_distance(atr_distance_pct=Decimal("3.2"))
    assert eff3 == Decimal("3.2")


def test_trailing_stop_long_with_dynamic_atr_prevents_premature_wickout():
    """
    Kiểm tra cơ chế chống quét non râu nến (ERA, DOS) trên lệnh LONG:
    Với khoảng cách trailing động 3.0%, khi nến rút râu nhẹ -2.2% không bị quét out,
    SL dời bám đỉnh an toàn.
    """
    mgr = TrailingTakeProfitManager()
    ref_price = Decimal("100.0")
    current_sl = Decimal("95.0")
    key = "sig_long_atr_test"

    # Giá tăng mạnh lên 105.0 (+5.0% > 2.0% pump threshold)
    # Với atr_distance_pct = 3.0% -> Trail price = 105.0 * (1 - 0.03) = 101.85
    update, new_sl, msg = mgr.calculate_trailing_stop(
        side=PositionSide.LONG,
        reference_price=ref_price,
        current_mark_price=Decimal("105.0"),
        current_sl=current_sl,
        key=key,
        atr_distance_pct=Decimal("3.0"),
    )
    assert update is True
    assert new_sl == Decimal("101.85")
    assert new_sl > current_sl

    # Giá rút râu về 103.0 (giảm 1.9% từ đỉnh 105.0):
    # Với trailing cũ 1.5% (SL ở 103.425) thì đã bị quét non!
    # Nhưng với trailing mới 3.0% (SL ở 101.85), giá 103.0 vẫn trên SL an toàn!
    assert Decimal("103.0") > new_sl

    # Đỉnh không đổi -> Không dời SL lùi (Bất biến rủi ro)
    update2, new_sl2, _ = mgr.calculate_trailing_stop(
        side=PositionSide.LONG,
        reference_price=ref_price,
        current_mark_price=Decimal("103.0"),
        current_sl=new_sl,
        key=key,
        atr_distance_pct=Decimal("3.0"),
    )
    assert update2 is False
    assert new_sl2 == new_sl


def test_trailing_stop_short_with_dynamic_atr():
    """
    Kiểm tra Trailing Stop động cho lệnh SHORT:
    SL bám đáy dời xuống khóa lãi khi giá giảm sâu.
    """
    mgr = TrailingTakeProfitManager()
    ref_price = Decimal("100.0")
    current_sl = Decimal("105.0")
    key = "sig_short_atr_test"

    # Giá giảm mạnh xuống 94.0 (-6.0% > 2.0% pump threshold)
    # Với atr_distance_pct = 2.8% -> Trail price = 94.0 * (1 + 0.028) = 96.632
    update, new_sl, msg = mgr.calculate_trailing_stop(
        side=PositionSide.SHORT,
        reference_price=ref_price,
        current_mark_price=Decimal("94.0"),
        current_sl=current_sl,
        key=key,
        atr_distance_pct=Decimal("2.8"),
    )
    assert update is True
    assert new_sl == Decimal("96.632")
    assert new_sl < current_sl
