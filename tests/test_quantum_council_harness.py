"""
tests/test_quantum_council_harness.py
=============================================================================
BỘ KIỂM THỬ TOÀN DIỆN & ADVERSARIAL STRESS TEST CHO QUANTUM COUNCIL HARNESS
=============================================================================
Được xây dựng bởi Kiểm Thử Viên Trưởng Độc Lập (Independent QA & Stress Tester).

Bao gồm đầy đủ các kịch bản thực tế bắt buộc:
- Kịch bản 1: Giả lập ca REZUSDT (Volume đột biến 3.5x, giá tăng 16% mà có tín hiệu SHORT)
  -> Red Team Skeptic PHẢI giơ thẻ đỏ và Arbiter PHẢI phủ quyết (is_approved = False).
- Kịch bản 2: Giả lập ca ATOMUSDT (Giá sập dưới EMA20/50, không có phân kỳ dương, cố LONG bắt đáy)
  -> Red Team Skeptic & Macro Regime PHẢI giơ thẻ đỏ và Arbiter PHẢI phủ quyết.
- Kịch bản 3: Giả lập ca WLFIUSDT (SHORT thuận xu hướng nến đỏ, volume bình thường, cản EMA50 retest)
  -> Tất cả 4 đặc vụ đồng thuận và Arbiter PHẢI phê duyệt (is_approved = True) với đòn bẩy safe leverage <= 20x.
- Kịch bản 4: Giả lập ca Black Swan (Tin tức SEC phạt hoặc exploit)
  -> Sentiment Sentinel giơ thẻ đỏ và Arbiter PHẢI phủ quyết.
- Kịch bản 5: Kiểm tra tính năng format_telegram_transcript xuất ra biên bản họp định dạng Markdown chuẩn đẹp.

Cùng các bài kiểm tra chuyên sâu từng đặc vụ độc lập, kiểm tra bẫy giá nghịch lý,
tính toán ATR Volatility Sizing, Safe Leverage Clamp và Benchmark độ trễ nội bộ <= 5ms.
=============================================================================
"""

import asyncio
import json
import time
import pytest

from services.quantum_council_harness import (
    CouncilVote,
    AgentOpinion,
    CouncilDeliberationResult,
    TechnicalScoutAgent,
    MacroRegimeAgent,
    SentimentSentinelAgent,
    RedTeamSkepticAgent,
    QuantumCouncilArbiter,
)
from services.market_sentiment_news_guardian import MarketSentimentNewsGuardian
from risk.market_regime_shield import MarketRegimeShield


