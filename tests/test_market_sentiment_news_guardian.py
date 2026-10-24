import pytest
from services.market_sentiment_news_guardian import (
    MarketSentimentNewsGuardian,
    SentimentVerdict,
)


@pytest.mark.asyncio
async def test_black_swan_veto_delist():
    guardian = MarketSentimentNewsGuardian()
    headlines = [
        "Binance Will Delist DOGEUSDT and Several Margin Pairs on October 25",
        "Market rallies across major cryptocurrencies",
    ]
    res = await guardian.analyze_symbol_sentiment("DOGEUSDT", "LONG", headlines_override=headlines)
    assert res.verdict == SentimentVerdict.REJECTED_BLACK_SWAN
    assert res.confidence_delta == -100
    assert any("DELIST" in r for r in res.reasons)
    await guardian.close()


@pytest.mark.asyncio
async def test_black_swan_veto_sec_or_hack():
    guardian = MarketSentimentNewsGuardian()
    headlines = [
        "SEC launches formal investigation into SOL foundation operations",
        "Solana network processing high transaction volume",
    ]
    res = await guardian.analyze_symbol_sentiment("SOLUSDT", "LONG", headlines_override=headlines)
    assert res.verdict == SentimentVerdict.REJECTED_BLACK_SWAN
    assert res.confidence_delta == -100
    assert any("SEC" in r or "INVESTIGATION" in r for r in res.reasons)
    await guardian.close()


@pytest.mark.asyncio
async def test_bullish_catalyst_confidence_boost():
    guardian = MarketSentimentNewsGuardian()
    headlines = [
        "Ethereum layer 2 announces mainnet upgrade and major institutional partnership",
        "ETH daily active wallets reach all-time high",
    ]
    res = await guardian.analyze_symbol_sentiment("ETHUSDT", "LONG", headlines_override=headlines)
    assert res.verdict == SentimentVerdict.BOOSTED
    assert res.confidence_delta == 10
    assert res.score >= 75
    assert len(res.catalysts) > 0
    await guardian.close()


@pytest.mark.asyncio
async def test_bearish_catalyst_short_boost():
    guardian = MarketSentimentNewsGuardian()
    headlines = [
        "Massive whale deposit causes selloff fear across AVAX holders",
        "AVAX faces resistance at 10 dollar level",
    ]
    res = await guardian.analyze_symbol_sentiment("AVAXUSDT", "SHORT", headlines_override=headlines)
    assert res.verdict == SentimentVerdict.BOOSTED
    assert res.confidence_delta == 10
    assert res.score <= -75
    await guardian.close()


@pytest.mark.asyncio
async def test_contrarian_news_penalty():
    guardian = MarketSentimentNewsGuardian()
    # Good news while trying to SHORT
    headlines = [
        "BTC breaks resistance following major ETF approval and record institutional inflow",
    ]
    res = await guardian.analyze_symbol_sentiment("BTCUSDT", "SHORT", headlines_override=headlines)
    assert res.verdict == SentimentVerdict.REJECTED_CONTRARIAN
    assert res.confidence_delta == -15
    await guardian.close()


@pytest.mark.asyncio
async def test_neutral_news_pure_technical_approval():
    guardian = MarketSentimentNewsGuardian()
    headlines = [
        "Crypto market trades sideways in quiet weekend session",
        "Global stock futures tick slightly higher",
    ]
    res = await guardian.analyze_symbol_sentiment("NEARUSDT", "LONG", headlines_override=headlines)
    assert res.verdict == SentimentVerdict.APPROVED
    assert res.confidence_delta == 0
    await guardian.close()


@pytest.mark.asyncio
async def test_graceful_fallback_on_empty_or_error():
    guardian = MarketSentimentNewsGuardian()
    # No headlines available (e.g. offline)
    res = await guardian.analyze_symbol_sentiment("PEPEUSDT", "LONG", headlines_override=[])
    assert res.verdict == SentimentVerdict.APPROVED
    assert res.confidence_delta == 0
    await guardian.close()

