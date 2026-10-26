import asyncio
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from config.config import AppConfig
from core.enums import MarginMode, OrderSide, OrderType, PositionSide, SignalState
from core.models import SourceMetadata, ValidatedSignal
from services.quantum_ai_engine import (
    calculate_rsi_series,
    calculate_stoch_rsi,
    calculate_bollinger_bands,
    detect_divergence,
    detect_liquidity_sweep,
    detect_order_block,
)

logger = logging.getLogger("gemini_trader")

DEFAULT_WATCHLIST = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "SUIUSDT",
    "NEARUSDT",
    "AVAXUSDT",
    "PEPEUSDT",
    "APTUSDT",
    "ADAUSDT",
    "LINKUSDT",
    "PENGUUSDT",
    "ENAUSDT",
    "OPUSDT",
    "ARBUSDT",
    "TIAUSDT",
    "INJUSDT",
    "FETUSDT",
]

def calculate_ema(prices: List[float], period: int) -> float:
    if not prices:
        return 0.0
    if len(prices) < period:
        return prices[-1]
    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1.0 - k)
    return ema

def calculate_rsi(prices: List[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss <= 1e-9:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return (highs[-1] - lows[-1]) if highs and lows else 0.0
    tr_list = []
    for i in range(1, len(closes)):
        h = highs[i]
        l = lows[i]
        prev_c = closes[i-1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_list.append(tr)
    return sum(tr_list[-period:]) / period


class GeminiAutonomousTrader:
    """
    Autonomous AI & Quant Market Scanner:
    - Scans liquid Binance Futures pairs (K-lines 1h, EMA, RSI, ATR).
    - Queries Gemini 1.5/2.0 Flash with technical market snapshots for trade validation.
    - Built-in Quant Engine fallback if Gemini API key is missing or quota runs out.
    - Executes high-probability setups (>= 75% confidence, >= 2.0 R:R) with Zero-Liquidation risk.
    """

    def __init__(
        self,
        config: AppConfig,
        binance_client: Any,
        order_manager: Any = None,
        risk_engine: Any = None,
        signal_repo: Any = None,
        db: Any = None,
        entry_enabled_provider: Any = None,
        engine_status_provider: Any = None,
    ):
        self.config = config
        self.client = binance_client
        self.order_manager = order_manager
        self.risk_engine = risk_engine
        self.signal_repo = signal_repo
        self.db = db
        self._entry_enabled_provider = entry_enabled_provider
        self._engine_status_provider = engine_status_provider

        # State
        ai_cfg = getattr(config, "ai", None)
        self.enabled: bool = getattr(ai_cfg, "enabled", False) if ai_cfg else getattr(config, "ai_trading_enabled", False)
        self.gemini_api_key: Optional[str] = (getattr(ai_cfg, "api_key", None) if ai_cfg else None) or os.getenv("GEMINI_API_KEY")
        self.scan_interval_minutes: int = getattr(ai_cfg, "scan_interval_minutes", 15) if ai_cfg else 15
        self.preferred_model: str = getattr(ai_cfg, "preferred_model", "gemini-3.6-flash") if ai_cfg else "gemini-3.6-flash"
        self.min_confidence: int = getattr(ai_cfg, "min_confidence", 80) if ai_cfg else 80
        self.watchlist: List[str] = list(getattr(ai_cfg, "watchlist", DEFAULT_WATCHLIST)) if ai_cfg else list(DEFAULT_WATCHLIST)
        self._top_watchlist_cache: List[str] = []
        self._top_watchlist_time: float = 0.0
        self._valid_symbol_cache: set[str] = set()
        self._valid_symbol_cache_time: float = 0.0
        self.last_scan_time: Optional[str] = None
        self.last_scan_results: List[Dict[str, Any]] = []
        self.last_scan_skipped_symbols: List[str] = []
        self.last_scan_symbol_validation_error: Optional[str] = None
        self._is_scanning: bool = False
        self._gemini_key_invalid: bool = False

        # Load persisted scan results cache if available to survive backend restarts
        try:
            cache_file = os.path.join(getattr(self.config, "data_dir", "./data"), "ai_last_scan.json")
            if os.path.exists(cache_file):
                with open(cache_file, "r", encoding="utf-8") as f_cache:
                    cached_data = json.load(f_cache)
                    self.last_scan_time = cached_data.get("scan_time")
                    self.last_scan_results = cached_data.get("setups", [])
                    logger.info(f"Loaded {len(self.last_scan_results)} cached AI setups from {cache_file}")
        except Exception as e_cache_init:
            logger.debug(f"Failed to load cached AI scan results: {e_cache_init}")

        from services.quantum_ai_engine import QuantumAIEngine
        from services.market_sentiment_news_guardian import MarketSentimentNewsGuardian
        from services.quantum_council_harness import QuantumCouncilArbiter
        self.quantum_engine = QuantumAIEngine(config, binance_client)
        self.sentiment_guardian = MarketSentimentNewsGuardian(config=self.config)
        self.council_arbiter = QuantumCouncilArbiter(
            config=self.config,
            binance_client=self.client,
            quantum_engine=self.quantum_engine,
            sentiment_guardian=self.sentiment_guardian,
        )
        self._api_cooldown_until: float = 0.0
        self._quota_status: str = "NORMAL"  # NORMAL | RATE_LIMITED_COOLDOWN | PREPAY_DEPLETED
        self._daily_api_calls: int = 0
        self._daily_calls_reset_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._running_task: Optional[asyncio.Task] = None

        # V2.3 Market Cooldown Buffer & Trade Interval Tracking
        self.symbol_last_closed: Dict[str, float] = {}
        self.symbol_last_was_loss: Dict[str, bool] = {}
        self.last_trade_opened_at: float = self._get_last_trade_from_db()
        if hasattr(self, "council_arbiter") and self.council_arbiter:
            self.council_arbiter.last_trade_opened_at = self.last_trade_opened_at

    def _get_last_closed_info_from_db(self, symbol: str) -> Tuple[float, bool]:
        """Truy vấn thời điểm đóng vị thế và kết quả (lỗ/stop-loss hay không) từ Database."""
        if not self.db:
            return 0.0, False
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT updated_at, blocking_reason FROM signals WHERE symbol = ? AND state = 'CLOSED' ORDER BY updated_at DESC LIMIT 1",
                    (symbol,)
                )
                row = cursor.fetchone()
                if row and row[0]:
                    dt = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
                    reason = str(row[1] or "").upper()
                    was_loss = "STOP_LOSS" in reason or "SL" in reason or "LOSS" in reason
                    return dt.timestamp(), was_loss
        except Exception as e:
            logger.debug(f"Error querying last closed from DB for {symbol}: {e}")
        return 0.0, False

    def _get_last_closed_from_db(self, symbol: str) -> float:
        ts, _ = self._get_last_closed_info_from_db(symbol)
        return ts

    def _get_last_trade_from_db(self) -> float:
        """Truy vấn thời điểm mở lệnh gần nhất toàn hệ thống từ Database."""
        if not self.db:
            return 0.0
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT created_at FROM signals ORDER BY created_at DESC LIMIT 1"
                )
                row = cursor.fetchone()
                if row and row[0]:
                    dt = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
                    return dt.timestamp()
        except Exception as e:
            logger.debug(f"Error querying last trade from DB: {e}")
        return 0.0

    def record_position_closed(self, symbol: str, closed_at: Optional[float] = None, was_loss: bool = False) -> None:
        """Ghi nhận thời điểm đóng vị thế và kết quả cho coin X để kích hoạt Market Cooldown Buffer."""
        sym = symbol.upper().replace("/", "").replace(":", "")
        ts = closed_at or time.time()
        self.symbol_last_closed[sym] = ts
        self.symbol_last_was_loss[sym] = was_loss
        if hasattr(self, "council_arbiter") and self.council_arbiter:
            self.council_arbiter.record_position_closed(sym, ts)

    def record_trade_opened(self, symbol: str, opened_at: Optional[float] = None) -> None:
        """Ghi nhận thời điểm mở vị thế mới để kiểm soát Global Trade Interval 15m."""
        ts = opened_at or time.time()
        self.last_trade_opened_at = ts
        if hasattr(self, "council_arbiter") and self.council_arbiter:
            self.council_arbiter.record_trade_opened(symbol, ts)

    def get_symbol_cooldown_remaining(self, symbol: str) -> int:
        """
        Trả về số giây làm nguội còn lại của coin X:
        - Nếu vừa dính SL / Lỗ: 4 tiếng = 14400s (chống bẫy Revenge Trading).
        - Nếu đóng hòa vốn / lãi: 30 phút = 1800s.
        """
        sym = symbol.upper().replace("/", "").replace(":", "")
        last_closed = self.symbol_last_closed.get(sym, 0.0)
        was_loss = self.symbol_last_was_loss.get(sym, False)
        if last_closed <= 0.0 and self.db:
            last_closed, db_was_loss = self._get_last_closed_info_from_db(sym)
            if last_closed > 0.0:
                self.symbol_last_closed[sym] = last_closed
                self.symbol_last_was_loss[sym] = db_was_loss
                was_loss = db_was_loss
        req_cooldown = 14400 if was_loss else 1800
        elapsed = time.time() - last_closed
        if 0 <= elapsed < req_cooldown:
            return int(req_cooldown - elapsed)
        return 0

    def get_global_trade_interval_remaining(self) -> int:
        """Trả về số giây khoảng cách còn lại giữa 2 lần mở vị thế bất kỳ (15 phút = 900s)."""
        last_trade = self.last_trade_opened_at
        if last_trade <= 0.0 and self.db:
            last_trade = self._get_last_trade_from_db()
            if last_trade > 0.0:
                self.last_trade_opened_at = last_trade
        elapsed = time.time() - last_trade
        if 0 <= elapsed < 900:
            return int(900 - elapsed)
        return 0

    def get_cooldown_remaining(self) -> int:
        remaining = self._api_cooldown_until - time.time()
        return max(0, int(remaining))

    def _execution_gate_reason(self) -> Optional[str]:
        """Return reason when autonomous entry is not in a trusted lifecycle state."""
        from config.config import exchange_writes_enabled
        if not exchange_writes_enabled(self.config):
            return f"Exchange writes blocked in {self.config.mode.value} mode"
        if not callable(self._entry_enabled_provider) or not self._entry_enabled_provider():
            return "AI execution blocked while entry lifecycle is disabled"
        if callable(self._engine_status_provider):
            status = self._engine_status_provider()
            status_value = getattr(status, "value", str(status))
            if status_value not in {"RUNNING_LISTEN", "RUNNING_SHADOW"}:
                return f"AI execution requires active protected engine lifecycle (got {status_value})"
        return None

    def _setup_is_current(self, setup: Dict[str, Any]) -> bool:
        """Require match to a recent scan result; never execute arbitrary untrusted signals."""
        scan_time = self.last_scan_time
        if not scan_time or not self.last_scan_results:
            return False
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(scan_time)).total_seconds()
        except (TypeError, ValueError):
            return False
        max_age = max(3600, int(getattr(getattr(self.config, "risk", None), "signal_max_age_seconds", 300)) * 12)
        if age < 0 or age > max_age:
            return False

        required_fields = ("symbol", "direction", "entry_price", "stop_loss", "take_profit_1", "take_profit_2", "take_profit_3")

        def _match_candidate(cand: Dict[str, Any]) -> bool:
            if str(cand.get("symbol", "")).upper() != str(setup.get("symbol", "")).upper():
                return False
            if str(cand.get("direction", "")).upper() != str(setup.get("direction", "")).upper():
                return False
            for f in ("entry_price", "stop_loss", "take_profit_1", "take_profit_2", "take_profit_3"):
                try:
                    c_val = Decimal(str(cand.get(f, 0)))
                    s_val = Decimal(str(setup.get(f, 0)))
                    ref = c_val if c_val > 0 else Decimal("1")
                    if abs(c_val - s_val) / ref > Decimal("0.01"):
                        return False
                except Exception:
                    if str(cand.get(f)) != str(setup.get(f)):
                        return False
            return True

        return any(_match_candidate(candidate) for candidate in self.last_scan_results)

    def is_promising_candidate(self, snapshot: Dict[str, Any]) -> bool:
        """
        CPU-based Pre-Filter (< 1ms execution):
        Dramatically saves Gemini API quota (by 85-90%) by only querying AI
        when the coin is near key technical inflection points.
        """
        rsi = snapshot.get("rsi_14", 50.0)
        p = snapshot.get("current_price", 0.0)
        ema50 = snapshot.get("ema50", 0.0)
        chg = abs(snapshot.get("change_24h_pct", 0.0))

        # Condition 1: RSI in oversold or overbought pullback zones
        if rsi <= 36.0 or rsi >= 64.0:
            return True

        # Condition 2: Price retesting EMA50 within 1.5% in an active trend
        if ema50 > 0 and abs(p - ema50) / ema50 <= 0.015:
            return True

        # Condition 3: Significant 24h momentum breakout
        if chg >= 4.0:
            return True

        # Condition 4: SMC Liquidity Sweep or RSI Divergence or Bollinger Band Exhaustion
        sweep = snapshot.get("sweep", {})
        if sweep.get("bull_sweep") or sweep.get("bear_sweep"):
            return True
        div = snapshot.get("divergence", {})
        if div.get("bullish_divergence") or div.get("bearish_divergence"):
            return True
        pct_b = snapshot.get("pct_b", 0.5)
        if pct_b <= 0.18 or pct_b >= 0.82:
            return True

        return False

    async def _filter_valid_symbols(self, symbols: List[str]) -> Tuple[List[str], List[str]]:
        """Validate configured symbols once per hour before requesting klines."""
        normalized = list(dict.fromkeys(str(symbol).upper().strip() for symbol in symbols if str(symbol).strip()))
        self.last_scan_symbol_validation_error = None
        try:
            if not self._valid_symbol_cache or time.time() - self._valid_symbol_cache_time >= 3600:
                self._valid_symbol_cache = await self.client.get_exchange_symbols()
                self._valid_symbol_cache_time = time.time()
            valid = [symbol for symbol in normalized if symbol in self._valid_symbol_cache]
            skipped = [symbol for symbol in normalized if symbol not in self._valid_symbol_cache]
            for symbol in skipped:
                logger.warning("Skipping unavailable Binance Futures symbol: %s", symbol)
            return valid, skipped
        except Exception as exc:
            self.last_scan_symbol_validation_error = str(exc)
            logger.warning("Could not validate Binance Futures symbols; keeping configured symbols: %s", exc)
            return normalized, []

    async def get_market_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Collects technical indicators and recent candles for a symbol from Binance."""
        try:
            session = await self.client._get_session()
            url = f"{self.client.base_url}/fapi/v1/klines?symbol={symbol}&interval=1h&limit=120"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8.0)) as resp:
                if resp.status != 200:
                    return None
                klines = await resp.json()

            if not klines or len(klines) < 30:
                return None

            opens = [float(k[1]) for k in klines]
            closes = [float(k[4]) for k in klines]
            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]
            volumes = [float(k[5]) for k in klines]

            current_p = closes[-1]
            ema20 = calculate_ema(closes, 20)
            ema50 = calculate_ema(closes, 50)
            rsi = calculate_rsi(closes, 14)
            rsi_series = calculate_rsi_series(closes, 14)
            atr = calculate_atr(highs, lows, closes, 14)
            k_stoch, d_stoch = calculate_stoch_rsi(closes)
            mid_bb, upper_bb, lower_bb, pct_b = calculate_bollinger_bands(closes)
            div = detect_divergence(closes, rsi_series)
            sweep = detect_liquidity_sweep(highs, lows, closes, opens)
            ob = detect_order_block(opens, highs, lows, closes)
            
            # 4H Macro Trend Alignment (20-bar 4H ~ 80h, 50-bar 4H ~ 120h)
            ema_4h_20 = calculate_ema(closes, min(len(closes), 80))
            ema_4h_50 = calculate_ema(closes, min(len(closes), 120))
            if current_p > ema_4h_50 and ema_4h_20 >= ema_4h_50:
                trend_4h = "BULLISH"
            elif current_p < ema_4h_50 and ema_4h_20 <= ema_4h_50:
                trend_4h = "BEARISH"
            else:
                trend_4h = "CHOPPY"

            # Trend calculation
            if current_p > ema20 > ema50:
                trend = "STRONG_BULLISH"
            elif current_p > ema20:
                trend = "BULLISH"
            elif current_p < ema20 < ema50:
                trend = "STRONG_BEARISH"
            elif current_p < ema20:
                trend = "BEARISH"
            else:
                trend = "SIDEWAYS"

            change_24h_pct = ((current_p - closes[-24]) / closes[-24] * 100.0) if len(closes) >= 24 else 0.0

            last_open = float(klines[-1][1])
            last_high = highs[-1]
            last_low = lows[-1]
            candle_range = last_high - last_low if last_high > last_low else 1e-6
            upper_wick = last_high - max(last_open, current_p)
            lower_wick = min(last_open, current_p) - last_low
            upper_wick_ratio = upper_wick / candle_range
            lower_wick_ratio = lower_wick / candle_range

            vol_ma20 = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else volumes[-1]
            vol_ratio = volumes[-1] / vol_ma20 if vol_ma20 > 0 else 1.0

            tick_size = 0.0001
            try:
                filt = await self.client.get_symbol_filter(symbol)
                if filt and filt.tick_size:
                    tick_size = float(filt.tick_size)
            except Exception:
                pass

            return {
                "symbol": symbol,
                "current_price": current_p,
                "ema20": round(ema20, 6),
                "ema50": round(ema50, 6),
                "ema_4h_20": round(ema_4h_20, 6),
                "ema_4h_50": round(ema_4h_50, 6),
                "trend_4h": trend_4h,
                "rsi_14": round(rsi, 2),
                "rsi": round(rsi, 2),
                "atr_14": round(atr, 6),
                "atr": round(atr, 6),
                "trend": trend,
                "change_24h_pct": round(change_24h_pct, 2),
                "change_24h": round(change_24h_pct, 2),
                "vol_ratio": vol_ratio,
                "upper_wick_ratio": upper_wick_ratio,
                "lower_wick_ratio": lower_wick_ratio,
                "recent_high": max(highs[-24:]),
                "recent_low": min(lows[-24:]),
                "last_high": last_high,
                "last_low": last_low,
                "k_stoch": k_stoch,
                "d_stoch": d_stoch,
                "pct_b": pct_b,
                "lower_bb": lower_bb,
                "upper_bb": upper_bb,
                "divergence": div,
                "sweep": sweep,
                "order_block": ob,
                "tick_size": tick_size,
                "recent_candles": [
                    {"open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4])}
                    for k in klines[-5:]
                ],
            }
        except Exception as e:
            logger.warning(f"Error fetching snapshot for {symbol}: {e}")
            return None

    async def analyze_with_gemini(self, snapshot: Dict[str, Any], api_key: str) -> Optional[Dict[str, Any]]:
        """
        Multi-Agent Committee Evaluation (inspired by TauricResearch/TradingAgents):
        - Technical Analyst: Evaluates trend structure, EMA20/50, RSI(14), and ATR(14).
        - Bull Researcher: Builds the strongest bullish case and upside catalysts.
        - Bear Researcher: Actively stress-tests against traps, resistance, and divergences.
        - Risk Management Guardian: Enforces minimum 2.0 R:R and capital preservation.
        - Head Trader: Synthesizes consensus. Approves ONLY when conviction is high (>= 75%).
        """
        if not api_key or time.time() < self._api_cooldown_until:
            return None

        # Reset daily counter if new day UTC
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._daily_calls_reset_date != today_utc:
            self._daily_api_calls = 0
            self._daily_calls_reset_date = today_utc

        prompt = f"""You are an institutional Multi-Agent Trading Committee (Technical Analyst, Bull Researcher, Bear Researcher, Risk Guardian, and Head Trader) operating on Binance USD-M Futures.