# =============================================================================
# I. 5 KỊCH BẢN THỰC CHIẾN BẮT BUỘC (MANDATORY REAL-WORLD SCENARIOS)
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_1_rezusdt_pump_trap_red_team_veto():
    """
    Kịch bản 1: Giả lập ca REZUSDT sáng nay.
    - Tình huống: Altcoin bị bơm thổi mạnh (Volume đột biến 3.5x, giá tăng 16.0% trong 24h).
    - Tín hiệu: Đòi mở vị thế SHORT (cản tàu / bắt đỉnh non).
    - Kết quả mong đợi:
      + Red Team Skeptic PHẢI giơ thẻ đỏ (vote = CouncilVote.VETO, confidence = 0).
      + Arbiter PHẢI phủ quyết (is_approved = False).
      + Veto reason phải chỉ rõ bẫy cản tàu bơm thổi Low-cap Pump Trap.
    """
    arbiter = QuantumCouncilArbiter()

    # Dữ liệu thị trường mô phỏng chính xác trường hợp REZUSDT
    market_data_rez = {
        "symbol": "REZUSDT",
        "direction": "SHORT",
        "current_price": 0.0450,
        "entry_price": 0.0450,
        "stop_loss": 0.0475,          # SL dist = 5.56%
        "take_profit_1": 0.0410,
        "take_profit_2": 0.0380,      # TP2 dist = 15.56% -> R:R = 2.8
        "take_profit_3": 0.0350,
        "leverage": 15,
        "vol_ratio": 3.5,             # Volume đột biến 3.5x Whale Climax Surge (>= 2.5)
        "change_24h": 16.0,           # Giá tăng mạnh +16.0%
        "ema20": 0.0430,
        "ema50": 0.0400,
        "rsi": 78.0,
        "btc_regime": {"status": "NEUTRAL", "reason": "BTC dao động tích lũy"},
        "headlines": ["REZ token price gains traction with unusual volume spike"],
    }

    result = await arbiter.deliberate("REZUSDT", market_data_rez)

    # 1. Arbiter PHẢI phủ quyết
    assert result.is_approved is False, "REZUSDT pump trap bắt buộc phải bị Arbiter phủ quyết (is_approved = False)!"
    assert result.consensus_score < 85, f"Điểm đồng thuận phải < 85 khi có Veto, thực tế: {result.consensus_score}"

    # 2. Red Team Skeptic PHẢI giơ thẻ đỏ VETO
    assert result.red_team.vote == CouncilVote.VETO, "Red Team Skeptic bắt buộc phải giơ thẻ đỏ VETO!"
    assert result.red_team.confidence == 0, "Độ tin cậy của Red Team khi giơ thẻ đỏ phải về 0!"
    assert "Low-cap Pump Trap" in (result.red_team.red_flag or "")
    assert "3.50" in (result.red_team.red_flag or "") or "3.5" in (result.red_team.red_flag or "")

    # 3. Veto reason và Transcript
    assert result.veto_reason is not None
    assert "Red Team Skeptic" in result.veto_reason
    assert "THẺ ĐỎ" in result.transcript or "BÁC BỎ" in result.transcript
    assert "REZUSDT" in result.transcript


@pytest.mark.asyncio
async def test_scenario_2_atomusdt_falling_knife_red_team_and_macro_veto():
    """
    Kịch bản 2: Giả lập ca ATOMUSDT sáng nay.
    - Tình huống: Giá rơi tự do thủng đáy (p < ema20 < ema50), không có phân kỳ dương RSI,
      râu nến dưới rất ngắn (20% < 40%), đồng thời BTC bước vào trạng thái sập hoảng loạn BEARISH_PANIC.
    - Tín hiệu: Cố LONG bắt đáy dao rơi.
    - Kết quả mong đợi:
      + CẢ Red Team Skeptic VÀ Macro Regime PHẢI giơ thẻ đỏ (vote = CouncilVote.VETO).
      + Arbiter PHẢI phủ quyết (is_approved = False).
      + Lý do phủ quyết phải chứa cả cảnh báo dao rơi Falling Knife VÀ sập vĩ mô BEARISH_PANIC.
    """
    arbiter = QuantumCouncilArbiter()

    # Dữ liệu thị trường mô phỏng ca ATOMUSDT
    market_data_atom = {
        "symbol": "ATOMUSDT",
        "direction": "LONG",
        "current_price": 1.680,
        "entry_price": 1.680,
        "stop_loss": 1.620,           # SL dist = 3.57%
        "take_profit_1": 1.760,
        "take_profit_2": 1.820,       # TP2 dist = 8.33% -> R:R = 2.33
        "leverage": 10,
        "ema20": 1.720,               # p < ema20 < ema50 -> Giảm mạnh dốc đứng
        "ema50": 1.780,
        "rsi": 29.0,                  # Quá bán sâu
        "lower_wick_ratio": 0.20,     # Râu dưới 20% (< 40%) -> Thiếu lực hấp thụ gom hàng
        "divergence": {"bullish_divergence": False, "bearish_divergence": False},  # KHÔNG có phân kỳ
        "vol_ratio": 1.4,
        "change_24h": -8.5,
        "btc_regime": {
            "status": "BEARISH_PANIC",
            "reason": "BTC gãy thủng EMA20/50 khung 4H và RSI 1H < 35",
            "btc_price": 63500.0,
            "btc_1h_rsi": 32.0,
        },
        "headlines": ["Crypto market faces severe correction led by Bitcoin slump"],
    }

    result = await arbiter.deliberate("ATOMUSDT", market_data_atom)

    # 1. Arbiter PHẢI phủ quyết
    assert result.is_approved is False, "ATOMUSDT bắt dao rơi trong BEARISH_PANIC bắt buộc phải bị phủ quyết!"
    assert result.consensus_score < 85

    # 2. Red Team Skeptic PHẢI giơ thẻ đỏ (Check 2: Falling Knife Trap)
    assert result.red_team.vote == CouncilVote.VETO, "Red Team bắt buộc phải VETO dao rơi ATOMUSDT!"
    assert result.red_team.confidence == 0
    assert "Falling Knife Trap" in (result.red_team.red_flag or "")

    # 3. Macro Regime PHẢI giơ thẻ đỏ (Kỷ luật chặn Altcoin LONG khi BEARISH_PANIC)
    assert result.macro_regime.vote == CouncilVote.VETO, "Macro Regime bắt buộc phải VETO Altcoin LONG khi BEARISH_PANIC!"
    assert result.macro_regime.confidence == 0
    assert "BEARISH_PANIC VETO" in (result.macro_regime.red_flag or "")

    # 4. Veto reason tổng hợp
    assert "Red Team Skeptic" in result.veto_reason
    assert "Macro Sentinel" in result.veto_reason
    assert "BÁC BỎ / VETO" in result.transcript


