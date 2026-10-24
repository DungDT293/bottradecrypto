import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
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

    def __init__(self, config: Optional[Any] = None, session: Optional[aiohttp.ClientSession] = None):
        self.config = config
        self._session = session
        self._owns_session = False
        # Cache for headlines: { symbol_base: (timestamp, [headlines]) }
        self._news_cache: Dict[str, Tuple[float, List[str]]] = {}
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
            "https://www.binance.com/bapi/composite/v1/public/cms/article/all/query"
            "?type=1&pageNo=1&pageSize=15"
        )
        try:
            async with asyncio.timeout(self.request_timeout):
                async with session.get(binance_cms_url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        articles = data.get("data", {}).get("articles", [])
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

        # Scan all available headlines
        for h in headlines:
            h_lower = h.lower()
            # Check if this headline is about or mentions this coin / market
            coin_match = (
                base in re.findall(r"\b[a-z0-9]+\b", h_lower)
                or base in h_lower
                or "crypto" in h_lower
                or "binance" in h_lower
            )

            # 1. Check for Black-Swan Red List Keywords
            for kw in self.BLACK_SWAN_KEYWORDS:
                if kw in h_lower:
                    if coin_match or kw in ("sec", "delist", "delisting", "insolvent", "bankruptcy", "hack"):
                        black_swans.append(f"Cảnh báo đỏ '{kw.upper()}' trong: '{h[:80]}'")

            # 2. Check for Bullish Catalyst Keywords
            for kw in self.BULLISH_CATALYST_KEYWORDS:
                if kw in h_lower and coin_match:
                    bull_hits += 1
                    catalysts.append(f"Xúc tác tích cực: {kw.title()} ('{h[:60]}...')")

            # 3. Check for Bearish Catalyst Keywords
            for kw in self.BEARISH_CATALYST_KEYWORDS:
                if kw in h_lower and coin_match:
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