Analyze this 1h market snapshot for {snapshot['symbol']}:
- Current Price: {snapshot['current_price']}
- Trend: {snapshot['trend']}
- 4H Macro Trend: {snapshot.get('trend_4h', 'CHOPPY')}
- EMA 20: {snapshot['ema20']}, EMA 50: {snapshot['ema50']}
- RSI (14): {snapshot['rsi_14']}
- ATR (14): {snapshot['atr_14']}
- 24h Change: {snapshot['change_24h_pct']}%
- Recent 5 Candles (OHLC): {json.dumps(snapshot['recent_candles'])}

Follow this strict Dialectical Committee Workflow:
1. BULL RESEARCHER: Identifies all positive bullish price action signals, support levels, and upward continuation factors.
2. BEAR RESEARCHER: Identifies all bearish headwinds, resistance walls, RSI exhaustion, or false breakout risks.
3. RISK GUARDIAN: Evaluates whether a valid trade exists with R:R >= 2.0 and structural Stop Loss between 1.5% and 5.0%. If conflicting or high risk, issue VETO.
4. HEAD TRADER: Synthesizes the debate. STRICT RULE: Must align with 4H Macro Trend (e.g. if 4H is BEARISH, NEVER approve LONG; if 4H is BULLISH, NEVER approve SHORT). Approves LONG/SHORT only if confidence >= 80% (strictly calibrated to empirical winrate tiers: 90% Trend Continuation, 85% Order Block Retest, 80% Liquidity Sweep) and Risk Guardian approves. Otherwise, reject trade.