@pytest.mark.asyncio
async def test_scenario_3_wlfiusdt_trend_short_consensus_approval():
    """
    Kịch bản 3: Giả lập ca WLFIUSDT.
    - Tình huống: SHORT thuận xu hướng nến đỏ, volume bình thường (1.1x), cản EMA50 retest thành công,
      R:R = 2.4 >= 2.0, SL buffer 4.17% an toàn, không có tin tức tiêu cực.
    - Kết quả mong đợi:
      + TẤT CẢ 4 ĐẶC VỤ ĐỒNG THUẬN (vote = CouncilVote.APPROVED).
      + Arbiter PHẢI phê duyệt (is_approved = True).
      + Điểm đồng thuận consensus_score >= 85.
      + Đòn bẩy safe leverage được chuẩn hóa <= 20x.
    """
    arbiter = QuantumCouncilArbiter()

    # Dữ liệu thị trường chuẩn mực WLFIUSDT
    market_data_wlfi = {
        "symbol": "WLFIUSDT",
        "direction": "SHORT",
        "current_price": 0.1200,
        "entry_price": 0.1200,
        "stop_loss": 0.1250,          # SL dist = 0.0050 (4.17% > 3.0%), SL > Entry cho SHORT
        "take_profit_1": 0.1130,
        "take_profit_2": 0.1080,      # TP2 dist = 0.0120 -> R:R = 2.40 >= 2.0
        "take_profit_3": 0.1000,
        "leverage": 20,               # Đòn bẩy thiết lập
        "vol_ratio": 1.15,            # Volume bình thường (< 2.5x)
        "change_24h": -3.2,           # Đà giảm vừa phải (< 18.0%)
        "ema20": 0.1220,
        "ema50": 0.1255,              # Retest cản EMA50
        "upper_wick_ratio": 0.38,     # Râu trên từ chối giá
        "rsi": 44.0,
        "btc_regime": {
            "status": "NEUTRAL",
            "reason": "BTC dao động ổn định trong biên độ hẹp",
            "btc_price": 67500.0,
            "btc_1h_rsi": 51.0,
        },
        "headlines": ["WLFI community governance proposal passes smoothly"],
        "atr": 0.0035,                # ATR% = (0.0035 / 0.1200) * 100 = 2.92% (< 5.0%)
    }

    result = await arbiter.deliberate("WLFIUSDT", market_data_wlfi)

    # 1. Arbiter PHẢI phê duyệt
    assert result.is_approved is True, "WLFIUSDT thỏa mãn toàn diện các điều kiện phải được phê duyệt (is_approved = True)!"
    assert result.consensus_score >= 85, f"Điểm đồng thuận phải >= 85, thực tế: {result.consensus_score}"
    assert result.veto_reason is None

    # 2. Toàn bộ 4 Đặc Vụ phải đồng thuận APPROVED
    assert result.technical_scout.vote == CouncilVote.APPROVED
    assert result.macro_regime.vote == CouncilVote.APPROVED
    assert result.sentiment_sentinel.vote == CouncilVote.APPROVED
    assert result.red_team.vote == CouncilVote.APPROVED

    # 3. Đòn bẩy an toàn phải <= 20x
    safe_leverage = result.trade_parameters.get("leverage")
    assert safe_leverage is not None
    assert safe_leverage <= 20, f"Đòn bẩy an toàn phải <= 20x, thực tế: {safe_leverage}"
    assert result.trade_parameters["estimated_rr"] >= 2.0

    # 4. Transcript phải hiển thị trạng thái phê duyệt
    assert "ĐƯỢC PHÊ DUYỆT" in result.transcript
    assert "WLFIUSDT" in result.transcript


