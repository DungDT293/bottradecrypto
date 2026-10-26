import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock

from core.enums import ExecutionMode
from config.config import AppConfig
from services.quantum_ai_engine import QuantumAIEngine
from services.quantum_council_harness import (
    CouncilVote,
    RedTeamSkepticAgent,
    QuantumCouncilArbiter,
    QuantumCouncilSupervisor,
)


@pytest.fixture
def mock_config():
    cfg = MagicMock(spec=AppConfig)
    cfg.mode = ExecutionMode.PAPER
    cfg.live_trading_enabled = False
    cfg.risk = MagicMock()
    cfg.risk.max_active_signals = 5
    cfg.risk.max_risk_per_trade_pct = Decimal("2.0")
    cfg.risk.min_rr_ratio = Decimal("2.0")
    cfg.risk.atr_sl_multiplier = Decimal("1.8")
    cfg.risk.max_leverage = 20
    cfg.risk.enable_dynamic_leverage = True
    return cfg


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.base_url = "https://fapi.binance.com"
    client.get_open_positions = AsyncMock(return_value=[])
    client.get_symbol_filter = AsyncMock(return_value=MagicMock(tick_size="0.01"))
    return client


def test_mermaid_mean_reversion_deprecated(mock_config, mock_client):
    """Test that MERMAID_MEAN_REVERSION is completely deprecated (returns None)."""
    engine = QuantumAIEngine(mock_config, mock_client)
    # Market data with extreme RSI < 25 (oversold) but without SMC confluence
    m = {
        "symbol": "TRASHUSDT",
        "current_price": 10.0,
        "ema20": 12.0,
        "ema50": 13.0,
        "rsi": 22.0,
        "atr": 0.5,
        "vol_ratio": 1.0,
        "lower_wick_ratio": 0.1,
        "upper_wick_ratio": 0.1,
        "change_24h": -10.0,
        "tick_size": 0.01,
        "divergence": {"bullish_divergence": False, "bearish_divergence": False},
        "sweep": {"bull_sweep": False, "bear_sweep": False},
        "order_block": {"bull_ob": None, "bear_ob": None},
    }
    setup = engine.evaluate_admin_archetypes(m)
    assert setup is None, "MERMAID_MEAN_REVERSION should be deprecated and return None"


def test_calibrated_confidence_levels(mock_config, mock_client):
    """Test that Quantum 85%+ confluences yield mathematically calibrated confidence (85% or 90%)."""
    engine = QuantumAIEngine(mock_config, mock_client)
    
    # 4 Confluences setup (Sweep + Div + OB + Vol)
    m4 = {
        "symbol": "SOLUSDT",
        "current_price": 150.0,
        "open": 150.0,
        "ema20": 149.0,
        "ema50": 148.0,
        "rsi": 32.0,
        "atr": 3.0,
        "vol_ratio": 1.5,
        "lower_wick_ratio": 0.38,  # < 0.40 so confluence 5 is not triggered
        "upper_wick_ratio": 0.05,
        "change_24h": 1.0,
        "tick_size": 0.01,
        "divergence": {"bullish_divergence": True, "bearish_divergence": False},
        "sweep": {"bull_sweep": True, "bear_sweep": False, "lowest_prior": 147.0},
        "order_block": {"bull_ob": {"top": 150.5, "bottom": 149.0}, "bear_ob": None},
    }
    setup4 = engine.evaluate_quantum_85pct_confluence(m4)
    assert setup4 is not None
    assert setup4["has_setup"] is True
    assert setup4["confidence"] == 85, "4 confluences must yield calibrated 85% confidence"

    # 5 Confluences setup (+ Pinbar >= 40%)
    m5 = dict(m4)
    m5["lower_wick_ratio"] = 0.45
    setup5 = engine.evaluate_quantum_85pct_confluence(m5)
    assert setup5 is not None
    assert setup5["has_setup"] is True
    assert setup5["confidence"] == 90, "5 confluences must yield calibrated 90% confidence"


@pytest.mark.asyncio
async def test_red_team_cooldown_after_stoploss():
    """Test that RedTeamSkepticAgent enforces 4-hour (14400s) cooldown after a stop-loss."""
    red_team = RedTeamSkepticAgent()
    import time
    
    # Stopped out 1 hour ago (3600s < 14400s)
    closed_at = time.time() - 3600
    market_data = {
        "last_closed_at": closed_at,
        "last_trade_was_loss": True,
        "current_price": 100.0,
        "ema20": 100.0,
        "ema50": 100.0,
        "vol_ratio": 1.0,
        "change_24h": 0.0,
        "open_positions": [],
    }
    trade_params = {
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "leverage": 15,
        "confidence": 85,
    }
    opinion = await red_team.evaluate("VVVUSDT", "LONG", market_data, trade_params)
    assert opinion.vote == CouncilVote.VETO
    assert "COOLDOWN_VETO" in opinion.rationale
    assert "STOP LOSS" in opinion.rationale


@pytest.mark.asyncio
async def test_dual_ai_supervisor_workflow(mock_config, mock_client):
    """Test that QuantumCouncilSupervisor audits setups and executes 1-touch veto."""
    arbiter = QuantumCouncilArbiter(config=mock_config, binance_client=mock_client)
    supervisor = QuantumCouncilSupervisor(arbiter=arbiter)
    
    # Candidate setup attempting to SHORT a parabolic pump (Change 24h +25%, Vol x3.0)
    snapshot = {
        "current_price": 50.0,
        "ema20": 45.0,
        "ema50": 40.0,
        "vol_ratio": 3.0,
        "change_24h": 25.0,
        "open_positions": [],
        "btc_regime": {"status": "BULLISH_TREND", "btc_price": 68000.0},
    }
    candidate = {
        "direction": "SHORT",
        "entry_price": 50.0,
        "stop_loss": 53.0,
        "leverage": 20,
        "confidence": 85,
    }
    
    is_approved, veto_reason, deliberation = await supervisor.audit_setup("PUMPUSDT", snapshot, candidate)
    assert is_approved is False
    assert veto_reason is not None
    assert "Pump Trap" in veto_reason or "Red Team" in veto_reason