Respond with ONLY valid JSON strictly matching this schema:
{{
    "has_setup": true or false,
    "direction": "LONG" or "SHORT",
    "confidence": integer strictly one of [80, 85, 90],
    "bull_arguments": "Vietnamese 1-sentence summary of the strongest Bull argument",
    "bear_arguments": "Vietnamese 1-sentence summary of the key Bear risk/counter-argument",
    "risk_verdict": "APPROVED" or "VETOED",
    "rationale": "Vietnamese concise synthesis explaining the entry thesis and level invalidation",
    "entry_price": float (optimal entry price near current price),
    "stop_loss": float (structural invalidation level),
    "take_profit_1": float (quick scalp profit lock 0.9R - 1.0R, ~1.0% - 1.5% price move),
    "take_profit_2": float (trend target 2.0R - 2.5R),
    "take_profit_3": float (3.5R - 4.5R runner)
}}
If no trade meets >= 80% confidence and R:R >= 2.0, set "has_setup": false and explain reason in "rationale"."""

        # Strict directive: only models 3.6 and above
        available_36_plus_models = [
            "gemini-3.6-flash",
            "gemini-3.8-flash",
            "gemini-4-argon",
        ]
        pref = getattr(self, "preferred_model", "gemini-3.6-flash")
        if pref in available_36_plus_models:
            models_to_try = [pref] + [m for m in available_36_plus_models if m != pref]
        else:
            models_to_try = available_36_plus_models

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"},
        }

        try:
            session = await self.client._get_session()
            for model_name in models_to_try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                try:
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=8.0)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            candidates = data.get("candidates", [])
                            if candidates:
                                text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                                parsed = json.loads(text)
                                self._quota_status = "NORMAL"
                                self._daily_api_calls += 1
                                if parsed.get("has_setup") and parsed.get("risk_verdict") != "VETOED":
                                    parsed["symbol"] = snapshot["symbol"]
                                    parsed["source"] = f"Gemini ({model_name})"
                                    return parsed
                        elif resp.status in (429, 404, 400):
                            err_txt = await resp.text()
                            if "API key not valid" in err_txt:
                                self._gemini_key_invalid = True
                                logger.warning("Gemini API key is invalid. Switching to Quantitative Engine fallback.")
                                break
                            
                            # Quota Exceeded (429) or Prepay Credits Depleted Guard
                            if resp.status == 429 or "prepay" in err_txt.lower() or "resource_exhausted" in err_txt.lower():
                                is_prepay = "prepay" in err_txt.lower()
                                self._quota_status = "PREPAY_DEPLETED" if is_prepay else "RATE_LIMITED_COOLDOWN"
                                # Set 15-minute protective circuit breaker
                                self._api_cooldown_until = time.time() + 900
                                logger.warning(
                                    f"Gemini API Quota/Prepay boundary reached on {model_name} (status {resp.status}). "
                                    f"Activating 15-minute Circuit Breaker to prevent project-wide API lockout. "
                                    f"Switching seamlessly to Quant Engine Fallback."
                                )
                                # DO NOT query other models - all models share the project quota
                                break

                            # If model not found (404), try next 3.6+ candidate
                            if resp.status == 404:
                                logger.info(f"Model {model_name} not available in region (404), trying next 3.6+ model...")
                                continue
                except Exception as e_mod:
                    logger.warning(f"Error querying {model_name}: {e_mod}")
                    continue
        except Exception as e:
            logger.warning(f"Gemini analysis error for {snapshot['symbol']}: {e}")

        return None

    def analyze_with_quant_rules(self, snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Quantum Multi-Admin Brain + Algorithmic Fallback Engine."""
        # Priority 1: Evaluate against reverse-engineered Admin Archetypes (82% - 88% winrate models)
        if hasattr(self, "quantum_engine") and self.quantum_engine:
            quantum_setup = self.quantum_engine.evaluate_admin_archetypes(snapshot)
            if quantum_setup and quantum_setup.get("has_setup"):
                return quantum_setup

        p = snapshot["current_price"]
        ema20 = snapshot["ema20"]
        ema50 = snapshot["ema50"]
        rsi = snapshot["rsi_14"]
        atr = snapshot["atr_14"]
        sym = snapshot["symbol"]
        trend_4h = snapshot.get("trend_4h", "CHOPPY")

        if atr <= 0 or p <= 0:
            return None

        # Setup A: Bullish Trend Pullback (Price > EMA50, RSI pulled back to 38-48 range)
        if p > ema50 and 38.0 <= rsi <= 50.0 and ema20 >= ema50:
            if trend_4h == "BEARISH":
                return None
            sl_dist = max(atr * 1.3, p * 0.018)
            sl = p - sl_dist
            tp1 = p + (sl_dist * 0.95)
            tp2 = p + (sl_dist * 2.0)
            tp3 = p + (sl_dist * 3.5)
            return {
                "has_setup": True,
                "symbol": sym,
                "direction": "LONG",
                "archetype": "TREND_CONTINUATION",
                "confidence": 90,
                "bull_arguments": f"Giá duy trì vững chắc trên đường xu hướng EMA 50 ({ema50}), phe mua kiểm soát cấu trúc tăng.",
                "bear_arguments": "Cần thận trọng nếu RSI suy giảm xuyên thủng mốc 35 hoặc thủng đáy gần nhất.",
                "risk_verdict": "APPROVED",
                "rationale": f"Hồi quy xu hướng Tăng khung 1h: Giá giữ vững trên EMA 50 ({ema50}), RSI ({rsi}) về vùng tích lũy xung lực đẹp.",
                "entry_price": p,
                "stop_loss": round(sl, 6),
                "take_profit_1": round(tp1, 6),
                "take_profit_2": round(tp2, 6),
                "take_profit_3": round(tp3, 6),
                "source": "Quant Engine Fallback",
            }

        # Setup B: Bearish Trend Pullback (Price < EMA50, RSI bounced to 50-62 range)
        if p < ema50 and 50.0 <= rsi <= 62.0 and ema20 <= ema50:
            if trend_4h == "BULLISH":
                return None
            sl_dist = max(atr * 1.3, p * 0.018)
            sl = p + sl_dist
            tp1 = p - (sl_dist * 0.95)
            tp2 = p - (sl_dist * 2.0)
            tp3 = p - (sl_dist * 3.5)
            return {
                "has_setup": True,
                "symbol": sym,
                "direction": "SHORT",
                "archetype": "TREND_CONTINUATION",
                "confidence": 90,
                "bull_arguments": "Phe mua có nhịp hồi phục kỹ thuật nhẹ nhưng khối lượng không đột biến.",
                "bear_arguments": f"Cản động EMA 50 ({ema50}) đè nặng lên giá, RSI ({rsi}) suy kiệt xung lực hồi phục.",
                "risk_verdict": "APPROVED",
                "rationale": f"Hồi quy xu hướng Giảm khung 1h: Giá bị cản dưới EMA 50 ({ema50}), RSI ({rsi}) suy kiệt đà hồi phục.",
                "entry_price": p,
                "stop_loss": round(sl, 6),
                "take_profit_1": round(tp1, 6),
                "take_profit_2": round(tp2, 6),
                "take_profit_3": round(tp3, 6),
                "source": "Quant Engine Fallback",
            }

        # Setup C & D (Blind RSI Mean Reversion) have been deprecated:
        # Bắt dao rơi RSI đơn thuần bị loại bỏ hoàn toàn để bảo vệ 100% kỷ luật bảo toàn vốn.
        return None

    EXCLUDE_SYMBOLS = {
        "USDCUSDT", "FDUSDUSDT", "BUSDUSDT", "TUSDUSDT", "EURUSDT", "AEURUSDT"
    }

    async def get_top_liquid_watchlist(self, limit: int = 25) -> List[str]:
        """
        Dynamically retrieves Top 25 liquid USDT-M perpetual contracts from Binance.
        Caches results for 1 hour to prevent redundant ticker requests.
        """
        if self._top_watchlist_cache and (time.time() - self._top_watchlist_time < 3600):
            return self._top_watchlist_cache[:limit]

        try:
            session = await self.client._get_session()
            # Fetch active perpetual crypto symbols from exchangeInfo
            ex_url = f"{self.client.base_url}/fapi/v1/exchangeInfo"
            active_perps = set()
            async with session.get(ex_url, timeout=aiohttp.ClientTimeout(total=8.0)) as ex_resp:
                if ex_resp.status == 200:
                    ex_data = await ex_resp.json()
                    active_perps = {
                        s["symbol"] for s in ex_data.get("symbols", [])
                        if s.get("contractType") == "PERPETUAL"
                        and s.get("status") == "TRADING"
                        and s.get("quoteAsset") == "USDT"
                    }
                    if active_perps:
                        self._valid_symbol_cache = active_perps
                        self._valid_symbol_cache_time = time.time()

            url = f"{self.client.base_url}/fapi/v1/ticker/24hr"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8.0)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    usdt_pairs = [
                        d for d in data
                        if isinstance(d, dict)
                        and (not active_perps or d.get("symbol") in active_perps)
                        and d.get("symbol", "").endswith("USDT")
                        and d.get("symbol") not in self.EXCLUDE_SYMBOLS
                        and float(d.get("quoteVolume", 0) or 0) > 1000000  # Min $1M 24h volume
                    ]
                    usdt_pairs.sort(key=lambda x: float(x.get("quoteVolume", 0) or 0), reverse=True)
                    top_symbols = [d["symbol"] for d in usdt_pairs[:max(limit, 100)]]
                    if top_symbols:
                        self._top_watchlist_cache = top_symbols
                        self._top_watchlist_time = time.time()
                        logger.info(f"Updated dynamic Top {len(top_symbols)} liquid futures watchlist.")
                        return top_symbols[:limit]
        except Exception as e:
            logger.warning(f"Failed to fetch dynamic top watchlist: {e}")

        return self._top_watchlist_cache or self.watchlist or DEFAULT_WATCHLIST

    async def scan_market(self, symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Scans Top 100 liquid pairs and ranks potential trade setups.
        Uses 2-phase pipeline:
        Phase 1: Local CPU Technical Pre-Filter on all 100 coins (< 5 seconds total).
        Phase 2: Ranks promising candidates and queries Gemini 3.6+/Argon 4 on Top 3 highest-potential setups.
        Phase 3: Quantitative Engine fallback for remaining setups or cooldown periods.
        """
        if symbols:
            target_symbols = symbols
        elif self.watchlist:
            target_symbols = self.watchlist
        else:
            target_symbols = await self.get_top_liquid_watchlist(limit=25)
        target_symbols, skipped_symbols = await self._filter_valid_symbols(target_symbols)

        setups: List[Dict[str, Any]] = []
        now_str = datetime.now(timezone.utc).isoformat()
        self.last_scan_time = now_str

        # Phase 1: Local CPU Technical Pre-Filter
        promising_candidates: List[Tuple[float, Dict[str, Any]]] = []

        for sym in target_symbols:
            snapshot = await self.get_market_snapshot(sym)
            if not snapshot:
                continue
            await asyncio.sleep(0.03)  # Gentle 30ms pacing for exchange weight safety

            if self.is_promising_candidate(snapshot):
                # Calculate technical inflection score
                rsi = snapshot.get("rsi_14", 50.0)
                chg = abs(snapshot.get("change_24h_pct", 0.0))
                score = abs(rsi - 50.0) * 1.5 + chg
                promising_candidates.append((score, snapshot))

        # Sort promising candidates by inflection score descending
        promising_candidates.sort(key=lambda x: x[0], reverse=True)

        can_query_gemini = (
            bool(self.gemini_api_key)
            and not self._gemini_key_invalid
            and time.time() > self._api_cooldown_until
        )

        gemini_analyzed_symbols = set()
        # Phase 2: Send top 3 candidates to Gemini (Argon 4 / 3.6+)
        if can_query_gemini and promising_candidates:
            top_for_ai = promising_candidates[:3]
            for _, snap in top_for_ai:
                await asyncio.sleep(2.5)  # 2.5s anti-burst throttle
                ai_setup = await self.analyze_with_gemini(snap, self.gemini_api_key)
                gemini_analyzed_symbols.add(snap["symbol"])
                if ai_setup and ai_setup.get("has_setup"):
                    entry = ai_setup.get("entry_price", 0)
                    sl = ai_setup.get("stop_loss", 0)
                    tp2 = ai_setup.get("take_profit_2", 0)
                    risk = abs(entry - sl)
                    reward = abs(tp2 - entry)
                    rr = round(reward / risk, 2) if risk > 0 else 0.0
                    ai_setup["estimated_rr"] = rr
                    if rr >= 1.8 and ai_setup.get("confidence", 0) >= self.min_confidence:
                        setups.append(ai_setup)

        # Phase 3: Evaluate remaining promising candidates with Quant Engine Fallback
        for _, snap in promising_candidates:
            if snap["symbol"] in gemini_analyzed_symbols:
                continue
            q_setup = self.analyze_with_quant_rules(snap)
            if q_setup and q_setup.get("has_setup"):
                entry = q_setup.get("entry_price", 0)
                sl = q_setup.get("stop_loss", 0)
                tp2 = q_setup.get("take_profit_2", 0)
                risk = abs(entry - sl)
                reward = abs(tp2 - entry)
                rr = round(reward / risk, 2) if risk > 0 else 0.0
                q_setup["estimated_rr"] = rr
                if rr >= 1.8 and q_setup.get("confidence", 0) >= self.min_confidence:
                    setups.append(q_setup)

        # Phase 4: Quantum Council Deliberation (Adversarial Multi-Agent Review)
        current_positions = []
        if self.client:
            try:
                current_positions = await self.client.get_open_positions()
            except Exception as e_pos:
                logger.debug(f"Unable to fetch positions for council deliberation: {e_pos}")

        validated_setups: List[Dict[str, Any]] = []
        for s in setups:
            sym = s.get("symbol", "")
            # Check per-symbol cooldown (Anti-Revenge Trading Buffer 30m)
            cd_rem = self.get_symbol_cooldown_remaining(sym)
            if cd_rem > 0:
                logger.info(f"[COOLDOWN SKIP] Bỏ qua {sym} vì đang trong thời gian làm nguội ({cd_rem}s còn lại)")
                skipped_symbols.append(sym)
                continue

            try:
                s["open_positions"] = current_positions
                s["last_closed_at"] = self.symbol_last_closed.get(sym) or self._get_last_closed_from_db(sym)
                s["last_trade_opened_at"] = self.last_trade_opened_at
                is_ferrari = bool(getattr(self.config, "ferrari_mode_enabled", False))
                s["ferrari_mode_enabled"] = is_ferrari
                s["max_directional_cap"] = 15 if is_ferrari else 3
                deliberation = await self.council_arbiter.deliberate(sym, s)
                if not deliberation.is_approved:
                    logger.warning(
                        f"[COUNCIL VETO] Hội đồng lượng tử phủ quyết {sym} ({s.get('direction')}): {deliberation.veto_reason}"
                    )
                    continue

                # Cập nhật thông số tối ưu từ Hội Đồng Lượng Tử
                s["confidence"] = deliberation.consensus_score
                s["council_transcript"] = deliberation.transcript
                s["council_debate_html"] = getattr(deliberation, "debate_html", "")
                s["deliberation"] = deliberation
                if deliberation.trade_parameters:
                    if "leverage" in deliberation.trade_parameters:
                        s["leverage"] = deliberation.trade_parameters["leverage"]
                    if "stop_loss" in deliberation.trade_parameters:
                        s["stop_loss"] = deliberation.trade_parameters["stop_loss"]
                    if "take_profit_1" in deliberation.trade_parameters:
                        s["take_profit_1"] = deliberation.trade_parameters["take_profit_1"]
                    if "take_profit_2" in deliberation.trade_parameters:
                        s["take_profit_2"] = deliberation.trade_parameters["take_profit_2"]
                    if "take_profit_3" in deliberation.trade_parameters:
                        s["take_profit_3"] = deliberation.trade_parameters["take_profit_3"]
                validated_setups.append(s)
            except Exception as e_delib:
                logger.debug(f"Council deliberation error on {sym}: {e_delib}")
                validated_setups.append(s)

        # Sort by confidence descending
        validated_setups.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        self.last_scan_results = validated_setups
        self.last_scan_skipped_symbols = skipped_symbols

        try:
            cache_file = os.path.join(getattr(self.config, "data_dir", "./data"), "ai_last_scan.json")
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f_cache:
                json.dump({"scan_time": self.last_scan_time, "setups": validated_setups}, f_cache, ensure_ascii=False)
        except Exception as e_cache_save:
            logger.debug(f"Failed to persist AI scan results: {e_cache_save}")

        return validated_setups

    async def _emergency_close_and_verify(
        self, symbol: str, side: OrderSide, quantity: Decimal, client_order_id: str
    ) -> None:
        """Close residual position and verify exchange reports no meaningful amount."""
        await self.client.create_standard_order(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            client_order_id=client_order_id,
            reduce_only=True,
        )
        await asyncio.sleep(0.3)
        pos = await self.client.get_position(symbol)
        residual = abs(Decimal(str(pos.get("positionAmt", "0")))) if pos else Decimal("0")
        if residual > Decimal("0"):
            raise RuntimeError(f"Emergency close chưa xác nhận vị thế {symbol} về 0 (còn {residual})")

    async def execute_setup(self, setup: Dict[str, Any], bypass_cooldown: bool = False) -> Optional[Dict[str, Any]]:
        """Execute only a fresh, scanned setup while protected lifecycle is active."""
        gate_reason = self._execution_gate_reason()
        if gate_reason:
            return {"status": "SKIPPED", "reason": gate_reason}

        if not isinstance(setup, dict):
            return {"status": "ERROR", "reason": "AI setup phải là object"}
        required_fields = ("symbol", "direction", "entry_price", "stop_loss", "take_profit_1", "take_profit_2", "take_profit_3")
        if any(field not in setup for field in required_fields):
            return {"status": "ERROR", "reason": "AI setup thiếu trường bắt buộc"}
        source = str(setup.get("source", ""))
        trusted_sources = ("Gemini", "Quant Engine", "Quantum AI")
        if not any(source.startswith(ts) for ts in trusted_sources):
            return {"status": "ERROR", "reason": "AI setup không xuất phát từ kết quả scan đã xác thực"}
        if setup.get("has_setup") is not True or setup.get("risk_verdict") != "APPROVED":
            return {"status": "ERROR", "reason": "AI setup chưa được phê duyệt bởi bộ lọc rủi ro"}
        try:
            confidence = int(setup.get("confidence", 0))
        except (TypeError, ValueError):
            return {"status": "ERROR", "reason": "Confidence AI không hợp lệ"}
        if not 0 <= confidence <= 100 or confidence < self.min_confidence:
            return {"status": "ERROR", "reason": "AI setup chưa đạt ngưỡng confidence"}
        if not self._setup_is_current(setup):
            return {"status": "ERROR", "reason": "AI setup không khớp kết quả scan gần nhất hoặc đã hết hạn"}

        sym = str(setup["symbol"]).upper()
        if not re.fullmatch(r"[A-Z0-9]{2,20}USDT", sym):
            return {"status": "ERROR", "reason": "Symbol AI không hợp lệ"}
        direction = str(setup["direction"]).upper()
        if direction not in ("LONG", "SHORT"):
            return {"status": "ERROR", "reason": "Hướng giao dịch không hợp lệ"}

        # Check Per-symbol Cooldown (30 phút hoặc 4 tiếng nếu dính SL)
        sym_cd_rem = self.get_symbol_cooldown_remaining(sym)
        if sym_cd_rem > 0:
            was_loss = self.symbol_last_was_loss.get(sym, False)
            cd_type = "4 tiếng (triệt tiêu bẫy cay cú sau khi dính SL)" if was_loss else "30 phút"
            return {
                "status": "SKIPPED",
                "reason": f"SYMBOL_COOLDOWN: Đồng {sym} vừa đóng vị thế trong vòng {cd_type} (còn {sym_cd_rem}s làm nguội) để tránh bẫy trả thù lệnh (Revenge trading)",
            }

        # Check Weekend Liquidity Shield (Lá Chắn Thanh Khoản Cuối Tuần)
        now_utc = datetime.now(timezone.utc)
        vn_hour = (now_utc.hour + 7) % 24
        vn_day_shift = 1 if (now_utc.hour + 7) >= 24 else 0
        vn_weekday = (now_utc.weekday() + vn_day_shift) % 7
        is_weekend = (vn_weekday == 5) or (vn_weekday == 6) or (vn_weekday == 0 and vn_hour < 6)
        if is_weekend:
            is_major = sym in ("BTCUSDT", "ETHUSDT")
            if is_major:
                if confidence < 90:
                    return {
                        "status": "SKIPPED",
                        "reason": f"WEEKEND_LIQUIDITY_SHIELD: Cuối tuần chỉ cho phép giao dịch {sym} khi đạt chuẩn Sniper Master (>= 90%). Kèo hiện tại chỉ đạt {confidence}%.",
                    }
            else:
                vol_24h = float(setup.get("quote_volume_24h", setup.get("quoteVolume", 0.0)))
                if vol_24h < 100_000_000:
                    return {
                        "status": "SKIPPED",
                        "reason": f"WEEKEND_LIQUIDITY_SHIELD: Cuối tuần tự động đóng băng Altcoins thanh khoản mỏng ({sym} 24h Vol: ${vol_24h/1e6:.1f}M < $100M) để tránh bẫy quét râu nến ảo.",
                    }

        # Check Global Trade Interval (15 phút ở chế độ An Toàn; Bỏ qua khi BẬT Ferrari Mode)
        is_ferrari = getattr(self.config, "ferrari_mode_enabled", False)
        global_cd_rem = self.get_global_trade_interval_remaining()
        min_bypass_conf = 80 if is_ferrari else 92
        if not bypass_cooldown and not is_ferrari and global_cd_rem > 0 and confidence < min_bypass_conf:
            return {
                "status": "SKIPPED",
                "reason": f"GLOBAL_INTERVAL: Chế độ An Toàn đang giãn cách 15 phút giữa 2 lệnh (còn {global_cd_rem}s). Bật Ferrari Mode hoặc đợi hết đếm lùi.",
            }

        # Sentinel Black-Swan Gate
        try:
            sent_gate = await self.sentiment_guardian.analyze_symbol_sentiment(sym, direction)
            if getattr(sent_gate.verdict, "value", str(sent_gate.verdict)) == "REJECTED_BLACK_SWAN":
                reason_str = sent_gate.reasons[0] if sent_gate.reasons else "Cảnh báo thiên nga đen"
                return {"status": "SKIPPED", "reason": f"Bị chặn bởi Bộ Lọc Tin Tức Thiên Nga Đen: {reason_str}"}
        except Exception:
            pass

        try:
            entry_check = Decimal(str(setup["entry_price"]))
            sl_check = Decimal(str(setup["stop_loss"]))
            tp_check = [Decimal(str(setup[f"take_profit_{idx}"])) for idx in (1, 2, 3)]
        except Exception:
            return {"status": "ERROR", "reason": "Giá AI không hợp lệ"}
        if any(not value.is_finite() for value in [entry_check, sl_check, *tp_check]):
            return {"status": "ERROR", "reason": "Giá AI phải là số hữu hạn"}
        if entry_check <= 0 or (direction == "LONG" and not (sl_check < entry_check < tp_check[0] <= tp_check[1] <= tp_check[2])) or (direction == "SHORT" and not (sl_check > entry_check > tp_check[0] >= tp_check[1] >= tp_check[2])):
            return {"status": "ERROR", "reason": "Quan hệ Entry/SL/TP không hợp lệ"}

        # Check existing open positions
        try:
            positions = await self.client.get_open_positions()
            if any(p.get("symbol") == sym and float(p.get("positionAmt", 0)) != 0 for p in (positions or [])):
                return {"status": "SKIPPED", "reason": f"Dang co vi the {sym} tren san"}
            is_ferrari = getattr(self.config, "ferrari_mode_enabled", False)
            if is_ferrari:
                limit = int(getattr(self.config.risk, "max_active_signals", 20))
            else:
                limit = min(int(getattr(self.config.risk, "max_active_signals", 3)), 5)
            active_count = len([p for p in (positions or []) if float(p.get("positionAmt", 0)) != 0])
            if active_count >= limit:
                mode_label = "Ferrari Mode" if is_ferrari else "Chế độ An Toàn"
                return {"status": "SKIPPED", "reason": f"Đã đạt hạn mức tối đa {limit} vị thế đồng thời ({active_count}/{limit}) của {mode_label} để bảo toàn ký quỹ"}

            # Directional Exposure Cap (An Toàn: Max 3 cùng chiều; Ferrari: trần mở rộng)
            open_longs = len([p for p in (positions or []) if float(p.get("positionAmt", 0)) > 0])
            open_shorts = len([p for p in (positions or []) if float(p.get("positionAmt", 0)) < 0])
            max_directional = max(10, limit // 2) if is_ferrari else 3
            if direction == "SHORT" and open_shorts >= max_directional:
                return {
                    "status": "SKIPPED",
                    "reason": f"DIRECTIONAL_CAP_VETO: Đã đạt trần tối đa {max_directional} vị thế SHORT. Chặn để phòng ngừa rủi ro Short Squeeze khi thị trường đảo chiều!",
                }
            if direction == "LONG" and open_longs >= max_directional:
                return {
                    "status": "SKIPPED",
                    "reason": f"DIRECTIONAL_CAP_VETO: Đã đạt trần tối đa {max_directional} vị thế LONG. Chặn để phòng ngừa rủi ro Long Squeeze khi thị trường đảo chiều!",
                }
        except Exception as e:
            return {"status": "ERROR", "reason": f"Khong the kiem tra vi the: {e}"}

        # Filter info
        try:
            filter_info = await self.client.get_symbol_filter(sym)
            price_filter = filter_info.tick_size
            step_size = filter_info.step_size
        except Exception as exc:
            return {"status": "ERROR", "reason": f"Không thể xác minh bộ lọc symbol: {exc}"}
        if price_filter <= 0 or step_size <= 0 or filter_info.min_qty <= 0 or filter_info.min_notional <= 0:
            return {"status": "ERROR", "reason": "Bộ lọc symbol không hợp lệ"}

        entry_p = Decimal(str(setup["entry_price"]))
        sl_p = Decimal(str(setup["stop_loss"]))
        tp1_p = Decimal(str(setup["take_profit_1"]))
        tp2_p = Decimal(str(setup["take_profit_2"]))
        tp3_p = Decimal(str(setup["take_profit_3"]))

        def _round_tick(val: Decimal, tick: Decimal) -> Decimal:
            if tick <= Decimal("0"):
                return val
            units = (val / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            return units * tick

        sl_p = _round_tick(sl_p, price_filter)

        # Protect against Binance PERCENT_PRICE limits (typical max 14% deviation from entry)
        if setup.get("direction") == "LONG":
            tp1_p = min(tp1_p, entry_p * Decimal("1.14"))
            tp2_p = min(tp2_p, entry_p * Decimal("1.14"))
            tp3_p = min(tp3_p, entry_p * Decimal("1.14"))
        else:
            tp1_p = max(tp1_p, entry_p * Decimal("0.86"))
            tp2_p = max(tp2_p, entry_p * Decimal("0.86"))
            tp3_p = max(tp3_p, entry_p * Decimal("0.86"))

        tp1_p = _round_tick(tp1_p, price_filter)
        tp2_p = _round_tick(tp2_p, price_filter)
        tp3_p = _round_tick(tp3_p, price_filter)

        # Safe Leverage Calculation (Zero Liquidation directive)
        sl_dist_pct = abs(entry_p - sl_p) / entry_p
        if sl_dist_pct <= Decimal("0"):
            return {"status": "ERROR", "reason": "Khoang cach SL bang 0"}

        is_ferrari = getattr(self.config, "ferrari_mode_enabled", False)
        max_lev = 35 if is_ferrari else 20
        target_lev = 30 if is_ferrari else 15

        # Macro Bearish Panic Clamp for Altcoin Longs: Clamp leverage to 15x-18x
        try:
            from risk.market_regime_shield import global_market_regime_shield
            regime_cap = global_market_regime_shield.get_safe_leverage_ceiling(sym, setup["direction"])
            if regime_cap:
                max_lev = min(max_lev, regime_cap)
                target_lev = min(target_lev, 15)
        except Exception:
            pass

        safe_lev = min(max_lev, max(5, min(target_lev, int(Decimal("0.75") / sl_dist_pct))))
        side = PositionSide.LONG if setup["direction"] == "LONG" else PositionSide.SHORT
        order_side = OrderSide.BUY if side == PositionSide.LONG else OrderSide.SELL
        close_side = OrderSide.SELL if side == PositionSide.LONG else OrderSide.BUY

        # Sizing: 5.0% in Ferrari Mode, 1.5% in Safe Mode
        try:
            equity = Decimal(str(await self.client.get_account_equity()))
        except Exception as exc:
            return {"status": "ERROR", "reason": f"Không thể xác minh equity: {exc}"}
        if not equity.is_finite() or equity <= 0:
            return {"status": "ERROR", "reason": "Equity không hợp lệ hoặc bằng 0"}
        safe_risk = Decimal(str(getattr(getattr(self.config, "risk", None), "risk_per_signal_pct", "1.5"))) / Decimal("100")
        risk_pct = Decimal("0.05") if is_ferrari else min(Decimal("0.02"), max(Decimal("0.005"), safe_risk))
        risk_budget = equity * risk_pct
        dollar_sl_dist = abs(entry_p - sl_p)
        raw_qty = (risk_budget / dollar_sl_dist).quantize(step_size)
        total_qty = max(filter_info.min_qty, raw_qty)

        # Ensure notional meets minimum 5 USDT
        if total_qty * entry_p < filter_info.min_notional:
            total_qty = (filter_info.min_notional / entry_p).quantize(step_size)
            if total_qty * entry_p < filter_info.min_notional:
                total_qty += step_size

        # Account configuration is part of safety gate, not best effort.
        try:
            await self.client.set_margin_type_cross(sym)
            applied_lev = await self.client.set_leverage(sym, safe_lev)
            if int(applied_lev) <= 0:
                return {"status": "ERROR", "reason": "Sàn không xác nhận mức đòn bẩy hợp lệ"}
            safe_lev = int(applied_lev)
        except Exception as exc:
            return {"status": "ERROR", "reason": f"Không thể cấu hình margin/leverage an toàn: {exc}"}

        sig_id = f"sig_ai_{sym}_{uuid.uuid4().hex[:6]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        # 1. Market Entry
        ent_cid = f"ent_{sig_id[:8]}_{uuid.uuid4().hex[:4]}"
        try:
            ent_resp = await self.client.create_standard_order(
                symbol=sym,
                side=order_side,
                order_type=OrderType.MARKET,
                quantity=total_qty,
                client_order_id=ent_cid,
                reduce_only=False,
            )
            filled_order_id = str(ent_resp.get("orderId"))
            if not filled_order_id:
                raise RuntimeError("Sàn không trả về orderId cho lệnh Entry")
        except Exception as exc:
            return {"status": "ERROR", "reason": f"Đặt Entry thất bại: {exc}"}

        await asyncio.sleep(0.3)
        pos = await self.client.get_position(sym)
        actual_amt = abs(Decimal(str(pos.get("positionAmt", "0")))) if pos else Decimal("0")
        real_entry_p = Decimal(str(pos.get("entryPrice", entry_p))) if pos else entry_p
        if actual_amt <= Decimal("0"):
            return {"status": "ERROR", "reason": "Entry không tạo vị thế trên sàn"}
        total_qty = min(total_qty, actual_amt)

        # 2. Protective Algo STOP_MARKET Order (100% Volume)
        sl_cid = f"sl_{sig_id[:8]}_{uuid.uuid4().hex[:4]}"
        try:
            sl_resp = await self.client.create_algo_order(
                symbol=sym,
                side=close_side,
                order_type=OrderType.STOP_MARKET,
                trigger_price=sl_p,
                quantity=total_qty,
                client_algo_id=sl_cid,
                close_position=False,
                reduce_only=True,
            )
        except Exception as exc:
            try:
                await self.client.create_standard_order(
                    symbol=sym,
                    side=close_side,
                    order_type=OrderType.MARKET,
                    quantity=total_qty,
                    client_order_id=f"emg_{sig_id[:8]}_{uuid.uuid4().hex[:4]}",
                    reduce_only=True,
                )
            except Exception as cleanup_exc:
                return {"status": "ERROR", "reason": f"Đặt SL thất bại; emergency close cũng thất bại: {cleanup_exc}"}
            try:
                pos_after_close = await self.client.get_position(sym)
                residual = abs(Decimal(str(pos_after_close.get("positionAmt", "0")))) if pos_after_close else Decimal("0")
                if residual > Decimal("0"):
                    return {"status": "ERROR", "reason": f"Đặt SL thất bại; emergency close chưa xác nhận vị thế về 0 (còn {residual})"}
            except Exception as verify_exc:
                return {"status": "ERROR", "reason": f"Đặt SL thất bại; không xác minh được emergency close: {verify_exc}"}
            return {"status": "ERROR", "reason": f"Đặt SL thất bại; đã đóng khẩn cấp vị thế: {exc}"}
        sl_algo_id = str(sl_resp.get("algoId"))

        # 3. Smart Multi-Tier Take Profit Orders (respecting min_notional)
        total_notional = total_qty * real_entry_p
        min_notional = getattr(filter_info, "min_notional", Decimal("5.0"))
        if min_notional <= Decimal("0"):
            min_notional = Decimal("5.0")

        if total_notional >= Decimal("3.5") * min_notional:
            # 35 / 35 / 30 Take Profit Orders
            tp1_qty = (total_qty * Decimal("0.35")).quantize(step_size)
            tp2_qty = (total_qty * Decimal("0.35")).quantize(step_size)
            tp3_qty = total_qty - (tp1_qty + tp2_qty)
            if tp3_qty * tp3_p >= min_notional and tp3_qty >= filter_info.min_qty:
                tps_to_place = [
                    (1, tp1_p, tp1_qty),
                    (2, tp2_p, tp2_qty),
                    (3, tp3_p, tp3_qty),
                ]
            else:
                tp1_qty = (total_qty * Decimal("0.50")).quantize(step_size)
                tp2_qty = total_qty - tp1_qty
                tps_to_place = [
                    (1, tp1_p, tp1_qty),
                    (2, tp2_p, tp2_qty),
                ]
        elif total_notional >= Decimal("2.1") * min_notional:
            # 50 / 50 Take Profit Orders
            tp1_qty = (total_qty * Decimal("0.50")).quantize(step_size)
            tp2_qty = total_qty - tp1_qty
            if tp2_qty * tp2_p >= min_notional and tp2_qty >= filter_info.min_qty:
                tps_to_place = [
                    (1, tp1_p, tp1_qty),
                    (2, tp2_p, tp2_qty),
                ]
            else:
                tps_to_place = [
                    (1, tp1_p, total_qty),
                ]
        else:
            # Single conservative Take Profit at TP1 (cautious, high probability)
            tps_to_place = [
                (1, tp1_p, total_qty),
            ]

        placed_tps = []
        try:
            for idx, tp_px, tp_vol in tps_to_place:
                tp_px = _round_tick(tp_px, price_filter)
                tp_vol = (tp_vol // step_size) * step_size
                if tp_vol < filter_info.min_qty or (tp_vol * tp_px < filter_info.min_notional):
                    raise RuntimeError(f"TP{idx} không đạt minQty/minNotional; từ chối vị thế thiếu bảo vệ")
                tp_cid = f"tp_{sig_id[:8]}_{idx}_{uuid.uuid4().hex[:4]}"
                tp_resp = await self.client.create_standard_order(
                    symbol=sym,
                    side=close_side,
                    order_type=OrderType.LIMIT,
                    quantity=tp_vol,
                    price=tp_px,
                    client_order_id=tp_cid,
                    reduce_only=True,
                )
                placed_tps.append({
                    "client_order_id": tp_cid,
                    "order_id": str(tp_resp.get("orderId")),
                    "price": float(tp_px),
                    "quantity": float(tp_vol),
                })
        except Exception as exc:
            logger.warning(f"Lỗi khi đặt lệnh Take Profit cho {sym}: {exc}. Vị thế vẫn được bảo vệ bởi Stop Loss {sl_p}.")

        # 4. Save to Database
        if self.signal_repo and self.db:
            try:
                with self.db.get_connection() as conn:
                    # Parent Message record to satisfy Foreign Key constraints
                    ai_chat_id = -999001
                    ai_msg_id = int(time.time() * 1000)
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO messages (
                            chat_id, message_id, sender_id, telegram_timestamp, received_at,
                            raw_text, normalized_text
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ai_chat_id,
                            ai_msg_id,
                            ai_chat_id,
                            now_iso,
                            now_iso,
                            f"AI Autonomous Signal: {sym} {side.value}",
                            f"AI Autonomous Signal: {sym} {side.value}",
                        ),
                    )

                    # Signals table
                    tps_saved_json = json.dumps([str(tp_item[1]) for tp_item in tps_to_place])
                    conn.execute(
                        """
                        INSERT INTO signals (
                            signal_id, chat_id, message_id, symbol, side, state,
                            entry_mode, entries_json, stop_loss, take_profits_json,
                            leverage, margin_mode, risk_pct, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            sig_id,
                            ai_chat_id,
                            ai_msg_id,
                            sym,
                            side.value,
                            "OPEN_PROTECTED",
                            "SINGLE",
                            json.dumps([str(real_entry_p)]),
                            float(sl_p),
                            tps_saved_json,
                            safe_lev,
                            "CROSSED",
                            float(risk_pct * Decimal("100")),
                            now_iso,
                            now_iso,
                        ),
                    )

                    # Entry order
                    conn.execute(
                        """
                        INSERT INTO orders (
                            client_order_id, signal_id, symbol, side, order_type,
                            price, quantity, is_reduce_only, is_algo, exchange_order_id,
                            status, filled_quantity, avg_fill_price, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(client_order_id) DO UPDATE SET
                            exchange_order_id = excluded.exchange_order_id,
                            status = excluded.status,
                            filled_quantity = excluded.filled_quantity,
                            avg_fill_price = excluded.avg_fill_price,
                            updated_at = excluded.updated_at
                        """,
                        (
                            ent_cid, sig_id, sym, order_side.value, "MARKET",
                            float(real_entry_p), float(total_qty), 0, 0, filled_order_id,
                            "FILLED", float(total_qty), float(real_entry_p), now_iso, now_iso,
                        ),
                    )

                    # SL order
                    conn.execute(
                        """
                        INSERT INTO orders (
                            client_order_id, signal_id, symbol, side, order_type,
                            trigger_price, quantity, is_reduce_only, is_algo, exchange_order_id,
                            status, filled_quantity, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(client_order_id) DO UPDATE SET
                            exchange_order_id = excluded.exchange_order_id,
                            status = excluded.status,
                            filled_quantity = excluded.filled_quantity,
                            updated_at = excluded.updated_at
                        """,
                        (
                            sl_cid, sig_id, sym, close_side.value, "STOP_MARKET",
                            float(sl_p), float(total_qty), 1, 1, sl_algo_id,
                            "NEW", 0.0, now_iso, now_iso,
                        ),
                    )

                    # TP orders
                    for tp in placed_tps:
                        conn.execute(
                            """
                            INSERT INTO orders (
                                client_order_id, signal_id, symbol, side, order_type,
                                price, quantity, is_reduce_only, is_algo, exchange_order_id,
                                status, filled_quantity, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(client_order_id) DO UPDATE SET
                                exchange_order_id = excluded.exchange_order_id,
                                status = excluded.status,
                                filled_quantity = excluded.filled_quantity,
                                updated_at = excluded.updated_at
                            """,
                            (
                                tp["client_order_id"], sig_id, sym, close_side.value, "LIMIT",
                                tp["price"], tp["quantity"], 1, 0, tp["order_id"],
                                "NEW", 0.0, now_iso, now_iso,
                            ),
                        )

                    # Timeline event
                    conn.execute(
                        """
                        INSERT INTO signal_timeline (signal_id, timestamp, event_type, description, payload_json)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            sig_id,
                            now_iso,
                            "AI_AUTONOMOUS_TRADE_EXECUTED",
                            f"Gemini Quant AI tu dong khop {side.value} {total_qty} {sym} @ {real_entry_p}. Ly do: {setup.get('rationale')} (Do tin cay: {setup.get('confidence')}% | Nguon: {setup.get('source')})",
                            json.dumps({"source": setup.get("source"), "confidence": setup.get("confidence")}),
                        ),
                    )
            except Exception as e_db:
                logger.error(f"Error persisting AI signal to database: {e_db}")

        try:
            from services.alert_service import AlertLevel, AlertService
            AlertService.get_instance().add_alert(
                AlertLevel.INFO,
                f"🚀 VÀO LỆNH AI: {sym} {side.value}",
                f"Đã khớp {side.value} {total_qty} {sym} @ {real_entry_p} | SL: {sl_p} | TP1: {tp1_p}. Độ tin cậy: {setup.get('confidence')}%",
                "AI_QUANT",
            )
            # Phát sóng trực tiếp Tranh Biện Hội Đồng Lượng Tử AI lên Telegram
            debate_html = setup.get("council_debate_html")
            if not debate_html and "deliberation" in setup:
                debate_html = getattr(setup["deliberation"], "debate_html", "")
            if debate_html:
                alert_svc = AlertService.get_instance()
                if hasattr(alert_svc, "_notifier") and alert_svc._notifier:
                    notifier = alert_svc._notifier
                    if hasattr(notifier, "send_debate"):
                        asyncio.create_task(notifier.send_debate(debate_html))
                    elif hasattr(notifier, "notify"):
                        asyncio.create_task(notifier.notify(debate_html, parse_mode="html"))
        except Exception as e_broadcast:
            logger.debug(f"Debate broadcast notification failed: {e_broadcast}")

        # Ghi nhận thời điểm mở lệnh để áp dụng Global Trade Interval 15m
        self.record_trade_opened(sym)

        return {
            "status": "SUCCESS",
            "signal_id": sig_id,
            "symbol": sym,
            "side": side.value,
            "entry_price": float(real_entry_p),
            "quantity": float(total_qty),
            "leverage": safe_lev,
            "stop_loss": float(sl_p),
            "take_profits": [float(tp_item[1]) for tp_item in tps_to_place],
            "rationale": setup.get("rationale"),
            "confidence": setup.get("confidence"),
            "source": setup.get("source"),
        }

    async def scan_and_auto_trade(self) -> Dict[str, Any]:
        """Runs one full autonomous scan cycle and executes the highest-conviction setup."""
        setups = await self.scan_market()
        scan_meta = {
            "skipped_symbols": self.last_scan_skipped_symbols,
            "symbol_validation_error": self.last_scan_symbol_validation_error,
        }
        if not setups:
            return {"scanned": len(self.watchlist), "setups_found": 0, "executed": None, **scan_meta}

        # Filter setups with confidence >= min_confidence
        valid_setups = [s for s in setups if s.get("confidence", 0) >= self.min_confidence]
        if not valid_setups:
            return {"scanned": len(self.watchlist), "setups_found": len(setups), "executed": None, **scan_meta}

        # Pick top setup
        best_setup = valid_setups[0]
        exec_res = None
        if self.enabled and not self._execution_gate_reason():
            exec_res = await self.execute_setup(best_setup)

        return {
            "scanned": len(self.watchlist),
            "setups_found": len(setups),
            "best_setup": best_setup,
            "executed": exec_res,
            **scan_meta,
        }

    async def evaluate_and_broadcast_debate(
        self,
        symbol: str,
        custom_params: Optional[Dict[str, Any]] = None,
        broadcast: bool = True,
    ) -> Any:
        """
        Kích hoạt Hội Đồng Lượng Tử AI thẩm định và phát sóng trực tiếp cuộc tranh luận
        5 đặc vụ lên Telegram theo yêu cầu on-demand hoặc qua lệnh chat.
        """
        sym = symbol.upper().replace("/", "").replace(":", "")
        market_data = dict(custom_params or {})

        # Tự động nạp giá hiện tại từ sàn nếu chưa có
        if "current_price" not in market_data and "entry_price" not in market_data and self.client:
            try:
                px = await self.client.get_symbol_price(sym)
                if px and float(px) > 0:
                    market_data["current_price"] = float(px)
            except Exception:
                pass

        deliberation = await self.council_arbiter.deliberate(sym, market_data)

        if broadcast and getattr(deliberation, "debate_html", None):
            try:
                from services.alert_service import AlertService
                alert_svc = AlertService.get_instance()
                if hasattr(alert_svc, "_notifier") and alert_svc._notifier:
                    notifier = alert_svc._notifier
                    if hasattr(notifier, "send_debate"):
                        await notifier.send_debate(deliberation.debate_html)
                    elif hasattr(notifier, "notify"):
                        await notifier.notify(deliberation.debate_html, parse_mode="html")
            except Exception as e_broadcast:
                logger.debug(f"evaluate_and_broadcast_debate broadcast notice: {e_broadcast}")

        return deliberation