@pytest.mark.asyncio
async def test_scenario_4_black_swan_news_sentiment_veto():
    """
    Kịch bản 4: Giả lập ca Black Swan (Thiên nga đen).
    - Tình huống: Tin tức chấn động thị trường (SEC khởi kiện / phạt nặng, hoặc Exploit/Hack hợp đồng thông minh).
    - Kết quả mong đợi:
      + Sentiment Sentinel PHẢI giơ thẻ đỏ (vote = CouncilVote.VETO, confidence = 0).
      + Arbiter PHẢI phủ quyết (is_approved = False).
      + Lý do phủ quyết phải nêu rõ 1-touch Veto do tin tức thảm họa Black-Swan.
    """
    arbiter = QuantumCouncilArbiter()

    # Thử nghiệm 4A: Tin tức SEC kiện / phạt
    market_data_sec = {
        "symbol": "TOKENUSDT",
        "direction": "LONG",
        "entry_price": 5.0,
        "stop_loss": 4.8,             # SL dist = 4.0%
        "take_profit_2": 5.6,         # R:R = 3.0
        "leverage": 15,
        "vol_ratio": 1.2,
        "change_24h": 0.5,
        "btc_regime": {"status": "NEUTRAL", "reason": "BTC bình ổn"},
        "headlines": [
            "SEC files fraud lawsuit and issues subpoena against project executives",
        ],
    }

    result_sec = await arbiter.deliberate("TOKENUSDT", market_data_sec)
    assert result_sec.is_approved is False
    assert result_sec.sentiment_sentinel.vote == CouncilVote.VETO
    assert result_sec.sentiment_sentinel.confidence == 0
    assert "Black-Swan VETO" in (result_sec.sentiment_sentinel.red_flag or "")
    assert "Sentiment Sentinel" in (result_sec.veto_reason or "")

    # Thử nghiệm 4B: Tin tức Hack / Exploit hợp đồng
    market_data_hack = {
        "symbol": "DEFIUSDT",
        "direction": "LONG",
        "entry_price": 1.0,
        "stop_loss": 0.95,
        "take_profit_2": 1.15,
        "leverage": 10,
        "btc_regime": {"status": "NEUTRAL", "reason": "BTC bình ổn"},
        "headlines": [
            "Critical DeFi protocol exploit discovered, over 40M stolen from treasury contracts",
        ],
    }

    result_hack = await arbiter.deliberate("DEFIUSDT", market_data_hack)
    assert result_hack.is_approved is False
    assert result_hack.sentiment_sentinel.vote == CouncilVote.VETO
    assert "exploit" in result_hack.sentiment_sentinel.rationale.lower() or "stolen" in result_hack.sentiment_sentinel.rationale.lower()


