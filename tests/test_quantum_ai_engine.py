import pytest
from services.quantum_ai_engine import (
    calculate_ema,
    calculate_rsi,
    calculate_rsi_series,
    calculate_atr,
    calculate_stoch_rsi,
    calculate_bollinger_bands,
    detect_divergence,
    detect_liquidity_sweep,
    detect_order_block,
    round_to_tick,
    QuantumAIEngine,
)


def test_rsi_and_rsi_series():
    closes = [100.0 + i for i in range(30)]
    rsi_val = calculate_rsi(closes, 14)
    assert 95.0 <= rsi_val <= 100.0

    series = calculate_rsi_series(closes, 14)
    assert len(series) == len(closes)
    assert series[-1] == pytest.approx(rsi_val, rel=1e-3)


def test_stoch_rsi_and_bollinger_bands():
    closes = [100.0 + (i % 5) for i in range(30)]
    k, d = calculate_stoch_rsi(closes)
    assert 0.0 <= k <= 100.0
    assert 0.0 <= d <= 100.0

    mid, up, low, pct_b = calculate_bollinger_bands(closes, period=20)
    assert low < mid < up
    assert 0.0 <= pct_b <= 1.0


def test_detect_divergence():
    # Bullish Divergence: Lower price low, higher RSI low
    closes = [100.0, 95.0, 90.0, 92.0, 89.0, 88.0] * 5
    rsi = [40.0, 32.0, 25.0, 30.0, 35.0, 38.0] * 5
    div = detect_divergence(closes, rsi, lookback=25)
    assert "bullish_divergence" in div
    assert "bearish_divergence" in div


def test_liquidity_sweep_detection():
    # Construct a bottom sweep candle
    highs = [105.0] * 25 + [102.0]
    lows = [95.0] * 25 + [93.0]  # Thủng 95.0
    opens = [100.0] * 25 + [98.0]
    closes = [100.0] * 25 + [99.0]  # Đóng cửa 99.0 (> 95.0) với râu dưới (98 - 93 = 5 / 9 = 55%)
    sweep = detect_liquidity_sweep(highs, lows, closes, opens, lookback=20)
    assert sweep["bull_sweep"] is True
    assert sweep["lower_wick_ratio"] >= 0.35


def test_quantum_85pct_confluence_evaluation():
    class DummyClient:
        base_url = "https://fapi.binance.com"

    engine = QuantumAIEngine(config=None, binance_client=DummyClient())

    # Build market data satisfying 4+ confluences for BOTTOM HUNT
    market_data = {
        "symbol": "BTCUSDT",
        "current_price": 80000.0,
        "ema20": 79000.0,
        "ema50": 78000.0,
        "rsi": 32.0,
        "atr": 1000.0,
        "vol_ratio": 1.6,
        "lower_wick_ratio": 0.42,
        "upper_wick_ratio": 0.05,
        "k_stoch": 15.0,
        "pct_b": 0.05,
        "lower_bb": 80100.0,
        "upper_bb": 84000.0,
        "divergence": {"bullish_divergence": True, "bearish_divergence": False},
        "sweep": {"bull_sweep": True, "bear_sweep": False, "lowest_prior": 79500.0},
        "order_block": {"bull_ob": {"top": 80100.0, "bottom": 79800.0}, "bear_ob": None},
        "tick_size": 0.1,
    }

    setup = engine.evaluate_quantum_85pct_confluence(market_data)
    assert setup is not None
    assert setup["has_setup"] is True
    assert setup["direction"] == "LONG"
    assert setup["confidence"] in (85, 90)
    assert setup["archetype"] in ("SMC_SWEEP_SNIPER", "QUANTUM_SMC_BOTTOM_HUNT")
    assert len(setup["confluences"]) >= 4
    assert setup["stop_loss"] < setup["entry_price"]
    assert setup["take_profit_1"] > setup["entry_price"]
    assert setup["leverage"] <= 20, f"Expected safe leverage <= 20, got {setup['leverage']}"


def test_falling_knife_shield_blocks_downtrend_without_confirmation():
    class DummyClient:
        base_url = "https://fapi.binance.com"

    engine = QuantumAIEngine(config=None, binance_client=DummyClient())

    # Simulated falling knife market data (like ATOM dump)
    falling_knife_data = {
        "symbol": "ATOMUSDT",
        "current_price": 1.68,
        "ema20": 1.72,  # Strong 1h downtrend (price < ema20 < ema50)
        "ema50": 1.78,
        "rsi": 31.0,  # Oversold
        "atr": 0.04,
        "vol_ratio": 1.4,
        "lower_wick_ratio": 0.20,  # Small wick (no real buyer defense)
        "upper_wick_ratio": 0.10,
        "k_stoch": 15.0,  # Oversold
        "pct_b": 0.05,  # Band touch
        "lower_bb": 1.69,
        "upper_bb": 1.79,
        "divergence": {"bullish_divergence": False, "bearish_divergence": False},  # No divergence!
        "sweep": {"bull_sweep": False, "bear_sweep": False},
        "order_block": {"bull_ob": None, "bear_ob": None},
        "tick_size": 0.001,
    }

    # Must be BLOCKED by falling knife shield
    setup = engine.evaluate_quantum_85pct_confluence(falling_knife_data)
    assert setup is None, "Expected falling knife in strong downtrend without divergence to be blocked"



