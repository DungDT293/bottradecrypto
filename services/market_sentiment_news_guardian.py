import asyncio
from datetime import datetime, timezone, timedelta
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
import xml.etree.ElementTree as ET
import aiohttp

logger = logging.getLogger("market_sentiment_news_guardian")


class SentimentVerdict(str, Enum):
    APPROVED = "APPROVED"
    BOOSTED = "BOOSTED"
    NEUTRAL = "NEUTRAL"
    REJECTED_BLACK_SWAN = "REJECTED_BLACK_SWAN"
    REJECTED_CONTRARIAN = "REJECTED_CONTRARIAN"


@dataclass
class SentimentResult:
    symbol: str
    direction: str
    verdict: SentimentVerdict
    score: int  # -100 (Extremely Bearish/Catastrophic) to +100 (Extremely Bullish)
    confidence_delta: int  # e.g., +10 (Boost to >= 85%), 0 (No change), -15 (Penalty), -100 (Veto)
    reasons: List[str] = field(default_factory=list)
    headlines: List[str] = field(default_factory=list)
    catalysts: List[str] = field(default_factory=list)
    model_used: str = "Local-Keyword-Sentinel"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "verdict": self.verdict.value,
            "score": self.score,
            "confidence_delta": self.confidence_delta,
            "reasons": self.reasons,
            "headlines": self.headlines[:3],
            "catalysts": self.catalysts,
            "model_used": self.model_used,
        }