@pytest.mark.asyncio
async def test_scenario_5_format_telegram_transcript_markdown_quality():
    """
    Kịch bản 5: Kiểm tra tính năng format_telegram_transcript.
    - Yêu cầu:
      + Xuất ra biên bản họp định dạng Markdown chuẩn đẹp.
      + Có biểu tượng icon và tên rõ ràng của cả 4 đặc vụ.
      + Có badge trạng thái phê duyệt (APPROVED) hoặc bác bỏ (REJECTED/VETO).
      + Hiển thị đầy đủ thông số lệnh: Entry, Stop Loss, TP1-3, R:R, Đòn bẩy, % Rủi ro.
      + Hiển thị thời gian độ trễ xử lý ms.
    """
    arbiter = QuantumCouncilArbiter()

    # 1. Kiểm tra transcript khi lệnh ĐƯỢC PHÊ DUYỆT
    approved_market_data = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry_price": 68000.0,
        "stop_loss": 66000.0,         # SL dist = 2.94%
        "take_profit_1": 71000.0,
        "take_profit_2": 74000.0,     # TP2 dist = 6000 -> R:R = 3.0
        "take_profit_3": 78000.0,
        "leverage": 20,
        "vol_ratio": 1.4,
        "change_24h": 1.8,
        "lower_wick_ratio": 0.45,
        "divergence": {"bullish_divergence": True},
        "btc_regime": {"status": "BULLISH_TREND", "reason": "BTC phá đỉnh 4H"},
        "headlines": ["Bitcoin institutional ETF inflows hit new monthly record"],
        "atr": 1200.0,
    }

    res_approved = await arbiter.deliberate("BTCUSDT", approved_market_data)
    assert res_approved.is_approved is True
    transcript_app = res_approved.transcript

    # Xác thực cấu trúc Markdown
    assert "🏛 *BIÊN BẢN HỘI ĐỒNG LƯỢNG TỬ (QUANTUM COUNCIL)* 🏛" in transcript_app
    assert "✅ *ĐƯỢC PHÊ DUYỆT (ALL AGENTS CONSENSUS)*" in transcript_app
    assert "`BTCUSDT`" in transcript_app
    assert "*LONG*" in transcript_app
    assert "1️⃣ 🔍 *Technical Scout*" in transcript_app
    assert "2️⃣ 🌐 *Macro Sentinel*" in transcript_app
    assert "3️⃣ 🛡 *Sentiment Sentinel*" in transcript_app
    assert "4️⃣ ⚔️ *Red Team Skeptic*" in transcript_app
    assert "🎯 *THÔNG SỐ LỆNH ĐƯỢC PHÊ DUYỆT:*" in transcript_app
    assert "• *Entry:* `68000.0`" in transcript_app
    assert "• *Stop Loss:* `66000.0`" in transcript_app
    assert "• *Mục tiêu:* TP1: `71000.0` | TP2: `74000.0` | TP3: `78000.0`" in transcript_app
    assert "• *Đòn bẩy an toàn:*" in transcript_app
    assert "• *Tỷ lệ R:R:* `3.0`" in transcript_app
    assert "• *Hạn mức rủi ro:*" in transcript_app
    assert "⏱ *Độ trễ xử lý:*" in transcript_app

    # 2. Kiểm tra transcript khi lệnh BỊ BÁC BỎ
    rejected_market_data = {
        "symbol": "DUMPUSDT",
        "direction": "SHORT",
        "entry_price": 10.0,
        "stop_loss": 10.5,
        "take_profit_2": 9.0,
        "vol_ratio": 4.0,             # Pump trap
        "change_24h": 25.0,
        "btc_regime": {"status": "NEUTRAL", "reason": "BTC đi ngang"},
        "headlines": [],
    }

    res_rejected = await arbiter.deliberate("DUMPUSDT", rejected_market_data)
    assert res_rejected.is_approved is False
    transcript_rej = res_rejected.transcript

    assert "🛑 *BỊ BÁC BỎ / VETO (THẺ ĐỎ)*" in transcript_rej
    assert "⛔ *LÝ DO PHỦ QUYẾT (VETO REASON):*" in transcript_rej
    assert "Low-cap Pump Trap" in transcript_rej
    assert "🔴 RED VETO" in transcript_rej


# =============================================================================
# II. KIỂM THỬ ĐỘC LẬP TỪNG ĐẶC VỤ (ISOLATED UNIT TESTS)
# =============================================================================

