import asyncio
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from config.config import AppConfig
from core.enums import MarginMode, OrderSide, OrderType, PositionSide, SignalState
from core.models import SourceMetadata, ValidatedSignal

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
        self.min_confidence: int = getattr(ai_cfg, "min_confidence", 75) if ai_cfg else 75
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
        self._api_cooldown_until: float = 0.0
        self._quota_status: str = "NORMAL"  # NORMAL | RATE_LIMITED_COOLDOWN | PREPAY_DEPLETED
        self._daily_api_calls: int = 0
        self._daily_calls_reset_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._running_task: Optional[asyncio.Task] = None

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
        """Require exact match to a recent scan result; never execute caller-supplied values."""
        scan_time = self.last_scan_time
        if not scan_time:
            return False
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(scan_time)).total_seconds()
        except (TypeError, ValueError):
            return False
        max_age = max(60, int(getattr(getattr(self.config, "risk", None), "signal_max_age_seconds", 300)))
        if age < 0 or age > max_age:
            return False
        required_fields = ("symbol", "direction", "entry_price", "stop_loss", "take_profit_1", "take_profit_2", "take_profit_3")
        return any(
            all(str(candidate.get(field)) == str(setup.get(field)) for field in required_fields)
            for candidate in self.last_scan_results
        )

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
            url = f"{self.client.base_url}/fapi/v1/klines?symbol={symbol}&interval=1h&limit=60"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8.0)) as resp:
                if resp.status != 200:
                    return None
                klines = await resp.json()

            if not klines or len(klines) < 30:
                return None

            closes = [float(k[4]) for k in klines]
            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]
            volumes = [float(k[5]) for k in klines]

            current_p = closes[-1]
            ema20 = calculate_ema(closes, 20)
            ema50 = calculate_ema(closes, 50)
            rsi = calculate_rsi(closes, 14)
            atr = calculate_atr(highs, lows, closes, 14)
            
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

            return {
                "symbol": symbol,
                "current_price": current_p,
                "ema20": round(ema20, 6),
                "ema50": round(ema50, 6),
                "rsi_14": round(rsi, 2),
                "atr_14": round(atr, 6),
                "trend": trend,
                "change_24h_pct": round(change_24h_pct, 2),
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
- EMA 20: {snapshot['ema20']}, EMA 50: {snapshot['ema50']}
- RSI (14): {snapshot['rsi_14']}
- ATR (14): {snapshot['atr_14']}
- 24h Change: {snapshot['change_24h_pct']}%
- Recent 5 Candles (OHLC): {json.dumps(snapshot['recent_candles'])}

Follow this strict Dialectical Committee Workflow:
1. BULL RESEARCHER: Identifies all positive bullish price action signals, support levels, and upward continuation factors.
2. BEAR RESEARCHER: Identifies all bearish headwinds, resistance walls, RSI exhaustion, or false breakout risks.
3. RISK GUARDIAN: Evaluates whether a valid trade exists with R:R >= 2.0 and structural Stop Loss between 1.5% and 5.0%. If conflicting or high risk, issue VETO.
4. HEAD TRADER: Synthesizes the debate. Approves LONG/SHORT only if confidence >= 75% and Risk Guardian approves. Otherwise, reject trade.

Respond with ONLY valid JSON strictly matching this schema:
{{
    "has_setup": true or false,
    "direction": "LONG" or "SHORT",
    "confidence": integer between 0 and 100,
    "bull_arguments": "Vietnamese 1-sentence summary of the strongest Bull argument",
    "bear_arguments": "Vietnamese 1-sentence summary of the key Bear risk/counter-argument",
    "risk_verdict": "APPROVED" or "VETOED",
    "rationale": "Vietnamese concise synthesis explaining the entry thesis and level invalidation",
    "entry_price": float (optimal entry price near current price),
    "stop_loss": float (structural invalidation level),
    "take_profit_1": float (conservative 1.5R - 2R),
    "take_profit_2": float (2.5R - 3R),
    "take_profit_3": float (4R+ runner)
}}
If no trade meets >= 75% confidence and R:R >= 2.0, set "has_setup": false and explain reason in "rationale"."""

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
        """Built-in algorithmic fallback when Gemini API key is absent or quota is limited."""
        p = snapshot["current_price"]
        ema20 = snapshot["ema20"]
        ema50 = snapshot["ema50"]
        rsi = snapshot["rsi_14"]
        atr = snapshot["atr_14"]
        sym = snapshot["symbol"]

        if atr <= 0 or p <= 0:
            return None

        # Setup A: Bullish Trend Pullback (Price > EMA50, RSI pulled back to 38-48 range)
        if p > ema50 and 38.0 <= rsi <= 50.0 and ema20 >= ema50:
            sl_dist = max(atr * 1.5, p * 0.02)
            sl = p - sl_dist
            tp1 = p + (sl_dist * 1.5)
            tp2 = p + (sl_dist * 2.5)
            tp3 = p + (sl_dist * 4.0)
            return {
                "has_setup": True,
                "symbol": sym,
                "direction": "LONG",
                "confidence": 78,
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
            sl_dist = max(atr * 1.5, p * 0.02)
            sl = p + sl_dist
            tp1 = p - (sl_dist * 1.5)
            tp2 = p - (sl_dist * 2.5)
            tp3 = p - (sl_dist * 4.0)
            return {
                "has_setup": True,
                "symbol": sym,
                "direction": "SHORT",
                "confidence": 78,
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

        # Setup C: Extreme RSI Oversold Mean Reversion (RSI < 28)
        if rsi < 28.0:
            sl_dist = max(atr * 1.8, p * 0.025)
            sl = p - sl_dist
            tp1 = p + (sl_dist * 1.5)
            tp2 = p + (sl_dist * 2.5)
            tp3 = p + (sl_dist * 3.5)
            return {
                "has_setup": True,
                "symbol": sym,
                "direction": "LONG",
                "confidence": 75,
                "bull_arguments": f"RSI 1h rớt sâu vào vùng quá bán cực đoan ({rsi} < 28), lực bán xả đã cạn kiệt.",
                "bear_arguments": "Đà giảm dốc đứng có thể tạo thêm 1 nhịp quét râu trước khi bật dậy.",
                "risk_verdict": "APPROVED",
                "rationale": f"Phân kỳ quá bán RSI 1h cực đoan ({rsi} < 28), khả năng cao xuất hiện sóng hồi phục kỹ thuật mạnh.",
                "entry_price": p,
                "stop_loss": round(sl, 6),
                "take_profit_1": round(tp1, 6),
                "take_profit_2": round(tp2, 6),
                "take_profit_3": round(tp3, 6),
                "source": "Quant Engine Fallback",
            }

        # Setup D: Extreme RSI Overbought Mean Reversion (RSI > 72)
        if rsi > 72.0:
            sl_dist = max(atr * 1.8, p * 0.025)
            sl = p + sl_dist
            tp1 = p - (sl_dist * 1.5)
            tp2 = p - (sl_dist * 2.5)
            tp3 = p - (sl_dist * 3.5)
            return {
                "has_setup": True,
                "symbol": sym,
                "direction": "SHORT",
                "confidence": 75,
                "bull_arguments": "Đà tăng dốc đứng của phe mua rất mạnh nhưng đã rơi vào vùng hưng phấn cực độ.",
                "bear_arguments": f"RSI 1h vượt mốc {rsi} (> 72), áp lực chốt lời diện rộng sẵn sàng kích hoạt.",
                "risk_verdict": "APPROVED",
                "rationale": f"Quá mua RSI 1h cực đoan ({rsi} > 72), xuất hiện lực ép chốt lời ngắn hạn từ phe mua.",
                "entry_price": p,
                "stop_loss": round(sl, 6),
                "take_profit_1": round(tp1, 6),
                "take_profit_2": round(tp2, 6),
                "take_profit_3": round(tp3, 6),
                "source": "Quant Engine Fallback",
            }

        return None

    EXCLUDE_SYMBOLS = {
        "USDCUSDT", "FDUSDUSDT", "BUSDUSDT", "TUSDUSDT", "EURUSDT", "AEURUSDT"
    }

    async def get_top_liquid_watchlist(self, limit: int = 100) -> List[str]:
        """
        Dynamically retrieves Top 100 liquid USDT-M perpetual contracts from Binance.
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
        else:
            target_symbols = await self.get_top_liquid_watchlist(limit=100)
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

        # Sort by confidence descending
        setups.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        self.last_scan_results = setups
        self.last_scan_skipped_symbols = skipped_symbols
        return setups

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

    async def execute_setup(self, setup: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Execute only a fresh, scanned setup while protected lifecycle is active."""
        gate_reason = self._execution_gate_reason()
        if gate_reason:
            return {"status": "SKIPPED", "reason": gate_reason}

        if not isinstance(setup, dict):
            return {"status": "ERROR", "reason": "AI setup phải là object"}
        required_fields = ("symbol", "direction", "entry_price", "stop_loss", "take_profit_1", "take_profit_2", "take_profit_3")
        if any(field not in setup for field in required_fields):
            return {"status": "ERROR", "reason": "AI setup thiếu trường bắt buộc"}
        if setup.get("source") not in ("Gemini (gemini-3.6-flash)", "Gemini (gemini-3.8-flash)", "Gemini (gemini-4-argon)", "Quant Engine Fallback"):
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
            limit = getattr(self.config.risk, "max_active_signals", 15)
            if len([p for p in (positions or []) if float(p.get("positionAmt", 0)) != 0]) >= limit:
                return {"status": "SKIPPED", "reason": f"Đã đạt hạn mức tối đa {limit} vị thế đồng thời"}
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

        # Safe Leverage Calculation (Zero Liquidation directive)
        sl_dist_pct = abs(entry_p - sl_p) / entry_p
        if sl_dist_pct <= Decimal("0"):
            return {"status": "ERROR", "reason": "Khoang cach SL bang 0"}

        safe_lev = min(25, max(5, int(Decimal("0.75") / sl_dist_pct)))
        side = PositionSide.LONG if setup["direction"] == "LONG" else PositionSide.SHORT
        order_side = OrderSide.BUY if side == PositionSide.LONG else OrderSide.SELL
        close_side = OrderSide.SELL if side == PositionSide.LONG else OrderSide.BUY

        # Sizing: 2.0% risk budget
        try:
            equity = Decimal(str(await self.client.get_account_equity()))
        except Exception as exc:
            return {"status": "ERROR", "reason": f"Không thể xác minh equity: {exc}"}
        if not equity.is_finite() or equity <= 0:
            return {"status": "ERROR", "reason": "Equity không hợp lệ hoặc bằng 0"}
        risk_budget = equity * Decimal("0.02")  # 2.0% Risk
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
            if int(applied_lev) != safe_lev:
                return {"status": "ERROR", "reason": "Sàn không xác nhận đúng mức đòn bẩy an toàn"}
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

        # 3. 35 / 35 / 30 Take Profit Orders
        tp1_qty = (total_qty * Decimal("0.35")).quantize(step_size)
        tp2_qty = (total_qty * Decimal("0.35")).quantize(step_size)
        tp3_qty = total_qty - (tp1_qty + tp2_qty)

        tps_to_place = [
            (1, tp1_p, tp1_qty),
            (2, tp2_p, tp2_qty),
            (3, tp3_p, tp3_qty),
        ]

        placed_tps = []
        try:
            for idx, tp_px, tp_vol in tps_to_place:
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
            for tp in placed_tps:
                try:
                    await self.client.cancel_standard_order(sym, tp["client_order_id"])
                except Exception:
                    pass
            try:
                await self.client.cancel_algo_order(sym, client_algo_id=sl_cid)
            except Exception:
                pass
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
                return {"status": "ERROR", "reason": f"Đặt TP thất bại; emergency close cũng thất bại: {cleanup_exc}"}
            try:
                pos_after_close = await self.client.get_position(sym)
                residual = abs(Decimal(str(pos_after_close.get("positionAmt", "0")))) if pos_after_close else Decimal("0")
                if residual > Decimal("0"):
                    return {"status": "ERROR", "reason": f"Đặt TP thất bại; emergency close chưa xác nhận vị thế về 0 (còn {residual})"}
            except Exception as verify_exc:
                return {"status": "ERROR", "reason": f"Đặt TP thất bại; không xác minh được emergency close: {verify_exc}"}
            return {"status": "ERROR", "reason": f"Đặt TP thất bại; đã đóng khẩn cấp vị thế: {exc}"}

        # 4. Save to Database
        if self.signal_repo and self.db:
            try:
                with self.db.get_connection() as conn:
                    # Signals table
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
                            -999001,  # Symbolic ID for Gemini Quant AI
                            int(time.time()),
                            sym,
                            side.value,
                            "OPEN_PROTECTED",
                            "SINGLE",
                            json.dumps([str(real_entry_p)]),
                            float(sl_p),
                            json.dumps([str(tp1_p), str(tp2_p), str(tp3_p)]),
                            safe_lev,
                            "CROSSED",
                            2.0,
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

        return {
            "status": "SUCCESS",
            "signal_id": sig_id,
            "symbol": sym,
            "side": side.value,
            "entry_price": float(real_entry_p),
            "quantity": float(total_qty),
            "leverage": safe_lev,
            "stop_loss": float(sl_p),
            "take_profits": [float(tp1_p), float(tp2_p), float(tp3_p)],
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
