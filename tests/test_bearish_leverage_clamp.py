import pytest
from datetime import datetime
from decimal import Decimal
from core.enums import OrderSide, PositionSide, SignalState
from core.models import SourceMetadata, ParsedSignal
from parser.validator import SignalValidator
from risk.market_regime_shield import MarketRegimeShield, global_market_regime_shield
from config.config import AppConfig

def create_signal(symbol="BCHUSDT", side=PositionSide.LONG, entry=Decimal("280"), sl=Decimal("270"), lev=35):
    meta = SourceMetadata(chat_id=-1002007658025, message_id=9991, telegram_timestamp=datetime.utcnow())
    tp = entry * Decimal("1.05") if side == PositionSide.LONG else entry * Decimal("0.95")
    return ParsedSignal(
        signal_id=f"sig_test_{symbol}",
        symbol_raw=symbol,
        symbol_candidate=symbol,
        side=side,
        entries=[entry],
        stop_loss=sl,
        take_profits=[tp],
        leverage_requested=lev,
        metadata=meta,
    )

def test_bearish_panic_altcoin_long_leverage_clamp():
    cfg = AppConfig()
    cfg.mode = "LIVE"
    cfg.live_trading_enabled = True
    cfg.ferrari_mode_enabled = True  # Ferrari mode default is 35x-40x
    validator = SignalValidator(cfg)

    # 1. Set regime to BEARISH_PANIC
    global_market_regime_shield.enabled = True
    global_market_regime_shield._cached_regime = {
        "status": "BEARISH_PANIC",
        "btc_price": 80700.0,
        "reason": "BTC < EMA20 & EMA50",
    }

    # Case A: Altcoin LONG requesting 35x in BEARISH_PANIC -> Clamped to 18x
    sig_bch = create_signal("BCHUSDT", PositionSide.LONG, Decimal("280"), Decimal("270"), 35)
    sig_res, val_bch = validator.validate_and_resolve(sig_bch)
    assert val_bch is not None
    assert val_bch.leverage == 18, f"Altcoin LONG in BEARISH_PANIC must be clamped to 18x, got {val_bch.leverage}"
    assert any("BEARISH_PANIC" in w for w in sig_bch.warnings)

    # Case B: Altcoin SHORT requesting 35x in BEARISH_PANIC -> Not clamped to 18x
    sig_wlfi = create_signal("WLFIUSDT", PositionSide.SHORT, Decimal("0.054"), Decimal("0.055"), 35)
    sig_res, val_wlfi = validator.validate_and_resolve(sig_wlfi)
    assert val_wlfi is not None, f"sig_wlfi blocked: {sig_res.blocking_reason} | {sig_res.warnings}"
    assert val_wlfi.leverage > 18, f"Altcoin SHORT in BEARISH_PANIC should keep favorable leverage (>18x), got {val_wlfi.leverage}"

    # Case C: BTC LONG requesting 35x in BEARISH_PANIC -> Not clamped by altcoin rule
    sig_btc = create_signal("BTCUSDT", PositionSide.LONG, Decimal("80000"), Decimal("79000"), 35)
    sig_res, val_btc = validator.validate_and_resolve(sig_btc)
    assert val_btc is not None
    assert val_btc.leverage == 35, f"BTC LONG should not be clamped by Altcoin rule, got {val_btc.leverage}"

    # Case D: In BULLISH_TREND, Altcoin LONG requesting 35x with tight SL -> Not clamped to 18x
    global_market_regime_shield._cached_regime = {
        "status": "BULLISH_TREND",
        "btc_price": 85000.0,
        "reason": "BTC > EMA20 > EMA50",
    }
    sig_bch_bull = create_signal("BCHUSDT", PositionSide.LONG, Decimal("280"), Decimal("276"), 35)
    sig_res, val_bch_bull = validator.validate_and_resolve(sig_bch_bull)
    assert val_bch_bull is not None
    assert val_bch_bull.leverage == 35, f"In BULLISH_TREND, Altcoin LONG should not be clamped to 18x, got {val_bch_bull.leverage}"