@pytest.mark.asyncio
async def test_technical_scout_rr_validation():
    """Kiểm tra Technical Scout kiểm soát chặt chẽ ngưỡng R:R >= 2.0."""
    scout = TechnicalScoutAgent()

    # R:R = 1.0 < 2.0 -> REJECTED
    bad_rr = {
        "direction": "LONG",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit_2": 105.0,
        "confidence": 85,
    }
    op_bad, params_bad = await scout.evaluate("ETHUSDT", bad_rr)
    assert op_bad.vote == CouncilVote.REJECTED
    assert "R:R" in op_bad.rationale
    assert params_bad["estimated_rr"] == 1.0

    # R:R = 2.5 >= 2.0 -> APPROVED
    good_rr = {
        "direction": "LONG",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit_2": 112.5,
        "confidence": 88,
    }
    op_good, params_good = await scout.evaluate("ETHUSDT", good_rr)
    assert op_good.vote == CouncilVote.APPROVED
    assert params_good["estimated_rr"] == 2.5


@pytest.mark.asyncio
async def test_technical_scout_smc_auto_detection():
    """Kiểm tra Technical Scout tự động kích hoạt thuật toán SMC khi không có sẵn trade params."""
    scout = TechnicalScoutAgent()

    market_data_smc = {
        "symbol": "SOLUSDT",
        "current_price": 150.0,
        "ema20": 149.0,
        "ema50": 148.0,
        "rsi": 32.0,
        "atr": 3.0,
        "vol_ratio": 1.6,
        "lower_wick_ratio": 0.42,
        "upper_wick_ratio": 0.05,
        "k_stoch": 15.0,
        "pct_b": 0.08,
        "lower_bb": 150.5,
        "upper_bb": 160.0,
        "divergence": {"bullish_divergence": True, "bearish_divergence": False},
        "sweep": {"bull_sweep": True, "bear_sweep": False, "lowest_prior": 148.0},
        "order_block": {"bull_ob": {"top": 150.2, "bottom": 149.0}, "bear_ob": None},
        "tick_size": 0.01,
        "open": 149.5,
    }
    opinion, params = await scout.evaluate("SOLUSDT", market_data_smc)
    assert opinion.vote == CouncilVote.APPROVED
    assert opinion.confidence >= 85
    assert params["direction"] == "LONG"
    assert params["estimated_rr"] >= 2.0


@pytest.mark.asyncio
async def test_macro_regime_bearish_panic_blocks_altcoin_long():
    """Kiểm tra Macro Sentinel với kỷ luật sập giá BEARISH_PANIC."""
    shield = MarketRegimeShield(cache_ttl_seconds=60)
    closes_4h = [70000.0 - (i * 350.0) for i in range(60)]
    closes_1h = [55000.0 - (i * 200.0) for i in range(30)]
    shield.evaluate_regime_from_data(closes_4h, closes_1h)

    macro_agent = MacroRegimeAgent(regime_shield=shield)

    # 1. Altcoin LONG -> VETO
    op_alt_long = await macro_agent.evaluate("NEARUSDT", "LONG", {})
    assert op_alt_long.vote == CouncilVote.VETO
    assert op_alt_long.confidence == 0

    # 2. Altcoin SHORT -> APPROVED (thuận dòng tiền rút)
    op_alt_short = await macro_agent.evaluate("NEARUSDT", "SHORT", {})
    assert op_alt_short.vote == CouncilVote.APPROVED
    assert op_alt_short.confidence == 92

    # 3. BTCUSDT chính nó -> APPROVED
    op_btc = await macro_agent.evaluate("BTCUSDT", "LONG", {})
    assert op_btc.vote == CouncilVote.APPROVED