def test_low_cap_pump_shield_blocks_dangerous_short():
    class DummyClient:
        base_url = "https://fapi.binance.com"

    engine = QuantumAIEngine(config=None, binance_client=DummyClient())

    short_market_data = {
        "symbol": "REZUSDT",
        "current_price": 0.0045,
        "ema20": 0.0044,
        "ema50": 0.0043,
        "rsi": 76.0,
        "atr": 0.0001,
        "vol_ratio": 3.2,  # Sudden 3.2x whale volume surge
        "lower_wick_ratio": 0.05,
        "upper_wick_ratio": 0.45,
        "k_stoch": 85.0,
        "pct_b": 0.95,
        "lower_bb": 0.0040,
        "upper_bb": 0.00445,
        "divergence": {"bullish_divergence": False, "bearish_divergence": False},
        "sweep": {"bull_sweep": False, "bear_sweep": True, "highest_prior": 0.00448},
        "order_block": {"bull_ob": None, "bear_ob": {"top": 0.00452, "bottom": 0.00448}},
        "tick_size": 0.00001,
        "change_24h": 16.5,
    }

    # Low-Cap Pump Shield must block SHORT setup despite 4+ confluences
    setup = engine.evaluate_quantum_85pct_confluence(short_market_data)
    assert setup is None, "Expected Low-Cap Pump Shield to block SHORT during volume surge"

    # Admin Archetypes must never return a SHORT setup during volume surge
    admin_setup = engine.evaluate_admin_archetypes(short_market_data)
    assert admin_setup is None or admin_setup.get("direction") != "SHORT", "Expected Admin Archetypes to not return SHORT during volume surge"


def test_4h_macro_trend_alignment_shield():
    class DummyClient:
        base_url = "https://fapi.binance.com"

    engine = QuantumAIEngine(config=None, binance_client=DummyClient())

    # 1. Test: 4H is BEARISH -> Counter-trend LONG must be BLOCKED
    long_data_bearish_4h = {
        "symbol": "BTCUSDT",
        "current_price": 80000.0,
        "ema20": 79000.0,
        "ema50": 78000.0,
        "trend_4h": "BEARISH",  # 4H is Bearish!
        "rsi": 32.0,
        "atr": 1000.0,
        "vol_ratio": 1.6,
        "lower_wick_ratio": 0.42,
        "upper_wick_ratio": 0.05,
        "k_stoch": 15.0,
        "pct_b": 0.05,
        "lower_bb": 80100.0,
        "upper_bb": 84000.0,
        "divergence": {"bullish_divergence": True, "bearish_divergence": False},
        "sweep": {"bull_sweep": True, "bear_sweep": False, "lowest_prior": 79500.0},
        "order_block": {"bull_ob": {"top": 80100.0, "bottom": 79800.0}, "bear_ob": None},
        "tick_size": 0.1,
    }
    setup_long = engine.evaluate_quantum_85pct_confluence(long_data_bearish_4h)
    assert setup_long is None, "Expected counter-trend LONG to be blocked when 4H trend is BEARISH"

    # 2. Test: 4H is BULLISH -> Counter-trend SHORT must be BLOCKED
    short_data_bullish_4h = {
        "symbol": "ETHUSDT",
        "current_price": 3000.0,
        "ema20": 2980.0,
        "ema50": 2950.0,
        "trend_4h": "BULLISH",  # 4H is Bullish!
        "rsi": 72.0,
        "atr": 40.0,
        "vol_ratio": 1.4,
        "lower_wick_ratio": 0.05,
        "upper_wick_ratio": 0.45,
        "k_stoch": 85.0,
        "pct_b": 0.95,
        "lower_bb": 2900.0,
        "upper_bb": 2990.0,
        "divergence": {"bullish_divergence": False, "bearish_divergence": True},
        "sweep": {"bull_sweep": False, "bear_sweep": True, "highest_prior": 2995.0},
        "order_block": {"bull_ob": None, "bear_ob": {"top": 3010.0, "bottom": 2995.0}},
        "tick_size": 0.01,
        "change_24h": 5.0,
    }
    setup_short = engine.evaluate_quantum_85pct_confluence(short_data_bullish_4h)
    assert setup_short is None, "Expected counter-trend SHORT to be blocked when 4H trend is BULLISH"

    # 3. Test: When aligned (e.g. 4H BULLISH for LONG), setup is approved
    long_data_bullish_4h = dict(long_data_bearish_4h)
    long_data_bullish_4h["trend_4h"] = "BULLISH"
    setup_aligned = engine.evaluate_quantum_85pct_confluence(long_data_bullish_4h)
    assert setup_aligned is not None
    assert setup_aligned["direction"] == "LONG"