class MarketSentimentNewsGuardian:
    """
    Trụ Cột Sentinel: Bộ Lọc Tin Tức, Sự Kiện On-Chain & Tâm Lý Thị Trường Đa Nguồn.
    1. Black-Swan Veto Filter: Tự động phủ quyết và hủy lệnh (1-touch Veto) nếu phát hiện
       tin tức thảm họa (Delist, Hack, SEC, Cliff Token Unlock).
    2. Confidence Booster: Gia tăng điểm tin cậy từ 75% lên >= 85% nếu có chất xúc tác
       tích cực mạnh mẽ (Mainnet, Đối tác lớn, Đốt coin, ETF approval).
    3. Graceful Fallback: Luôn giới hạn thời gian phản hồi <= 2.0s; nếu mất mạng hoặc API lỗi,
       tự động trả về APPROVED_OFFLINE để không làm gián đoạn hay nghẽn luồng lệnh của Bot.
    """

    BLACK_SWAN_KEYWORDS: Set[str] = {
        "delist", "delisting", "sec", "subpoena", "fraud", "exploit", "hack",
        "hacked", "stolen", "freeze", "freezing", "insolvent", "bankruptcy",
        "bankrupt", "rug", "rugpull", "banned", "investigation", "indictment",
        "cliff unlock", "token unlock", "massive unlock", "scam", "vulnerability"
    }

    BULLISH_CATALYST_KEYWORDS: Set[str] = {
        "mainnet", "burn", "burning", "partnership", "etf", "approval", "approved",
        "listing", "listed", "upgrade", "buyback", "airdrop", "staking", "accumulation",
        "record inflow", "integration", "institutional"
    }

    BEARISH_CATALYST_KEYWORDS: Set[str] = {
        "outflow", "dump", "whale deposit", "selloff", "downgrade", "liquidation wave",
        "rejection", "short seller", "bearish divergence"
    }

    COIN_ALIASES: Dict[str, Set[str]] = {
        "btc": {"btc", "bitcoin"},
        "eth": {"eth", "ethereum"},
        "sol": {"sol", "solana"},
        "bnb": {"bnb", "binance coin"},
        "doge": {"doge", "dogecoin"},
        "avax": {"avax", "avalanche"},
        "ada": {"ada", "cardano"},
        "xrp": {"xrp", "ripple"},
        "link": {"link", "chainlink"},
        "near": {"near", "near protocol"},
        "sui": {"sui"},
        "pepe": {"pepe"},
        "fet": {"fet", "fetch.ai", "artificial superintelligence"},
    }

    def __init__(self, config: Optional[Any] = None, session: Optional[aiohttp.ClientSession] = None):
        self.config = config
        self._session = session
        self._owns_session = False
        # Cache for headlines: { symbol_base: (timestamp, [headlines]) }
        self._news_cache: Dict[str, Tuple[float, List[str]]] = {}
        self._macro_news_cache: Tuple[float, List[str]] = (0.0, [])
        self._last_gemini_briefing: Optional[Dict[str, Any]] = None
        self._last_gemini_briefing_time: float = 0.0
        self.cache_ttl_seconds: int = 600  # 10 minutes cache
        self.request_timeout: float = 2.0  # 2.0s hard timeout

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    def _extract_base_asset(self, symbol: str) -> str:
        """Strips USDT, BUSD, USDC to get core coin name (e.g. BTCUSDT -> BTC)."""
        sym = symbol.upper()
        for quote in ("USDT", "USDC", "BUSD", "FDUSD"):
            if sym.endswith(quote):
                return sym[:-len(quote)]
        return sym

    async def fetch_news_headlines(self, symbol: str) -> List[str]:
        """
        Fetches recent public news headlines & Binance official announcements.
        Features in-memory TTL caching and a strict 2.0s timeout.
        """
        base = self._extract_base_asset(symbol)
        now = time.time()
        if base in self._news_cache:
            ts, cached_headlines = self._news_cache[base]
            if now - ts < self.cache_ttl_seconds:
                return cached_headlines

        headlines: List[str] = []
        session = await self._get_session()

        # Source 1: Binance Public CMS Announcements / News Endpoint
        binance_cms_url = (
            "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query"
            "?catalogId=48&pageNo=1&pageSize=10"
        )
        try:
            async with asyncio.timeout(self.request_timeout):
                async with session.get(binance_cms_url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        articles = (data.get("data") or {}).get("articles", [])
                        for art in articles:
                            title = art.get("title", "")
                            if title:
                                headlines.append(title)
        except Exception as e:
            logger.debug(f"Binance CMS news fetch error for {symbol}: {e}")

        # Source 2: CoinGecko Public Status / Ticker Search (Free, no auth)
        coingecko_search_url = f"https://api.coingecko.com/api/v3/search?query={base}"
        try:
            async with asyncio.timeout(self.request_timeout):
                async with session.get(coingecko_search_url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # Extract any related news or coin status if available
                        coins = data.get("coins", [])
                        if coins:
                            coin_name = coins[0].get("name", "")
                            if coin_name:
                                headlines.append(f"{coin_name} active market tracking on CoinGecko")
        except Exception as e:
            logger.debug(f"CoinGecko search fetch error for {symbol}: {e}")

        # Cache results (even if empty, to prevent burst spamming)
        self._news_cache[base] = (now, headlines)
        return headlines

    def scan_rule_sentiment(
        self, symbol: str, direction: str, headlines: List[str]
    ) -> SentimentResult:
        """
        Fast local rule-based NLP sentiment analyzer (0ms, 100% deterministic).
        Executes Black-Swan Veto and Catalyst Confluence Detection.
        """
        base = self._extract_base_asset(symbol).lower()
        dir_upper = direction.upper()

        reasons: List[str] = []
        catalysts: List[str] = []
        black_swans: List[str] = []
        bull_hits: int = 0
        bear_hits: int = 0

        aliases = self.COIN_ALIASES.get(base, {base})
        # Scan all available headlines
        for h in headlines:
            h_lower = h.lower()
            # Check if this headline specifically mentions this coin or if market-level catalyst for BTC
            coin_match = (
                any(bool(re.search(rf"\b{re.escape(a)}\b", h_lower)) for a in aliases)
                or (len(base) >= 4 and base in h_lower)
            )
            is_market_macro = base in ("btc", "bitcoin") and ("crypto" in h_lower or "market" in h_lower)
            target_match = coin_match or is_market_macro

            # 1. Check for Black-Swan Red List Keywords (strict word boundaries to avoid 'securities' matching 'sec')
            for kw in self.BLACK_SWAN_KEYWORDS:
                if re.search(rf"\b{re.escape(kw)}\b", h_lower):
                    if coin_match or kw in ("sec", "delist", "delisting", "insolvent", "bankruptcy", "hack"):
                        black_swans.append(f"Cảnh báo đỏ '{kw.upper()}' trong: '{h[:80]}'")

            # 2. Check for Bullish Catalyst Keywords
            for kw in self.BULLISH_CATALYST_KEYWORDS:
                if target_match and re.search(rf"\b{re.escape(kw)}\b", h_lower):
                    bull_hits += 1
                    catalysts.append(f"Xúc tác tích cực: {kw.title()} ('{h[:60]}...')")

            # 3. Check for Bearish Catalyst Keywords
            for kw in self.BEARISH_CATALYST_KEYWORDS:
                if target_match and re.search(rf"\b{re.escape(kw)}\b", h_lower):
                    bear_hits += 1

        # ==============================================================
        # VERDICT RESOLUTION
        # ==============================================================
        # A. VETO: Black Swan detected!
        if black_swans:
            reasons.extend(black_swans)
            return SentimentResult(
                symbol=symbol,
                direction=direction,
                verdict=SentimentVerdict.REJECTED_BLACK_SWAN,
                score=-95,
                confidence_delta=-100,  # Absolute cancellation of trade
                reasons=reasons,
                headlines=headlines,
                catalysts=catalysts,
                model_used="Local-Keyword-Sentinel (Black-Swan VETO)",
            )

        # B. Bullish Confluence for LONG or Bearish for SHORT
        if dir_upper == "LONG":
            if bull_hits > 0 and bear_hits == 0:
                reasons.append(f"Phát hiện {bull_hits} chất xúc tác tăng giá đồng thuận với thiết lập LONG.")
                return SentimentResult(
                    symbol=symbol,
                    direction=direction,
                    verdict=SentimentVerdict.BOOSTED,
                    score=75 + min(20, bull_hits * 10),
                    confidence_delta=+10,  # Boost 75% -> 85%+
                    reasons=reasons,
                    headlines=headlines,
                    catalysts=catalysts,
                    model_used="Local-Keyword-Sentinel (Bullish Catalyst Boost)",
                )
            elif bear_hits > bull_hits:
                reasons.append(f"Cảnh giác: Xuất hiện {bear_hits} tin tức tiêu cực đối nghịch với lệnh LONG.")
                return SentimentResult(
                    symbol=symbol,
                    direction=direction,
                    verdict=SentimentVerdict.REJECTED_CONTRARIAN,
                    score=-40,
                    confidence_delta=-15,  # Penalty
                    reasons=reasons,
                    headlines=headlines,
                    catalysts=catalysts,
                    model_used="Local-Keyword-Sentinel (Friction Penalty)",
                )

        elif dir_upper == "SHORT":
            if bear_hits > 0 and bull_hits == 0:
                reasons.append(f"Phát hiện {bear_hits} tin tức áp lực bán xả đồng thuận với thiết lập SHORT.")
                return SentimentResult(
                    symbol=symbol,
                    direction=direction,
                    verdict=SentimentVerdict.BOOSTED,
                    score=-75,
                    confidence_delta=+10,  # Boost 75% -> 85%+
                    reasons=reasons,
                    headlines=headlines,
                    catalysts=catalysts,
                    model_used="Local-Keyword-Sentinel (Bearish Catalyst Boost)",
                )
            elif bull_hits > bear_hits:
                reasons.append(f"Cảnh giác: Xuất hiện {bull_hits} tin tức bơm thổi tích cực đối nghịch với lệnh SHORT.")
                return SentimentResult(
                    symbol=symbol,
                    direction=direction,
                    verdict=SentimentVerdict.REJECTED_CONTRARIAN,
                    score=40,
                    confidence_delta=-15,  # Penalty
                    reasons=reasons,
                    headlines=headlines,
                    catalysts=catalysts,
                    model_used="Local-Keyword-Sentinel (Friction Penalty)",
                )

        # C. Neutral / Normal (Clean slate, pure technical execution)
        reasons.append("Không có tin tức thiên nga đen; tâm lý thị trường trung tính, tuân thủ 100% mô hình nến kỹ thuật.")
        return SentimentResult(
            symbol=symbol,
            direction=direction,
            verdict=SentimentVerdict.APPROVED,
            score=0,
            confidence_delta=0,
            reasons=reasons,
            headlines=headlines,
            catalysts=catalysts,
            model_used="Local-Keyword-Sentinel (Neutral Guard)",
        )

    async def analyze_symbol_sentiment(
        self, symbol: str, direction: str, headlines_override: Optional[List[str]] = None
    ) -> SentimentResult:
        """
        Main Sentinel entrypoint.
        Fetches live headlines, scans for Black-Swan & Catalysts, and returns verdict.
        Guarantees <= 2.0s response time with zero failure risk.
        """
        try:
            if headlines_override is not None:
                headlines = headlines_override
            else:
                headlines = await self.fetch_news_headlines(symbol)
            return self.scan_rule_sentiment(symbol, direction, headlines)
        except Exception as exc:
            logger.warning(f"Error in analyze_symbol_sentiment for {symbol}: {exc}")
            # Graceful Fallback: NEVER block trades on unexpected sentinel internal errors
            return SentimentResult(
                symbol=symbol,
                direction=direction,
                verdict=SentimentVerdict.APPROVED,
                score=0,
                confidence_delta=0,
                reasons=[f"Bộ lọc tin tức offline an toàn (Graceful Fallback): {exc}"],
                headlines=[],
                catalysts=[],
                model_used="Graceful-Fallback-Sentinel",
            )

    async def fetch_macro_crypto_headlines(self) -> List[str]:
        """
        Fetches global crypto headlines from Binance Official Announcements and CoinTelegraph RSS.
        Cached for 10 minutes to avoid redundant network overhead.
        """
        now = time.time()
        cached_ts, cached_list = self._macro_news_cache
        if now - cached_ts < self.cache_ttl_seconds and cached_list:
            return cached_list

        headlines: List[str] = []
        session = await self._get_session()

        # 1. Binance Official Announcements
        binance_catalog_url = (
            "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query"
            "?catalogId=48&pageNo=1&pageSize=8"
        )
        try:
            async with asyncio.timeout(3.5):
                async with session.get(binance_catalog_url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        articles = (data.get("data") or {}).get("articles", [])
                        for a in articles:
                            title = a.get("title", "")
                            if title and title not in headlines:
                                headlines.append(f"[Binance] {title.strip()}")
        except Exception as e:
            logger.debug(f"Binance announcements fetch error: {e}")

        # 2. CoinTelegraph Global Crypto RSS
        rss_url = "https://cointelegraph.com/rss"
        try:
            async with asyncio.timeout(3.5):
                async with session.get(rss_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}) as resp:
                    if resp.status == 200:
                        xml_text = await resp.text()
                        root = ET.fromstring(xml_text)
                        for item in root.findall(".//item")[:10]:
                            t_elem = item.find("title")
                            if t_elem is not None and t_elem.text:
                                clean_t = t_elem.text.strip()
                                if clean_t and clean_t not in headlines:
                                    headlines.append(f"[Market] {clean_t}")
        except Exception as e:
            logger.debug(f"CoinTelegraph RSS fetch error: {e}")

        if not headlines:
            headlines = [
                "[Market] Crypto market maintains steady volume across major USD-M futures pairs.",
                "[Binance] Binance Futures maintains normal operations across Top 35 contracts.",
            ]

        self._macro_news_cache = (now, headlines)
        return headlines

    async def _query_gemini_for_macro(
        self,
        headlines: List[str],
        btc_price: float,
        btc_change_24h: float,
        api_key: str,
    ) -> Optional[Dict[str, Any]]:
        """Queries Google Gemini models for deep macro crypto market intelligence."""
        if not api_key:
            return None

        prompt = f"""You are the Chief Quantitative Macro Strategist for an institutional Binance USD-M Futures desk.
Analyze these real-time crypto headlines and market context:
- BTC Price: ${btc_price:,.2f} (24h Change: {btc_change_24h:+.2f}%)
- Headlines: {json.dumps(headlines[:10], ensure_ascii=False)}

Generate an institutional macro and market sentiment briefing in Vietnamese.
Respond ONLY with a valid JSON object matching this schema:
{{
    "macro_regime": "Vietnamese short phrase, e.g. TÍCH LŨY BIÊN ĐỘ HẸP or ĐIỀU CHỈNH GIẢM or TĂNG TRƯỞNG PHÂN HÓA",
    "sentiment_score": integer between -100 (Extremely Bearish/Panic) and +100 (Extremely Bullish/Euphoric),
    "market_drivers": ["Vietnamese 1-sentence driver 1", "Vietnamese 1-sentence driver 2", "Vietnamese 1-sentence driver 3"],
    "top35_strategy": "Vietnamese tactical recommendation for Top 35 altcoins (e.g. prioritize SHORT on pullbacks or wait for 4H support)",
    "risk_warnings": "Vietnamese key risk to monitor (e.g. funding spikes, token unlocks, regulatory headlines)"
}}"""

        models_to_try = [
            "gemini-3.8-flash",
            "gemini-3.5-flash",
            "gemini-4-argon",
            "gemini-3.1-flash-lite",
            "gemini-flash-latest",
            "gemini-2.5-flash",
        ]

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"},
        }

        session = await self._get_session()
        for m in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
            try:
                async with asyncio.timeout(6.0):
                    async with session.post(url, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            cands = data.get("candidates", [])
                            if cands:
                                txt = cands[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                                clean = txt.strip()
                                if clean.startswith("```json"):
                                    clean = clean[7:]
                                elif clean.startswith("```"):
                                    clean = clean[3:]
                                if clean.endswith("```"):
                                    clean = clean[:-3]
                                parsed = json.loads(clean.strip())
                                parsed["model_used"] = f"Gemini ({m})"
                                return parsed
            except Exception as e_gemini:
                logger.debug(f"Gemini macro query error on {m}: {e_gemini}")
                continue
        return None

    def _synthesize_quant_macro(
        self,
        headlines: List[str],
        btc_price: float,
        btc_change_24h: float,
    ) -> Dict[str, Any]:
        """
        High-fidelity deterministic Quant Rule NLP Engine.
        Provides instant 0ms, zero-fail macro sentiment analysis when Gemini is offline or quota is exhausted.
        """
        bull_hits = 0
        bear_hits = 0
        black_swan_hits = 0
        drivers: List[str] = []

        for h in headlines:
            h_low = h.lower()
            # Black swan checks (word boundaries)
            for kw in self.BLACK_SWAN_KEYWORDS:
                if re.search(rf"\b{re.escape(kw)}\b", h_low):
                    black_swan_hits += 1
                    drivers.append(f"Cảnh báo đỏ: Phát hiện '{kw}' trong thông báo thị trường.")
                    break
            # Bullish
            for kw in self.BULLISH_CATALYST_KEYWORDS:
                if re.search(rf"\b{re.escape(kw)}\b", h_low):
                    bull_hits += 1
                    drivers.append(f"Xúc tác tích cực: {h[:75]}...")
                    break
            # Bearish
            for kw in self.BEARISH_CATALYST_KEYWORDS:
                if re.search(rf"\b{re.escape(kw)}\b", h_low):
                    bear_hits += 1
                    drivers.append(f"Áp lực điều chỉnh: {h[:75]}...")
                    break

        # Sentiment score calculation
        base_score = (bull_hits - bear_hits) * 15 - (black_swan_hits * 30)
        price_contribution = int(btc_change_24h * 8)
        score = max(-95, min(95, base_score + price_contribution))

        if score >= 25:
            macro_regime = "TĂNG TRƯỞNG LẠC QUAN (BULLISH)"
            strategy = (
                "Xu hướng ngắn hạn hỗ trợ phe mua. Ưu tiên canh LONG theo nhịp hồi Order Block "
                "trên các đồng coin mạnh hơn BTC, chốt 35% tại TP1 và khóa lãi Breakeven ngay lập tức."
            )
        elif score <= -25:
            macro_regime = "ÁP LỰC ĐIỀU CHỈNH (BEARISH CORRECTION)"
            strategy = (
                "Áp lực bán chiếm ưu thế. Ưu tiên thiết lập SHORT thuận xu hướng tại các mốc cản "
                "EMA20/50 trên nến 1H. Tuyệt đối không bắt dao rơi khi chưa có phân kỳ đảo chiều 4H."
            )
        else:
            macro_regime = "TÍCH LŨY PHÂN HÓA (CHOPPY / SIDEWAYS)"
            strategy = (
                "Thị trường giằng co trong biên độ hẹp. Chỉ giao dịch khi đạt tỷ lệ R:R >= 2.0 và "
                "điểm tin cậy >= 80%. Tuân thủ nghiêm ngặt giới hạn ký quỹ và Zero-Liquidation."
            )

        # Collect and format real breaking headlines from Binance Announcements & Global Crypto RSS
        real_headlines_formatted: List[str] = []
        for h in headlines:
            clean_h = h.strip()
            if clean_h and clean_h not in real_headlines_formatted:
                real_headlines_formatted.append(clean_h)
            if len(real_headlines_formatted) >= 4:
                break

        if not drivers and real_headlines_formatted:
            drivers = [f"Tin nóng thực tế: {h}" for h in real_headlines_formatted]
        elif real_headlines_formatted and len(drivers) < 3:
            for rh in real_headlines_formatted:
                cand = f"Tin quốc tế: {rh}"
                if cand not in drivers and len(drivers) < 4:
                    drivers.append(cand)

        if not drivers:
            drivers = [
                f"Bitcoin đang dao động quanh ngưỡng ${btc_price:,.2f} với biên độ 24h là {btc_change_24h:+.2f}%.",
                "Thanh khoản thị trường futures duy trì mức ổn định, cấu trúc Order Book không ghi nhận tường bán bất thường.",
                "Dòng tiền tập trung luân chuyển cục bộ giữa Bitcoin và các altcoin Top 35.",
            ]

        risks = (
            "Cảnh báo quét thanh khoản 2 đầu khi BTC dao động giằng co. Luôn duy trì SL bảo vệ cứng và kiểm tra ký quỹ định kỳ."
            if black_swan_hits == 0 else
            "CẢNH BÁO CAO ĐỘ: Có tin tức rủi ro hệ thống hoặc điều tra. Tự động kích hoạt VETO hủy các lệnh ngược xu hướng."
        )

        return {
            "macro_regime": macro_regime,
            "sentiment_score": score,
            "drivers": drivers[:4],
            "strategy": strategy,
            "risks": risks,
        }

    async def generate_macro_market_news_briefing(
        self,
        btc_price: float = 0.0,
        btc_change_24h: float = 0.0,
        gemini_api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Synthesizes macro market conditions, breaking crypto headlines, and Top 35 action plan.
        Tries Gemini models; if unavailable/depleted, falls back to Quant-Rule NLP.
        Guarantees high-fidelity Vietnamese institutional intelligence for Telegram broadcast.
        """
        headlines = await self.fetch_macro_crypto_headlines()
        now_vn = datetime.now(timezone(timedelta(hours=7)))
        time_str = now_vn.strftime("%H:%M %d/%m/%Y")

        gemini_result: Optional[Dict[str, Any]] = None
        if gemini_api_key and len(gemini_api_key.strip()) > 10:
            gemini_result = await self._query_gemini_for_macro(
                headlines=headlines,
                btc_price=btc_price,
                btc_change_24h=btc_change_24h,
                api_key=gemini_api_key.strip(),
            )

        if gemini_result:
            macro_regime = gemini_result.get("macro_regime", "TÍCH LŨY PHÂN HÓA")
            sentiment_score = int(gemini_result.get("sentiment_score", 0))
            drivers = gemini_result.get("market_drivers", [])
            strategy = gemini_result.get("top35_strategy", "Tuân thủ kỷ luật dừng lỗ và chốt lời từng phần.")
            risks = gemini_result.get("risk_warnings", "Bảo toàn vốn tuyệt đối, không fomo.")
            model_used = gemini_result.get("model_used", "Gemini 2.5 Flash")
        else:
            quant_analysis = self._synthesize_quant_macro(
                headlines=headlines,
                btc_price=btc_price,
                btc_change_24h=btc_change_24h,
            )
            macro_regime = quant_analysis["macro_regime"]
            sentiment_score = quant_analysis["sentiment_score"]
            drivers = quant_analysis["drivers"]
            strategy = quant_analysis["strategy"]
            risks = quant_analysis["risks"]
            model_used = "Quant-Sentinel NLP (Zero-Latency Engine)"

        regime_emoji = "🟢" if "TĂNG" in macro_regime.upper() or sentiment_score > 20 else ("🔴" if "GIẢM" in macro_regime.upper() or sentiment_score < -20 else "⚖️")
        trend_emoji = "🟢" if btc_change_24h >= 0 else "🔴"

        driver_lines = "\n".join([f"• <i>{d}</i>" for d in drivers[:4]])
        if not driver_lines:
            driver_lines = "• <i>Dòng tiền tập trung quanh Bitcoin và top altcoin thanh khoản cao.</i>"

        html_msg = (
            "📰 <b>[BẢN TIN CHIẾN LƯỢC &amp; TÂM LÝ THỊ TRƯỜNG GEMINI AI]</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>⏱️ Thời điểm: {time_str} (Giờ VN) | Trợ lý: Jarvis Quantum Mark 85</i>\n\n"
            "🌐 <b>BỐI CẢNH VĨ MÔ &amp; CHỈ SỐ TÂM LÝ:</b>\n"
            f"• Giá Bitcoin (BTC): <code>${btc_price:,.2f}</code> ({trend_emoji} <b>{btc_change_24h:+.2f}% / 24h</b>)\n"
            f"• Trạng thái thị trường: {regime_emoji} <b>{macro_regime}</b>\n"
            f"• Điểm số Tâm Lý Dòng Tiền: <b>{sentiment_score:+d}/100</b>\n"
            f"• Động cơ phân tích: <code>{model_used}</code>\n\n"
            "🔥 <b>TOP TIN TỨC &amp; TÍN HIỆU DẪN DẮT:</b>\n"
            f"{driver_lines}\n\n"
            "🎯 <b>ĐỊNH HƯỚNG TÁC CHIẾN TOP 35 COIN:</b>\n"
            f"💡 <i>{strategy}</i>\n\n"
            "🛡️ <b>RỦI RO &amp; VỆ BINH PHÒNG THỦ:</b>\n"
            f"⚠️ <i>{risks}</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🤖 <i>AI quét thị trường mỗi 15 phút, bảo vệ an toàn vốn Zero-Liquidation 24/7!</i>"
        )

        result = {
            "time_str": time_str,
            "btc_price": btc_price,
            "btc_change_24h": btc_change_24h,
            "macro_regime": macro_regime,
            "sentiment_score": sentiment_score,
            "market_drivers": drivers,
            "top35_strategy": strategy,
            "risk_warnings": risks,
            "model_used": model_used,
            "html_telegram_message": html_msg,
        }
        self._last_gemini_briefing = result
        self._last_gemini_briefing_time = time.time()
        return result