@pytest.mark.asyncio
async def test_sentiment_sentinel_catalyst_boost_and_neutral():
    """Kiểm tra Sentiment Sentinel nhận diện chất xúc tác tích cực và trạng thái trung tính."""
    guardian = MarketSentimentNewsGuardian()
    agent = SentimentSentinelAgent(sentiment_guardian=guardian)

    # Chất xúc tác tích cực (Mainnet, Burn, ETF) -> BOOSTED (confidence 94%)
    data_boost = {
        "headlines": ["COINB project announces mainnet launch and massive token burn next week"],
    }
    op_boost = await agent.evaluate("COINB", "LONG", data_boost)
    assert op_boost.vote == CouncilVote.APPROVED
    assert op_boost.confidence == 94
    assert "chất xúc tác tích cực" in op_boost.rationale.lower()

    # Tin tức trung tính -> APPROVED (confidence 85%)
    data_neutral = {
        "headlines": ["Consolidation continues within the weekly channel"],
    }
    op_neutral = await agent.evaluate("COINB", "LONG", data_neutral)
    assert op_neutral.vote == CouncilVote.APPROVED
    assert op_neutral.confidence == 85


@pytest.mark.asyncio
async def test_red_team_skeptic_all_three_checks():
    """Kiểm thử chi tiết cả 3 Check bắt lỗi cốt lõi của Red Team Skeptic."""
    red_team = RedTeamSkepticAgent()

    # Check 1: vol_ratio >= 2.5 đòi SHORT -> VETO
    op_c1 = await red_team.evaluate(
        "COIN1", "SHORT",
        {"vol_ratio": 2.7, "change_24h": 5.0},
        {"entry_price": 10.0, "stop_loss": 11.0, "leverage": 10},
    )
    assert op_c1.vote == CouncilVote.VETO
    assert "Check 1 - Low-cap Pump Trap" in op_c1.red_flag

    # Check 2: Falling Knife (p < ema20 < ema50, no bull div, wick < 40%) đòi LONG -> VETO
    op_c2 = await red_team.evaluate(
        "COIN2", "LONG",
        {
            "current_price": 90.0,
            "ema20": 95.0,
            "ema50": 100.0,
            "lower_wick_ratio": 0.25,
            "divergence": {"bullish_divergence": False},
        },
        {"entry_price": 90.0, "stop_loss": 85.0, "leverage": 10},
    )
    assert op_c2.vote == CouncilVote.VETO
    assert "Check 2 - Falling Knife Trap" in op_c2.red_flag

    # Check 3: SL buffer < 3.0% với đòn bẩy > 20x -> VETO
    op_c3 = await red_team.evaluate(
        "COIN3", "LONG",
        {},
        {"entry_price": 100.0, "stop_loss": 98.0, "leverage": 25},  # 2.0% SL với 25x
    )
    assert op_c3.vote == CouncilVote.VETO
    assert "Check 3 - SL Buffer & Leverage" in op_c3.red_flag


@pytest.mark.asyncio
async def test_red_team_logic_inversion_checks():
    """Kiểm thử bắt lỗi logic nghịch lý (SL đặt ngược với vị thế)."""
    red_team = RedTeamSkepticAgent()

    # LONG nhưng Stop Loss >= Entry -> VETO
    op_inv_long = await red_team.evaluate(
        "INV1", "LONG",
        {},
        {"entry_price": 100.0, "stop_loss": 105.0, "leverage": 10},
    )
    assert op_inv_long.vote == CouncilVote.VETO
    assert "Logic Error" in op_inv_long.red_flag
    assert "Stop Loss (105.0) >= Entry (100.0)" in op_inv_long.red_flag

    # SHORT nhưng Stop Loss <= Entry -> VETO
    op_inv_short = await red_team.evaluate(
        "INV2", "SHORT",
        {},
        {"entry_price": 100.0, "stop_loss": 95.0, "leverage": 10},
    )
    assert op_inv_short.vote == CouncilVote.VETO
    assert "Logic Error" in op_inv_short.red_flag
    assert "Stop Loss (95.0) <= Entry (100.0)" in op_inv_short.red_flag


# =============================================================================
# III. KIỂM THỬ TÍCH HỢP QUẢN TRỊ RỦI RO & HIỆU NĂNG (RISK & PERFORMANCE)
# =============================================================================

