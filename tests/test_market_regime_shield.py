import pytest
from decimal import Decimal
from risk.market_regime_shield import MarketRegimeShield, calculate_ema, calculate_rsi
from core.enums import PositionSide


def test_calculate_ema():
    prices = [10.0] * 30
    assert calculate_ema(prices, 20) == 10.0

    prices_trend = [float(i) for i in range(1, 31)]
    ema20 = calculate_ema(prices_trend, 20)
    assert ema20 > 20.0  # EMA should be weighted toward recent values


def test_calculate_rsi():
    # Constant prices -> 50 RSI
    prices = [100.0] * 20
    assert calculate_rsi(prices, 14) == 50.0

    # Strictly upward prices -> 100 RSI
    prices_up = [100.0 + i for i in range(25)]
    assert calculate_rsi(prices_up, 14) > 80.0

    # Strictly downward prices -> low RSI
    prices_down = [200.0 - (i * 2) for i in range(25)]
    assert calculate_rsi(prices_down, 14) < 20.0


def test_market_regime_bearish_panic():
    shield = MarketRegimeShield(cache_ttl_seconds=60)

    # 4H prices dropping below EMA20 and EMA50:
    # 55 candles dropping from 70,000 to 50,000
    closes_4h = [70000.0 - (i * 350.0) for i in range(60)]
    closes_1h = [55000.0 - (i * 200.0) for i in range(30)]

    regime = shield.evaluate_regime_from_data(closes_4h, closes_1h)
    assert regime["status"] == "BEARISH_PANIC"
    assert regime["btc_1h_rsi"] < 40.0

    # Test signal allowed checks:
    # 1. Altcoin LONG must be BLOCKED
    allowed, reason = shield.check_signal_allowed("SOLUSDT", PositionSide.LONG)
    assert not allowed
    assert "BEARISH_PANIC" in reason
    assert "Chặn mở Altcoin LONG" in reason

    # 2. Altcoin SHORT must be ALLOWED
    allowed, reason = shield.check_signal_allowed("ETHUSDT", PositionSide.SHORT)
    assert allowed
    assert "Cho phép mở lệnh SHORT" in reason

    # 3. BTC itself must be ALLOWED
    allowed, reason = shield.check_signal_allowed("BTCUSDT", PositionSide.LONG)
    assert allowed


def test_market_regime_bullish_trend():
    shield = MarketRegimeShield(cache_ttl_seconds=60)

    # 4H prices rising: 60 candles going up from 50,000 to 75,000
    closes_4h = [50000.0 + (i * 400.0) for i in range(60)]
    closes_1h = [70000.0 + (i * 150.0) for i in range(30)]

    regime = shield.evaluate_regime_from_data(closes_4h, closes_1h)
    assert regime["status"] == "BULLISH_TREND"
    assert regime["btc_1h_rsi"] >= 50.0

    # Altcoin LONG is allowed
    allowed, reason = shield.check_signal_allowed("SOLUSDT", "LONG")
    assert allowed

    # Altcoin SHORT is allowed
    allowed, reason = shield.check_signal_allowed("SOLUSDT", "SHORT")
    assert allowed