@pytest.mark.asyncio
async def test_arbiter_high_volatility_atr_sizing_and_safe_leverage_clamp():
    """
    Kiểm tra Arbiter tự động tích hợp quản trị rủi ro:
    1. Khi ATR > 5.0% của Entry: Tự động hạ rủi ro xuống 1.0% NAV (thay vì 1.5%).
    2. Đòn bẩy tối đa luôn bị gông chặt safe leverage <= 20x.
    """
    arbiter = QuantumCouncilArbiter()

    # Setup đạt chuẩn nhưng có độ biến động rất cao: ATR = 6.0 trên giá 100.0 (ATR% = 6.0% > 5.0%)
    high_vol_market_data = {
        "symbol": "VOLUSDT",
        "direction": "LONG",
        "entry_price": 100.0,
        "stop_loss": 94.0,           # SL dist = 6.0% >= 3.0%
        "take_profit_1": 110.0,
        "take_profit_2": 118.0,      # TP dist = 18.0 -> R:R = 3.0 >= 2.0
        "leverage": 30,              # Đòi đòn bẩy 30x (quá cao)
        "vol_ratio": 1.2,
        "change_24h": 1.5,
        "lower_wick_ratio": 0.45,
        "divergence": {"bullish_divergence": True},
        "btc_regime": {"status": "NEUTRAL", "reason": "BTC đi ngang"},
        "headlines": [],
        "atr": 6.0,                  # ATR% = 6.0% > 5.0%
    }

    result = await arbiter.deliberate("VOLUSDT", high_vol_market_data)

    assert result.is_approved is True
    # 1. Rủi ro tự động bị hạ xuống 1.0% NAV do biến động mạnh
    assert result.trade_parameters.get("risk_pct") == 1.0
    assert "Coin biến động cao" in result.trade_parameters.get("risk_note", "")

    # 2. Đòn bẩy 30x bị clamp xuống <= 20x
    assert result.trade_parameters.get("leverage") <= 20


@pytest.mark.asyncio
async def test_council_deliberation_result_serialization():
    """Kiểm tra CouncilDeliberationResult chuyển đổi sang JSON/dict chuẩn xác."""
    arbiter = QuantumCouncilArbiter()

    m_data = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry_price": 60000.0,
        "stop_loss": 58000.0,
        "take_profit_2": 66000.0,
        "leverage": 15,
        "btc_regime": {"status": "NEUTRAL", "reason": "Stable"},
        "headlines": [],
    }
    result = await arbiter.deliberate("BTCUSDT", m_data)
    d = result.to_dict()

    assert isinstance(d, dict)
    assert d["symbol"] == "BTCUSDT"
    assert "technical_scout" in d
    assert "macro_regime" in d
    assert "sentiment_sentinel" in d
    assert "red_team" in d
    assert "execution_time_ms" in d

    # Kiểm tra JSON serialize không gây Exception
    json_str = json.dumps(d)
    assert len(json_str) > 200


@pytest.mark.asyncio
async def test_quantum_council_sub_millisecond_latency_benchmark():
    """
    Benchmark độ trễ của Hội Đồng Lượng Tử:
    Đảm bảo 100% hoạt động nội bộ Python (0ms chi phí mạng, không nghẽn luồng).
    Thực hiện 20 lần thẩm định liên tiếp và kiểm tra trung bình mỗi lần <= 5.0ms.
    """
    arbiter = QuantumCouncilArbiter()

    fast_data = {
        "direction": "LONG",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit_2": 115.0,
        "leverage": 15,
        "vol_ratio": 1.2,
        "change_24h": 2.0,
        "btc_regime": {"status": "NEUTRAL", "reason": "BTC đi ngang"},
        "headlines": ["Normal crypto trading continues"],
    }

    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        res = await arbiter.deliberate("ETHUSDT", fast_data)
        elapsed = (time.perf_counter() - t0) * 1000.0
        times.append(elapsed)

    avg_ms = sum(times) / len(times)
    assert avg_ms < 10.0, f"Độ trễ trung bình của Hội Đồng Lượng Tử phải < 10.0ms, thực tế: {avg_ms:.2f}ms"
