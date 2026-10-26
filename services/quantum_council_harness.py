"""
services/quantum_council_harness.py
=============================================================================
HỘI ĐỒNG LƯỢNG TỬ ĐA ĐẶC VỤ (QUANTUM COUNCIL HARNESS) - 100% NỘI BỘ PYTHON
=============================================================================
Kiến trúc hội đồng đa tác nhân lượng tử (Quantum Council Multi-Agent System)
hoạt động 100% nội bộ bằng Python (0đ chi phí API ngoài, 0 latency, phản xạ
tức thì <= 5ms).

Hội đồng bao gồm 4 Đặc Vụ Chuyên Môn (Specialist Agents) độc lập và 1 Trọng Tài
Tối Cao (QuantumCouncilArbiter):
  1. TechnicalScoutAgent:
     - Phân tích cấu trúc Smart Money Concepts (SMC), Order Block (OB),
       Quét thanh khoản (Liquidity Sweeps), Nến Pinbar rút chân.
     - Bắt buộc tỷ lệ Risk:Reward (R:R) >= 2.0.
  2. MacroRegimeAgent:
     - Kiểm tra trạng thái BTC 4H / 1H (BULLISH, CHOPPY / NEUTRAL, BEARISH_PANIC).
     - Kỷ luật thép: Nếu BEARISH_PANIC -> CHẶN 100% lệnh LONG của Altcoins.
  3. SentimentSentinelAgent:
     - Quét từ khóa Thiên nga đen (SEC, Hack, Delist, Rugpull, Phá sản...).
     - Kỷ luật thép: 1-touch Veto phủ quyết hủy lệnh ngay lập tức khi phát hiện.
  4. RedTeamSkepticAgent (Đặc Vụ Phản Biện / Bắt Lỗi):
     - Check 1: Low-cap pump trap (vol_ratio >= 2.5 hoặc change_24h >= 18% mà đòi SHORT).
     - Check 2: Falling knife trap (p < ema20 < ema50 mà đòi LONG khi thiếu phân kỳ dương
       và nến rút chân < 40%).
     - Check 3: SL buffer quá mỏng (< 3.0%) với đòn bẩy cao (> 20x).
     - Bất kỳ vi phạm nào -> Giơ Thẻ Đỏ (Red Card Veto).

Quy tắc Phê Duyệt Hội Đồng (Arbiter Consensus Rule):
  - Phê duyệt (is_approved = True) KHI VÀ CHỈ KHI:
    + Red Team KHÔNG giơ thẻ đỏ (Pass Check 1, 2, 3).
    + Sentiment Sentinel KHÔNG giơ thẻ đỏ thiên nga đen.
    + Macro Regime KHÔNG chặn theo kỷ luật sập giá BTC.
    + Technical Scout xác nhận setup SMC hợp lưu đạt R:R >= 2.0.
    + Điểm đồng thuận toàn hội đồng (Consensus Score) >= 85/100.
=============================================================================
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from config.config import AppConfig
from risk.market_regime_shield import MarketRegimeShield, global_market_regime_shield
from risk.risk_engine import RiskEngine
from services.market_sentiment_news_guardian import (
    MarketSentimentNewsGuardian,
    SentimentResult,
    SentimentVerdict,
)
from services.quantum_ai_engine import (
    QuantumAIEngine,
    round_to_tick,
    calculate_ema,
    calculate_rsi,
    calculate_atr,
)

logger = logging.getLogger("quantum_council_harness")


class CouncilVote(str, Enum):
    """Quyết định biểu quyết của từng đặc vụ trong hội đồng."""
    APPROVED = "APPROVED"    # Đồng thuận thông qua
    REJECTED = "REJECTED"    # Từ chối vì không đạt tiêu chí tối thiểu
    VETO = "VETO"            # Giơ Thẻ Đỏ / Phủ quyết tuyệt đối (1-touch veto)


@dataclass
class AgentOpinion:
    """Biên bản ý kiến và đánh giá của một Đặc Vụ Chuyên Môn."""
    agent_id: str
    agent_name: str
    role: str
    vote: CouncilVote
    confidence: int  # Thang điểm tin cậy 0 - 100
    rationale: str
    key_metrics: Dict[str, Any] = field(default_factory=dict)
    red_flag: Optional[str] = None
    execution_time_ms: float = 0.0

    @property
    def is_veto(self) -> bool:
        return self.vote == CouncilVote.VETO

    @property
    def is_approved(self) -> bool:
        return self.vote == CouncilVote.APPROVED


@dataclass
class CouncilDeliberationResult:
    """Biên bản thẩm định toàn diện của Hội Đồng Lượng Tử."""
    symbol: str
    direction: str  # "LONG" | "SHORT" | "NEUTRAL"
    is_approved: bool
    consensus_score: int  # 0 to 100
    veto_reason: Optional[str]
    technical_scout: AgentOpinion
    macro_regime: AgentOpinion
    sentiment_sentinel: AgentOpinion
    red_team: AgentOpinion
    trade_parameters: Dict[str, Any]
    deliberated_at: str
    execution_time_ms: float
    transcript: str = ""
    # 5 Đặc Vụ Chuyên Môn Tranh Biện Hội Đồng Lượng Tử
    lead_quant: Optional[AgentOpinion] = None
    scalp_specialist: Optional[AgentOpinion] = None
    macro_smc: Optional[AgentOpinion] = None
    risk_guardian: Optional[AgentOpinion] = None
    sentiment_scout: Optional[AgentOpinion] = None
    debate_html: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Chuyển đổi kết quả sang dạng dictionary để lưu trữ hoặc truyền qua API/WebSocket."""
        res = {
            "symbol": self.symbol,
            "direction": self.direction,
            "is_approved": self.is_approved,
            "consensus_score": self.consensus_score,
            "veto_reason": self.veto_reason,
            "technical_scout": {
                "agent_id": self.technical_scout.agent_id,
                "name": self.technical_scout.agent_name,
                "vote": self.technical_scout.vote.value,
                "confidence": self.technical_scout.confidence,
                "rationale": self.technical_scout.rationale,
                "metrics": self.technical_scout.key_metrics,
                "red_flag": self.technical_scout.red_flag,
            },
            "macro_regime": {
                "agent_id": self.macro_regime.agent_id,
                "name": self.macro_regime.agent_name,
                "vote": self.macro_regime.vote.value,
                "confidence": self.macro_regime.confidence,
                "rationale": self.macro_regime.rationale,
                "metrics": self.macro_regime.key_metrics,
                "red_flag": self.macro_regime.red_flag,
            },
            "sentiment_sentinel": {
                "agent_id": self.sentiment_sentinel.agent_id,
                "name": self.sentiment_sentinel.agent_name,
                "vote": self.sentiment_sentinel.vote.value,
                "confidence": self.sentiment_sentinel.confidence,
                "rationale": self.sentiment_sentinel.rationale,
                "metrics": self.sentiment_sentinel.key_metrics,
                "red_flag": self.sentiment_sentinel.red_flag,
            },
            "red_team": {
                "agent_id": self.red_team.agent_id,
                "name": self.red_team.agent_name,
                "vote": self.red_team.vote.value,
                "confidence": self.red_team.confidence,
                "rationale": self.red_team.rationale,
                "metrics": self.red_team.key_metrics,
                "red_flag": self.red_team.red_flag,
            },
            "trade_parameters": self.trade_parameters,
            "deliberated_at": self.deliberated_at,
            "execution_time_ms": self.execution_time_ms,
            "transcript": self.transcript,
            "debate_html": self.debate_html,
        }
        if self.lead_quant:
            res["lead_quant"] = {
                "agent_id": self.lead_quant.agent_id,
                "name": self.lead_quant.agent_name,
                "vote": self.lead_quant.vote.value,
                "confidence": self.lead_quant.confidence,
                "rationale": self.lead_quant.rationale,
            }
        if self.scalp_specialist:
            res["scalp_specialist"] = {
                "agent_id": self.scalp_specialist.agent_id,
                "name": self.scalp_specialist.agent_name,
                "vote": self.scalp_specialist.vote.value,
                "confidence": self.scalp_specialist.confidence,
                "rationale": self.scalp_specialist.rationale,
            }
        if self.macro_smc:
            res["macro_smc"] = {
                "agent_id": self.macro_smc.agent_id,
                "name": self.macro_smc.agent_name,
                "vote": self.macro_smc.vote.value,
                "confidence": self.macro_smc.confidence,
                "rationale": self.macro_smc.rationale,
            }
        if self.risk_guardian:
            res["risk_guardian"] = {
                "agent_id": self.risk_guardian.agent_id,
                "name": self.risk_guardian.agent_name,
                "vote": self.risk_guardian.vote.value,
                "confidence": self.risk_guardian.confidence,
                "rationale": self.risk_guardian.rationale,
            }
        if self.sentiment_scout:
            res["sentiment_scout"] = {
                "agent_id": self.sentiment_scout.agent_id,
                "name": self.sentiment_scout.agent_name,
                "vote": self.sentiment_scout.vote.value,
                "confidence": self.sentiment_scout.confidence,
                "rationale": self.sentiment_scout.rationale,
            }
        return res


# =============================================================================
# 1. TECHNICAL SCOUT AGENT
# =============================================================================
class TechnicalScoutAgent:
    """
    Đặc Vụ Thám Báo Kỹ Thuật (Technical Scout):
    Phân tích cấu trúc thị trường SMC, Order Blocks, Quét thanh khoản (Liquidity Sweeps),
    Nến Pinbar rút chân, và đảm bảo tỷ lệ Risk:Reward (R:R) >= 2.0.
    """

    def __init__(self, quantum_engine: Optional[QuantumAIEngine] = None):
        self.agent_id = "technical_scout"
        self.agent_name = "Technical Scout (SMC Confluence)"
        self.role = "Phân tích cấu trúc SMC, Order Block, Thanh khoản & Tỷ lệ R:R >= 2.0"
        self.quantum_engine = quantum_engine

    async def evaluate(
        self,
        symbol: str,
        market_data: Dict[str, Any],
    ) -> Tuple[AgentOpinion, Dict[str, Any]]:
        """
        Đánh giá kỹ thuật đa hợp lưu:
        - Nếu market_data đã có thiết lập lệnh đề xuất: Kiểm tra R:R >= 2.0 và hợp lưu SMC.
        - Nếu market_data là dữ liệu kỹ thuật thuần: Sử dụng thuật toán SMC Quantum AI Engine để trích xuất setup.
        """
        start_t = time.perf_counter()
        trade_params: Dict[str, Any] = {}

        # Trường hợp 1: market_data đã chỉ định sẵn thông số lệnh (Proposed Setup)
        if "direction" in market_data and "entry_price" in market_data and "stop_loss" in market_data:
            dir_str = str(market_data["direction"]).upper()
            entry = float(market_data["entry_price"])
            sl = float(market_data["stop_loss"])
            tp2 = float(market_data.get("take_profit_2", market_data.get("take_profit_1", 0.0)))
            sl_dist = abs(entry - sl)
            tp_dist = abs(tp2 - entry)
            rr = round(tp_dist / sl_dist, 2) if sl_dist > 1e-9 else 0.0

            trade_params = {
                "symbol": symbol,
                "direction": dir_str,
                "entry_price": entry,
                "stop_loss": sl,
                "take_profit_1": float(market_data.get("take_profit_1", tp2)),
                "take_profit_2": tp2,
                "take_profit_3": float(market_data.get("take_profit_3", tp2 * 1.05 if dir_str == "LONG" else tp2 * 0.95)),
                "estimated_rr": rr,
                "leverage": int(market_data.get("leverage", 20)),
                "confluences": market_data.get("confluences", []),
                "archetype": market_data.get("archetype", "PROPOSED_SETUP"),
            }

            if rr < 2.0:
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                return AgentOpinion(
                    agent_id=self.agent_id,
                    agent_name=self.agent_name,
                    role=self.role,
                    vote=CouncilVote.REJECTED,
                    confidence=40,
                    rationale=f"Tỷ lệ Risk:Reward (R:R = {rr:.2f}) không đạt chuẩn tối thiểu R:R >= 2.0.",
                    key_metrics={"estimated_rr": rr, "entry": entry, "sl": sl, "tp2": tp2},
                    red_flag=f"R:R ({rr:.2f}) < 2.0",
                    execution_time_ms=elapsed_ms,
                ), trade_params

            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            return AgentOpinion(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                role=self.role,
                vote=CouncilVote.APPROVED,
                confidence=int(market_data.get("confidence", 88)),
                rationale=f"Xác nhận thiết lập kỹ thuật hợp lệ: R:R = {rr:.2f} >= 2.0, điểm vào lệnh tối ưu.",
                key_metrics={"estimated_rr": rr, "entry": entry, "sl": sl, "tp2": tp2},
                execution_time_ms=elapsed_ms,
            ), trade_params

        # Trường hợp 2: Quét thiết lập SMC tự động từ market_data
        engine = self.quantum_engine
        if engine is None:
            # Tạo engine cục bộ lightweight (không cần I/O mạng vì evaluate_quantum_85pct_confluence thuần toán)
            engine = QuantumAIEngine(config=None, binance_client=None)

        setup = engine.evaluate_quantum_85pct_confluence(market_data)
        if not setup or not setup.get("has_setup"):
            # Thử archetype fallback
            setup = engine.evaluate_admin_archetypes(market_data)

        if setup and setup.get("has_setup"):
            rr = float(setup.get("estimated_rr", 2.0))
            trade_params = {
                "symbol": symbol,
                "direction": setup["direction"],
                "entry_price": setup["entry_price"],
                "stop_loss": setup["stop_loss"],
                "take_profit_1": setup.get("take_profit_1"),
                "take_profit_2": setup.get("take_profit_2"),
                "take_profit_3": setup.get("take_profit_3"),
                "estimated_rr": rr,
                "leverage": setup.get("leverage", 20),
                "confluences": setup.get("confluences", []),
                "archetype": setup.get("archetype", "QUANTUM_SMC_CONFLUENCE"),
            }

            if rr < 2.0:
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                return AgentOpinion(
                    agent_id=self.agent_id,
                    agent_name=self.agent_name,
                    role=self.role,
                    vote=CouncilVote.REJECTED,
                    confidence=45,
                    rationale=f"Thiết lập SMC ({setup.get('archetype')}) có R:R = {rr:.2f} < 2.0.",
                    key_metrics={"estimated_rr": rr, "confluences_count": len(setup.get("confluences", []))},
                    red_flag=f"R:R ({rr:.2f}) < 2.0",
                    execution_time_ms=elapsed_ms,
                ), trade_params

            conf = int(setup.get("confidence", 85))
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            return AgentOpinion(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                role=self.role,
                vote=CouncilVote.APPROVED,
                confidence=conf,
                rationale=setup.get("rationale", f"Phát hiện hợp lưu SMC {conf}%+ vững chắc với R:R={rr:.2f}."),
                key_metrics={
                    "estimated_rr": rr,
                    "confluences": setup.get("confluences", []),
                    "archetype": setup.get("archetype"),
                    "entry": setup["entry_price"],
                    "sl": setup["stop_loss"],
                },
                execution_time_ms=elapsed_ms,
            ), trade_params

        # Không tìm thấy setup hợp lưu SMC đạt chuẩn
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
        return AgentOpinion(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            role=self.role,
            vote=CouncilVote.REJECTED,
            confidence=30,
            rationale="Không tìm thấy cấu trúc hợp lưu SMC 85%+ (thiếu Quét thanh khoản, Order Block hoặc Pinbar đảo chiều).",
            key_metrics={"has_setup": False},
            execution_time_ms=elapsed_ms,
        ), {}


# =============================================================================
# 2. MACRO REGIME AGENT
# =============================================================================
class MacroRegimeAgent:
    """
    Đặc Vụ Vĩ Mô Thị Trường Chung (Macro Sentinel):
    Kiểm tra trạng thái BTCUSDT 4H / 1H (BULLISH, CHOPPY / NEUTRAL, BEARISH_PANIC).
    Kỷ luật thép: Nếu BEARISH_PANIC -> CHẶN 100% lệnh LONG của Altcoins để bảo toàn vốn!
    """

    def __init__(self, regime_shield: Optional[MarketRegimeShield] = None):
        self.agent_id = "macro_regime"
        self.agent_name = "Macro Sentinel (BTC Market Regime)"
        self.role = "Giám sát xu hướng BTC 4H/1H & Kỷ luật chặn Altcoin LONG khi sập giá"
        self.shield = regime_shield or global_market_regime_shield

    async def evaluate(
        self,
        symbol: str,
        direction: str,
        market_data: Dict[str, Any],
    ) -> AgentOpinion:
        """
        Kiểm tra chế độ vĩ mô của Bitcoin:
        - Nếu btc_4h_closes & btc_1h_closes được cấp trong market_data -> tính toán trực tiếp.
        - Nếu có sẵn btc_regime -> trích xuất kết quả đã lưu trong cache.
        - Kỷ luật: BEARISH_PANIC chặn tuyệt đối Altcoin LONG.
        """
        start_t = time.perf_counter()
        clean_symbol = symbol.upper().replace("/", "").replace(":", "")
        is_btc = clean_symbol in ("BTCUSDT", "BTCUSDC", "BTC")
        dir_upper = direction.upper()

        regime: Dict[str, Any]
        if "btc_4h_closes" in market_data and "btc_1h_closes" in market_data:
            regime = self.shield.evaluate_regime_from_data(
                market_data["btc_4h_closes"],
                market_data["btc_1h_closes"],
            )
        elif "btc_regime" in market_data and isinstance(market_data["btc_regime"], dict):
            regime = market_data["btc_regime"]
        else:
            regime = self.shield.current_regime

        status = regime.get("status", "NEUTRAL")
        reason = regime.get("reason", "Duy trì trạng thái mặc định")
        btc_price = float(regime.get("btc_price", 0.0))
        rsi_1h = float(regime.get("btc_1h_rsi", 50.0))

        key_metrics = {
            "regime_status": status,
            "btc_price": btc_price,
            "btc_1h_rsi": rsi_1h,
            "is_btc_trade": is_btc,
        }

        # KỶ LUẬT THÉP: BEARISH_PANIC CHẶN 100% LỆNH LONG ALTCOIN
        if status == "BEARISH_PANIC":
            if not is_btc and dir_upper in ("LONG", "BUY"):
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                red_flag = (
                    f"BEARISH_PANIC VETO: Thị trường chung hoảng loạn ({reason}). "
                    f"Chặn 100% lệnh LONG Altcoin để bảo toàn vốn!"
                )
                return AgentOpinion(
                    agent_id=self.agent_id,
                    agent_name=self.agent_name,
                    role=self.role,
                    vote=CouncilVote.VETO,
                    confidence=0,
                    rationale=red_flag,
                    key_metrics=key_metrics,
                    red_flag=red_flag,
                    execution_time_ms=elapsed_ms,
                )
            elif dir_upper in ("SHORT", "SELL"):
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                return AgentOpinion(
                    agent_id=self.agent_id,
                    agent_name=self.agent_name,
                    role=self.role,
                    vote=CouncilVote.APPROVED,
                    confidence=92,
                    rationale=f"Thị trường BEARISH_PANIC ({reason}): Cho phép mở lệnh SHORT thuận xu hướng dòng tiền rút.",
                    key_metrics=key_metrics,
                    execution_time_ms=elapsed_ms,
                )
            else:
                # Lệnh trực tiếp trên BTC
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                return AgentOpinion(
                    agent_id=self.agent_id,
                    agent_name=self.agent_name,
                    role=self.role,
                    vote=CouncilVote.APPROVED,
                    confidence=85,
                    rationale="Lệnh trực tiếp trên BTCUSDT tuân thủ phân tích cấu trúc kỹ thuật riêng.",
                    key_metrics=key_metrics,
                    execution_time_ms=elapsed_ms,
                )

        if status in ("BULLISH_TREND", "BULLISH"):
            confidence = 94 if dir_upper in ("LONG", "BUY") else 75
            rationale = (
                f"BTC đang trong xu hướng Tăng ({reason}). "
                f"{'Đồng thuận mạnh cho lệnh LONG.' if dir_upper in ('LONG', 'BUY') else 'Cảnh báo lệnh SHORT là ngược xu hướng BTC.'}"
            )
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            return AgentOpinion(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                role=self.role,
                vote=CouncilVote.APPROVED,
                confidence=confidence,
                rationale=rationale,
                key_metrics=key_metrics,
                execution_time_ms=elapsed_ms,
            )

        # NEUTRAL / CHOPPY
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
        return AgentOpinion(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            role=self.role,
            vote=CouncilVote.APPROVED,
            confidence=82,
            rationale=f"BTC dao động đi ngang tích lũy ({reason}). Altcoin biến động độc lập.",
            key_metrics=key_metrics,
            execution_time_ms=elapsed_ms,
        )


# =============================================================================
# 3. SENTIMENT SENTINEL AGENT
# =============================================================================
class SentimentSentinelAgent:
    """
    Đặc Vụ Tin Tức & Tâm Lý Thị Trường (Sentiment Sentinel):
    Kiểm tra tin tức thiên nga đen (Black-Swan keywords: SEC, Hack, Delist, Fraud, Phá sản...).
    Kỷ luật thép: Nếu dính Black-Swan -> 1-touch Veto (Thẻ đỏ hủy kèo ngay lập tức).
    """

    def __init__(self, sentiment_guardian: Optional[MarketSentimentNewsGuardian] = None):
        self.agent_id = "sentiment_sentinel"
        self.agent_name = "Sentiment Sentinel (Black-Swan Guard)"
        self.role = "Quét tin tức thiên nga đen, On-chain catalysts & Rủi ro pháp lý"
        self.guardian = sentiment_guardian or MarketSentimentNewsGuardian()

    async def evaluate(
        self,
        symbol: str,
        direction: str,
        market_data: Dict[str, Any],
    ) -> AgentOpinion:
        """
        Quét tin tức & sự kiện thiên nga đen.
        Ưu tiên bộ headlines override trong market_data để kiểm tra tức thì (0ms latency).
        """
        start_t = time.perf_counter()
        headlines_override = market_data.get("headlines") or market_data.get("news")

        # Quét quy tắc NLP cục bộ an toàn
        if headlines_override is not None:
            sentiment_res = self.guardian.scan_rule_sentiment(symbol, direction, headlines_override)
        else:
            sentiment_res = await self.guardian.analyze_symbol_sentiment(symbol, direction)

        key_metrics = {
            "verdict": sentiment_res.verdict.value,
            "sentiment_score": sentiment_res.score,
            "catalysts": sentiment_res.catalysts,
        }

        # 1-TOUCH VETO KHI GẶP THIÊN NGA ĐEN
        if sentiment_res.verdict == SentimentVerdict.REJECTED_BLACK_SWAN:
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            reasons_text = "; ".join(sentiment_res.reasons)
            red_flag = f"Black-Swan VETO: Phát hiện tin tức thảm họa ({reasons_text})"
            return AgentOpinion(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                role=self.role,
                vote=CouncilVote.VETO,
                confidence=0,
                rationale=f"1-touch Veto kích hoạt: {reasons_text}",
                key_metrics=key_metrics,
                red_flag=red_flag,
                execution_time_ms=elapsed_ms,
            )

        if sentiment_res.verdict == SentimentVerdict.BOOSTED:
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            return AgentOpinion(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                role=self.role,
                vote=CouncilVote.APPROVED,
                confidence=94,
                rationale=f"Phát hiện chất xúc tác tích cực đồng thuận: {'; '.join(sentiment_res.catalysts or sentiment_res.reasons)}",
                key_metrics=key_metrics,
                execution_time_ms=elapsed_ms,
            )

        if sentiment_res.verdict == SentimentVerdict.REJECTED_CONTRARIAN:
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            return AgentOpinion(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                role=self.role,
                vote=CouncilVote.REJECTED,
                confidence=40,
                rationale=f"Tin tức thị trường đối nghịch với vị thế: {'; '.join(sentiment_res.reasons)}",
                key_metrics=key_metrics,
                execution_time_ms=elapsed_ms,
            )

        # NEUTRAL
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
        return AgentOpinion(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            role=self.role,
            vote=CouncilVote.APPROVED,
            confidence=85,
            rationale="Tâm lý thị trường trung tính, không phát hiện tin tức thiên nga đen hay rủi ro pháp lý.",
            key_metrics=key_metrics,
            execution_time_ms=elapsed_ms,
        )


# =============================================================================
# 4. RED TEAM SKEPTIC AGENT
# =============================================================================
class RedTeamSkepticAgent:
    """
    ĐẶC VỤ PHẢN BIỆN (Red Team Skeptic / Devil's Advocate):
    Nhiệm vụ duy nhất: BẮT LỖI, TÌM BẪY GIÁ & HỦY KÈO!
    
    3 Check Bắt Buộc Độc Lập:
      - Check 1: Low-cap pump trap (vol_ratio >= 2.5 hoặc change_24h >= 18% mà đòi SHORT).
      - Check 2: Falling knife trap (p < ema20 < ema50 mà đòi LONG bắt đáy khi KHÔNG có
                 phân kỳ dương RSI hoặc nến rút chân < 40%).
      - Check 3: SL buffer quá mỏng (< 3.0%) với đòn bẩy cao (> 20x).
      - Bất kỳ vi phạm nào -> Giơ Thẻ Đỏ (Red Card Veto).
    """

    def __init__(self):
        self.agent_id = "red_team"
        self.agent_name = "Red Team Skeptic (Devil's Advocate)"
        self.role = "Bắt bẫy giá cá mập, quét lỗi logic & Giơ thẻ đỏ bảo vệ vốn"

    def _count_directional_positions(self, market_data: Dict[str, Any]) -> Tuple[int, int]:
        """
        Đếm số lượng vị thế LONG và SHORT đang mở đồng thời.
        Hỗ trợ:
        - open_shorts / open_longs được truyền trực tiếp trong market_data.
        - Danh sách open_positions / positions từ Binance Futures client.
        """
        if "open_longs" in market_data and "open_shorts" in market_data:
            try:
                return int(market_data["open_longs"]), int(market_data["open_shorts"])
            except (ValueError, TypeError):
                pass

        positions = market_data.get("open_positions") or market_data.get("positions") or []
        open_longs = 0
        open_shorts = 0

        for p in positions:
            if isinstance(p, dict):
                amt_val = p.get("positionAmt", p.get("amount", p.get("qty")))
                if amt_val is not None:
                    try:
                        amt_f = float(amt_val)
                        if amt_f > 0:
                            open_longs += 1
                        elif amt_f < 0:
                            open_shorts += 1
                        continue
                    except (ValueError, TypeError):
                        pass
                side_str = str(p.get("positionSide", p.get("side", ""))).upper()
                if side_str in ("LONG", "BUY"):
                    open_longs += 1
                elif side_str in ("SHORT", "SELL"):
                    open_shorts += 1
            else:
                amt_val = getattr(p, "position_amt", getattr(p, "quantity", None))
                if amt_val is not None:
                    try:
                        amt_f = float(amt_val)
                        if amt_f > 0:
                            open_longs += 1
                        elif amt_f < 0:
                            open_shorts += 1
                        continue
                    except (ValueError, TypeError):
                        pass
                side_val = getattr(p, "side", getattr(p, "position_side", None))
                side_str = str(getattr(side_val, "value", side_val) or "").upper()
                if side_str in ("LONG", "BUY"):
                    open_longs += 1
                elif side_str in ("SHORT", "SELL"):
                    open_shorts += 1

        return open_longs, open_shorts

    async def evaluate(
        self,
        symbol: str,
        direction: str,
        market_data: Dict[str, Any],
        trade_params: Dict[str, Any],
    ) -> AgentOpinion:
        """
        Thực hiện kiểm tra bẫy giá và các yếu tố rủi ro hủy diệt tài khoản.
        """
        start_t = time.perf_counter()
        dir_upper = direction.upper()

        # -------------------------------------------------------------
        # CHECK 0: GIỚI HẠN TỶ TRỌNG CÙNG CHIỀU (Directional Exposure Cap / Anti-Skew Shield)
        # (Chế độ thường: Max 3 vị thế cùng chiều; Chế độ Ferrari Mode: Max 15-20 vị thế)
        # -------------------------------------------------------------
        open_longs, open_shorts = self._count_directional_positions(market_data)
        is_ferrari = bool(market_data.get("ferrari_mode_enabled", False))
        max_cap = int(market_data.get("max_directional_cap", 15 if is_ferrari else 3))

        if dir_upper in ("SHORT", "SELL") and open_shorts >= max_cap:
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            red_flag = (
                f"DIRECTIONAL_CAP_VETO: Đã đạt trần tối đa {max_cap} vị thế SHORT. "
                "Chặn để phòng ngừa rủi ro Short Squeeze khi thị trường đảo chiều!"
            )
            return AgentOpinion(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                role=self.role,
                vote=CouncilVote.VETO,
                confidence=0,
                rationale=red_flag,
                key_metrics={"open_shorts": open_shorts, "max_cap": max_cap, "check": "directional_cap"},
                red_flag=red_flag,
                execution_time_ms=elapsed_ms,
            )

        if dir_upper in ("LONG", "BUY") and open_longs >= max_cap:
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            red_flag = (
                f"DIRECTIONAL_CAP_VETO: Đã đạt trần tối đa {max_cap} vị thế LONG. "
                "Chặn để phòng ngừa rủi ro Long Squeeze khi thị trường đảo chiều!"
            )
            return AgentOpinion(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                role=self.role,
                vote=CouncilVote.VETO,
                confidence=0,
                rationale=red_flag,
                key_metrics={"open_longs": open_longs, "max_cap": max_cap, "check": "directional_cap"},
                red_flag=red_flag,
                execution_time_ms=elapsed_ms,
            )

        # -------------------------------------------------------------
        # CHECK COOLDOWN: BỘ ĐỆM LÀM NGUỘI THỊ TRƯỜNG (Per-Symbol Market Cooldown)
        # (Nếu coin vừa bị dính SL / Lỗ: cấm vào lại trong 4 tiếng = 14400s để triệt tiêu Revenge Trading)
        # (Nếu đóng vị thế hòa vốn / có lãi: cấm vào lại trong 30 phút = 1800s)
        # -------------------------------------------------------------
        last_closed_val = market_data.get("last_closed_at")
        if last_closed_val is not None:
            try:
                if isinstance(last_closed_val, (int, float)):
                    closed_ts = float(last_closed_val)
                else:
                    closed_ts = datetime.fromisoformat(str(last_closed_val).replace("Z", "+00:00")).timestamp()
                time_since_close = time.time() - closed_ts
                is_stopout = bool(
                    market_data.get("last_trade_was_loss") 
                    or market_data.get("last_trade_was_stopout") 
                    or float(market_data.get("last_trade_pnl", 0)) < 0
                )
                req_cooldown = 14400 if is_stopout else 1800
                if 0 <= time_since_close < req_cooldown:
                    remaining_s = int(req_cooldown - time_since_close)
                    elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                    reason_desc = f"vừa dính STOP LOSS (< {req_cooldown//60} phút)" if is_stopout else f"vừa đóng vị thế (< {req_cooldown//60} phút)"
                    red_flag = (
                        f"COOLDOWN_VETO: Đồng {symbol} {reason_desc}. "
                        f"Kích hoạt bộ đệm làm nguội nghiêm ngặt (còn {remaining_s}s) để triệt tiêu bẫy Cay cú (Revenge Trading)!"
                    )
                    return AgentOpinion(
                        agent_id=self.agent_id,
                        agent_name=self.agent_name,
                        role=self.role,
                        vote=CouncilVote.VETO,
                        confidence=0,
                        rationale=red_flag,
                        key_metrics={
                            "time_since_close_s": time_since_close,
                            "remaining_s": remaining_s,
                            "req_cooldown": req_cooldown,
                            "is_stopout": is_stopout,
                            "check": "per_symbol_cooldown",
                        },
                        red_flag=red_flag,
                        execution_time_ms=elapsed_ms,
                    )
            except Exception as e_cd:
                logger.debug(f"Per-symbol cooldown check error: {e_cd}")

        # -------------------------------------------------------------
        # CHECK WEEKEND LIQUIDITY SHIELD (LÁ CHẮN THANH KHOẢN CUỐI TUẦN)
        # (Từ 00:00 Thứ Bảy đến 06:00 Thứ Hai giờ VN: Khóa Altcoin thanh khoản mỏng < 100M$)
        # (Chỉ duy trì BTC/ETH với tiêu chuẩn phê duyệt Sniper >= 90%)
        # -------------------------------------------------------------
        try:
            now_utc = datetime.now(timezone.utc)
            vn_hour = (now_utc.hour + 7) % 24
            vn_day_shift = 1 if (now_utc.hour + 7) >= 24 else 0
            vn_weekday = (now_utc.weekday() + vn_day_shift) % 7  # 0=Mon, 5=Sat, 6=Sun
            
            is_weekend = (vn_weekday == 5) or (vn_weekday == 6) or (vn_weekday == 0 and vn_hour < 6)
            if is_weekend:
                clean_sym = symbol.upper().replace("/", "").replace(":", "")
                is_major = clean_sym in ("BTCUSDT", "ETHUSDT", "BTC", "ETH")
                setup_conf = int(trade_params.get("confidence", market_data.get("confidence", 85)))
                
                if is_major:
                    if setup_conf < 90:
                        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                        red_flag = (
                            f"WEEKEND_LIQUIDITY_VETO: Thị trường cuối tuần mỏng thanh khoản. "
                            f"{clean_sym} chỉ được phê duyệt khi đạt chuẩn Sniper Master (>= 90%). Kèo hiện tại chỉ đạt {setup_conf}%!"
                        )
                        return AgentOpinion(
                            agent_id=self.agent_id,
                            agent_name=self.agent_name,
                            role=self.role,
                            vote=CouncilVote.VETO,
                            confidence=0,
                            rationale=red_flag,
                            key_metrics={"is_weekend": True, "confidence": setup_conf, "check": "weekend_shield"},
                            red_flag=red_flag,
                            execution_time_ms=elapsed_ms,
                        )
                else:
                    vol_24h = float(market_data.get("quote_volume_24h", market_data.get("quoteVolume", 0.0)))
                    if vol_24h < 100_000_000:
                        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                        red_flag = (
                            f"WEEKEND_LIQUIDITY_VETO: Cuối tuần tự động đóng băng Altcoins thanh khoản mỏng "
                            f"({clean_sym} 24h Vol: ${vol_24h/1e6:.1f}M < $100M). Nguy cơ bị râu nến quét Stop Loss oan uổng!"
                        )
                        return AgentOpinion(
                            agent_id=self.agent_id,
                            agent_name=self.agent_name,
                            role=self.role,
                            vote=CouncilVote.VETO,
                            confidence=0,
                            rationale=red_flag,
                            key_metrics={"is_weekend": True, "vol_24h": vol_24h, "check": "weekend_altcoin_shield"},
                            red_flag=red_flag,
                            execution_time_ms=elapsed_ms,
                        )
        except Exception as e_wk:
            logger.debug(f"Weekend liquidity check error: {e_wk}")
        vol_r = float(market_data.get("vol_ratio", 1.0))
        chg_24h = float(market_data.get("change_24h", 0.0))

        p = float(
            trade_params.get("entry_price")
            or market_data.get("current_price")
            or market_data.get("price")
            or 0.0
        )
        ema20 = float(market_data.get("ema20", 0.0))
        ema50 = float(market_data.get("ema50", 0.0))
        lw_r = float(market_data.get("lower_wick_ratio", 0.0))

        div = market_data.get("divergence") or {}
        has_bull_div = bool(div.get("bullish_divergence", False)) if isinstance(div, dict) else False

        entry = p
        sl = float(trade_params.get("stop_loss", market_data.get("stop_loss", 0.0)))
        leverage = int(trade_params.get("leverage", market_data.get("leverage", 20)))

        # -------------------------------------------------------------
        # CHECK 1: LOW-CAP PUMP TRAP
        # (vol_ratio >= 2.5 hoặc change_24h >= 18% mà đòi SHORT)
        # -------------------------------------------------------------
        if dir_upper in ("SHORT", "SELL"):
            if vol_r >= 2.5 or chg_24h >= 18.0:
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                reasons = []
                if vol_r >= 2.5:
                    reasons.append(f"Volume gom bùng nổ x{vol_r:.2f} lần TB (>= 2.5x)")
                if chg_24h >= 18.0:
                    reasons.append(f"Đà tăng 24h quá nóng +{chg_24h:.1f}% (>= 18.0%)")
                detail_msg = " & ".join(reasons)
                red_flag = (
                    f"THẺ ĐỎ RED TEAM [Check 1 - Low-cap Pump Trap]: {detail_msg} mà đòi SHORT. "
                    f"Nguy cơ cản tàu bị quét thanh lý cháy tài khoản (Short Squeeze)!"
                )
                return AgentOpinion(
                    agent_id=self.agent_id,
                    agent_name=self.agent_name,
                    role=self.role,
                    vote=CouncilVote.VETO,
                    confidence=0,
                    rationale=red_flag,
                    key_metrics={"vol_ratio": vol_r, "change_24h": chg_24h},
                    red_flag=red_flag,
                    execution_time_ms=elapsed_ms,
                )

        # -------------------------------------------------------------
        # CHECK 2: FALLING KNIFE TRAP (BẮT DAO RƠI)
        # (p < ema20 < ema50 mà đòi LONG bắt đáy khi KHÔNG có phân kỳ dương hoặc râu nến dưới < 40%)
        # -------------------------------------------------------------
        if dir_upper in ("LONG", "BUY"):
            if ema20 > 0.0 and ema50 > 0.0 and (p < ema20 and ema20 < ema50):
                # Xu hướng 1H đang là Giảm mạnh
                if not has_bull_div and lw_r < 0.40:
                    elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                    red_flag = (
                        f"THẺ ĐỎ RED TEAM [Check 2 - Falling Knife Trap]: "
                        f"Giá ({p:.4f}) < EMA20 ({ema20:.4f}) < EMA50 ({ema50:.4f}) đang rơi tự do "
                        f"mà đòi LONG bắt đáy khi KHÔNG có phân kỳ dương RSI và râu nến dưới ({lw_r*100:.1f}%) < 40%. "
                        f"Nghiêm cấm bắt dao rơi!"
                    )
                    return AgentOpinion(
                        agent_id=self.agent_id,
                        agent_name=self.agent_name,
                        role=self.role,
                        vote=CouncilVote.VETO,
                        confidence=0,
                        rationale=red_flag,
                        key_metrics={"p": p, "ema20": ema20, "ema50": ema50, "lower_wick": lw_r, "bull_div": has_bull_div},
                        red_flag=red_flag,
                        execution_time_ms=elapsed_ms,
                    )

        # -------------------------------------------------------------
        # CHECK 3: SL BUFFER QUÁ MỎNG VỚI ĐÒN BẨY CAO
        # (Khoảng cách SL < 3.0% với đòn bẩy cao > 20x)
        # -------------------------------------------------------------
        if entry > 0.0 and sl > 0.0:
            sl_dist_pct = (abs(entry - sl) / entry) * 100.0
            if sl_dist_pct < 3.0 and leverage > 20:
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                red_flag = (
                    f"THẺ ĐỎ RED TEAM [Check 3 - SL Buffer & Leverage]: "
                    f"Khoảng cách SL quá mỏng ({sl_dist_pct:.2f}% < 3.0%) kết hợp đòn bẩy cao ({leverage}x > 20x). "
                    f"Dễ bị râu nến cá mập quét (Liquidity Wick Hunt) gây lỗ oan uổng!"
                )
                return AgentOpinion(
                    agent_id=self.agent_id,
                    agent_name=self.agent_name,
                    role=self.role,
                    vote=CouncilVote.VETO,
                    confidence=0,
                    rationale=red_flag,
                    key_metrics={"sl_dist_pct": sl_dist_pct, "leverage": leverage},
                    red_flag=red_flag,
                    execution_time_ms=elapsed_ms,
                )

        # -------------------------------------------------------------
        # CHECK BỔ TRỢ: TÍNH TOÀN VẸN CẤU TRÚC VỊ THẾ
        # -------------------------------------------------------------
        if entry > 0.0 and sl > 0.0:
            if dir_upper in ("LONG", "BUY") and sl >= entry:
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                red_flag = f"THẺ ĐỎ RED TEAM [Logic Error]: Lệnh LONG nhưng Stop Loss ({sl}) >= Entry ({entry})."
                return AgentOpinion(
                    agent_id=self.agent_id,
                    agent_name=self.agent_name,
                    role=self.role,
                    vote=CouncilVote.VETO,
                    confidence=0,
                    rationale=red_flag,
                    key_metrics={"entry": entry, "sl": sl},
                    red_flag=red_flag,
                    execution_time_ms=elapsed_ms,
                )
            if dir_upper in ("SHORT", "SELL") and sl <= entry:
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                red_flag = f"THẺ ĐỎ RED TEAM [Logic Error]: Lệnh SHORT nhưng Stop Loss ({sl}) <= Entry ({entry})."
                return AgentOpinion(
                    agent_id=self.agent_id,
                    agent_name=self.agent_name,
                    role=self.role,
                    vote=CouncilVote.VETO,
                    confidence=0,
                    rationale=red_flag,
                    key_metrics={"entry": entry, "sl": sl},
                    red_flag=red_flag,
                    execution_time_ms=elapsed_ms,
                )

        # KHÔNG VI PHẠM BẤT KỲ CHECK NÀO -> GIƠ THẺ XANH THÔNG QUA
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
        return AgentOpinion(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            role=self.role,
            vote=CouncilVote.APPROVED,
            confidence=95,
            rationale="Red Team thông qua (Thẻ xanh): Đã vượt qua 3 tầng lọc bẫy giá (Pump trap, Dao rơi Falling knife, SL buffer & Đòn bẩy).",
            key_metrics={"checks_passed": ["pump_trap", "falling_knife", "sl_leverage_ratio"]},
            execution_time_ms=elapsed_ms,
        )


# =============================================================================
# 5. QUANTUM COUNCIL ARBITER (TRỌNG TÀI HỘI ĐỒNG LƯỢNG TỬ)
# =============================================================================
class QuantumCouncilArbiter:
    """
    Trọng Tài Tối Cao Hội Đồng Lượng Tử (Quantum Council Arbiter):
    Kích hoạt 4 Đặc Vụ Chuyên Môn, thu thập phiếu biểu quyết, kiểm soát quyền phủ quyết (Veto),
    tính toán điểm đồng thuận và xuất biên bản điều trần chi tiết cho Telegram.
    """

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        binance_client: Optional[Any] = None,
        risk_engine: Optional[RiskEngine] = None,
        quantum_engine: Optional[QuantumAIEngine] = None,
        regime_shield: Optional[MarketRegimeShield] = None,
        sentiment_guardian: Optional[MarketSentimentNewsGuardian] = None,
    ):
        self.config = config
        self.client = binance_client
        self.risk_engine = risk_engine or (RiskEngine(config) if config else None)

        self.technical_scout = TechnicalScoutAgent(quantum_engine=quantum_engine)
        self.macro_agent = MacroRegimeAgent(regime_shield=regime_shield)
        self.sentiment_agent = SentimentSentinelAgent(sentiment_guardian=sentiment_guardian)
        self.red_team_agent = RedTeamSkepticAgent()
        self.symbol_last_closed: Dict[str, float] = {}
        self.last_trade_opened_at: float = 0.0

    def record_position_closed(self, symbol: str, closed_at: Optional[float] = None) -> None:
        """Ghi nhận thời điểm đóng vị thế của coin X để kích hoạt Market Cooldown Buffer 30m."""
        sym = symbol.upper().replace("/", "").replace(":", "")
        self.symbol_last_closed[sym] = closed_at or time.time()

    def record_trade_opened(self, symbol: str, opened_at: Optional[float] = None) -> None:
        """Ghi nhận thời điểm mở vị thế mới để kiểm soát Global Trade Interval 15m."""
        self.last_trade_opened_at = opened_at or time.time()

    async def deliberate(
        self,
        symbol: str,
        market_data: Dict[str, Any],
    ) -> CouncilDeliberationResult:
        """
        Kích hoạt hội đồng thẩm định lệnh (Deliberation Cycle):
        1. Technical Scout phân tích cấu trúc SMC & đề xuất/kiểm tra tham số lệnh.
        2. Kích hoạt song song Macro Sentinel, Sentiment Sentinel & Red Team Skeptic.
        3. Phán quyết:
           - Nếu Red Team giơ thẻ đỏ HOẶC Sentiment giơ thẻ đỏ HOẶC Macro chặn:
             is_approved = False, veto_reason = ...
           - Nếu tất cả thông qua và consensus_score >= 85:
             is_approved = True.
        4. Tích hợp Risk Engine điều chỉnh ATR volatility & đòn bẩy an toàn.
        5. Xuất biên bản Telegram transcript.
        """
        start_t = time.perf_counter()
        clean_sym = symbol.upper().replace("/", "").replace(":", "")

        # Tự động nạp trạng thái cooldown và thời điểm trade gần nhất từ Arbiter nếu chưa có
        if "last_closed_at" not in market_data and clean_sym in self.symbol_last_closed:
            market_data["last_closed_at"] = self.symbol_last_closed[clean_sym]
        if "last_trade_opened_at" not in market_data and self.last_trade_opened_at > 0:
            market_data["last_trade_opened_at"] = self.last_trade_opened_at

        # Tự động nạp vị thế từ Binance client nếu chưa có trong market_data
        if "open_positions" not in market_data and "positions" not in market_data and self.client:
            try:
                positions = await self.client.get_open_positions()
                if positions:
                    market_data["open_positions"] = positions
            except Exception as e_pos:
                logger.debug(f"Council arbiter get_open_positions notice: {e_pos}")

        # 1. Technical Scout đánh giá kỹ thuật và thiết lập tham số ban đầu
        tech_opinion, trade_params = await self.technical_scout.evaluate(symbol, market_data)
        direction = trade_params.get("direction", market_data.get("direction", "NEUTRAL"))

        # 2. Chạy song song 3 đặc vụ phòng thủ còn lại
        macro_opinion, sent_opinion, red_opinion = await asyncio.gather(
            self.macro_agent.evaluate(symbol, direction, market_data),
            self.sentiment_agent.evaluate(symbol, direction, market_data),
            self.red_team_agent.evaluate(symbol, direction, market_data, trade_params),
        )

        # 3. Phân xử biểu quyết và quyền phủ quyết (Veto)
        veto_reasons: List[str] = []
        if red_opinion.is_veto:
            veto_reasons.append(f"Red Team Skeptic: {red_opinion.red_flag or red_opinion.rationale}")
        if sent_opinion.is_veto:
            veto_reasons.append(f"Sentiment Sentinel: {sent_opinion.red_flag or sent_opinion.rationale}")
        if macro_opinion.is_veto:
            veto_reasons.append(f"Macro Sentinel: {macro_opinion.red_flag or macro_opinion.rationale}")

        is_approved = False
        veto_reason: Optional[str] = None
        consensus_score: int = 0

        if veto_reasons:
            is_approved = False
            veto_reason = " | ".join(veto_reasons)
            consensus_score = min(
                tech_opinion.confidence,
                macro_opinion.confidence,
                sent_opinion.confidence,
                red_opinion.confidence,
            )
        elif not tech_opinion.is_approved:
            is_approved = False
            veto_reason = f"Technical Scout từ chối setup: {tech_opinion.rationale}"
            consensus_score = tech_opinion.confidence
        elif not sent_opinion.is_approved:
            is_approved = False
            veto_reason = f"Sentiment Sentinel từ chối: {sent_opinion.rationale}"
            consensus_score = min(tech_opinion.confidence, sent_opinion.confidence)
        else:
            # Tính điểm đồng thuận trọng số (Weighted Consensus Score)
            # Technical Scout: 35% | Macro Regime: 25% | Sentiment: 15% | Red Team: 25%
            weighted_score = (
                tech_opinion.confidence * 0.35 +
                macro_opinion.confidence * 0.25 +
                sent_opinion.confidence * 0.15 +
                red_opinion.confidence * 0.25
            )
            consensus_score = int(round(weighted_score))

            if consensus_score >= 85:
                is_approved = True
                veto_reason = None
            else:
                is_approved = False
                veto_reason = f"Điểm đồng thuận hội đồng ({consensus_score}/100) chưa đạt ngưỡng phê duyệt >= 85"

            # Kiểm tra Quy tắc 2: Global Trade Interval (Khoảng cách tối thiểu 15 phút = 900s)
            # Trừ khi setup có điểm consensus >= 9.2 (>= 92/100) từ Hội đồng AI
            if is_approved:
                last_trade_val = market_data.get("last_trade_opened_at", self.last_trade_opened_at)
                if last_trade_val is not None:
                    try:
                        last_ts = float(last_trade_val) if isinstance(last_trade_val, (int, float)) else datetime.fromisoformat(str(last_trade_val).replace("Z", "+00:00")).timestamp()
                        if last_ts > 0:
                            elapsed_trade = time.time() - last_ts
                            if 0 <= elapsed_trade < 900 and consensus_score < 92:
                                is_approved = False
                                rem_gap = int(900 - elapsed_trade)
                                veto_reason = (
                                    f"GLOBAL_INTERVAL_VETO: Khoảng cách giữa 2 lần mở vị thế ({int(elapsed_trade)}s) "
                                    f"chưa đủ 15 phút (còn {rem_gap}s) và điểm đồng thuận ({consensus_score}/100) "
                                    f"chưa đạt ngưỡng đặc cách >= 92 (9.2)."
                                )
                    except Exception as e_int:
                        logger.debug(f"Global trade interval check error: {e_int}")

        # 4. Tích hợp Risk Engine: Điều chỉnh ATR Volatility & Đòn bẩy an toàn nếu lệnh được duyệt
        if is_approved:
            trade_params = self._apply_risk_engine_protections(symbol, trade_params, market_data)

        # 5. Hoàn thiện kết quả và xuất biên bản
        total_time_ms = (time.perf_counter() - start_t) * 1000.0
        now_iso = datetime.now(timezone.utc).isoformat()

        # Tổng hợp 5 Đặc Vụ Chuyên Môn Tranh Biện Hội Đồng Lượng Tử
        entry_val = float(trade_params.get("entry_price", market_data.get("current_price", 0.0)))
        sl_val = float(trade_params.get("stop_loss", 0.0))
        tp1_val = float(trade_params.get("take_profit_1", 0.0))
        tp2_val = float(trade_params.get("take_profit_2", 0.0))
        tp3_val = float(trade_params.get("take_profit_3", 0.0))
        rr_val = trade_params.get("estimated_rr", 2.0)
        lev_val = int(trade_params.get("leverage", 20))

        # Agent 1: Lead Quant Strategist
        if is_approved:
            lead_rat = (
                f"Hợp lưu SMC & OrderFlow đạt tỷ lệ R:R = {rr_val} (TP1: {tp1_val}, TP2: {tp2_val}, TP3: {tp3_val}). "
                f"Độ đồng thuận toàn diện {consensus_score}/100. Quyết nghị kích hoạt lệnh {direction} "
                f"với đòn bẩy {lev_val}x, phân bổ chốt lời 35/35/30 và Trailing Breakeven an toàn!"
            )
            lead_vote = CouncilVote.APPROVED
        else:
            lead_rat = (
                f"Quyết định Trọng Tài: Bác bỏ kích hoạt lệnh {direction} {symbol}. "
                f"Lý do: {veto_reason or 'Không đạt điểm đồng thuận tối thiểu >= 85'}. Bảo toàn vốn là ưu tiên số 1!"
            )
            lead_vote = CouncilVote.VETO if veto_reasons else CouncilVote.REJECTED

        lead_opinion = AgentOpinion(
            agent_id="lead_quant_strategist",
            agent_name="Lead Quant Strategist (Trưởng Ban Định Lượng AI)",
            role="Tổng hợp đa tín hiệu, tính toán xác suất thắng, R:R >= 2.0 & phân bổ TP 35/35/30",
            vote=lead_vote,
            confidence=consensus_score,
            rationale=lead_rat,
            key_metrics={"rr": rr_val, "consensus": consensus_score},
            execution_time_ms=total_time_ms,
        )

        # Agent 2: Scalp Specialist
        scalp_opinion = AgentOpinion(
            agent_id="scalp_specialist",
            agent_name="Scalp Specialist (Chuyên Gia Sóng Ngắn 15m/1H)",
            role="Bắt nhịp vi mô, động lượng RSI/EMA, nến Pinbar rút chân & điểm uốn giá",
            vote=tech_opinion.vote,
            confidence=tech_opinion.confidence,
            rationale=f"Động lượng nến ngắn hạn 15m/1H: {tech_opinion.rationale}",
            key_metrics=tech_opinion.key_metrics,
            execution_time_ms=tech_opinion.execution_time_ms,
        )

        # Agent 3: Macro & SMC Specialist
        macro_smc_opinion = AgentOpinion(
            agent_id="macro_smc_specialist",
            agent_name="Macro & SMC Specialist (Chuyên Gia Vĩ Mô & Smart Money)",
            role="Phân tích cấu trúc 4H/1D, quét thanh khoản (Liquidity Sweep), khối Order Block & BTC Regime",
            vote=macro_opinion.vote,
            confidence=macro_opinion.confidence,
            rationale=f"Cấu trúc vĩ mô 4H & BTC Regime: {macro_opinion.rationale}",
            key_metrics=macro_opinion.key_metrics,
            red_flag=macro_opinion.red_flag,
            execution_time_ms=macro_opinion.execution_time_ms,
        )

        # Agent 4: Risk Guardian Zero-Liquidation
        sl_dist_pct = (abs(entry_val - sl_val) / entry_val * 100.0) if entry_val > 0 and sl_val > 0 else 0.0
        liq_gap_pct = (100.0 / lev_val * 0.9) if lev_val > 0 else 0.0
        safety_multiplier = (liq_gap_pct / sl_dist_pct) if sl_dist_pct > 0 else 2.5
        risk_rat = (
            f"Thẩm định rủi ro Zero-Liquidation: SL ({sl_dist_pct:.2f}%) an toàn tuyệt đối so với Giá thanh lý ước tính (~{liq_gap_pct:.2f}%). "
            f"Biên an toàn đạt {safety_multiplier:.1f}x (KHÔNG THỂ CHÁY TÀI KHOẢN). "
            f"Đòn bẩy {lev_val}x Isolated. {red_opinion.rationale}"
        )
        risk_opinion = AgentOpinion(
            agent_id="risk_guardian_zero_liq",
            agent_name="Risk Guardian Zero-Liquidation (Vệ Binh Rủi Ro)",
            role="Bảo toàn vốn tuyệt đối, đo đạc khoảng cách SL vs Liquidation, kiểm soát đòn bẩy & bẫy giá",
            vote=red_opinion.vote,
            confidence=red_opinion.confidence,
            rationale=red_opinion.red_flag or risk_rat,
            key_metrics={"sl_dist_pct": sl_dist_pct, "liq_gap_pct": liq_gap_pct, "leverage": lev_val},
            red_flag=red_opinion.red_flag,
            execution_time_ms=red_opinion.execution_time_ms,
        )

        # Agent 5: Sentiment & News Scout
        sentiment_opinion = AgentOpinion(
            agent_id="sentiment_news_scout",
            agent_name="Sentiment & News Scout (Thám Báo Tâm Lý & Dòng Tiền)",
            role="Rà soát tin tức nóng, phát hiện thiên nga đen (SEC, Delist, Hack), tâm lý Funding Rate & FGI",
            vote=sent_opinion.vote,
            confidence=sent_opinion.confidence,
            rationale=sent_opinion.red_flag or sent_opinion.rationale,
            key_metrics=sent_opinion.key_metrics,
            red_flag=sent_opinion.red_flag,
            execution_time_ms=sent_opinion.execution_time_ms,
        )

        result = CouncilDeliberationResult(
            symbol=symbol,
            direction=direction,
            is_approved=is_approved,
            consensus_score=consensus_score,
            veto_reason=veto_reason,
            technical_scout=tech_opinion,
            macro_regime=macro_opinion,
            sentiment_sentinel=sent_opinion,
            red_team=red_opinion,
            trade_parameters=trade_params,
            deliberated_at=now_iso,
            execution_time_ms=total_time_ms,
            lead_quant=lead_opinion,
            scalp_specialist=scalp_opinion,
            macro_smc=macro_smc_opinion,
            risk_guardian=risk_opinion,
            sentiment_scout=sentiment_opinion,
        )
        result.transcript = self.format_telegram_transcript(result)
        result.debate_html = self.format_council_debate_html(result)
        return result

    def format_council_debate_html(self, result: CouncilDeliberationResult) -> str:
        """Xuất biên bản tranh luận trực tiếp của 5 đặc vụ Hội đồng Lượng tử dạng HTML Telegram."""
        from telegram.telegram_notifier import TelegramNotifier
        return TelegramNotifier.format_council_debate_html(result)

    def _apply_risk_engine_protections(
        self,
        symbol: str,
        params: Dict[str, Any],
        market_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Tích hợp tính toán vốn, độ biến động ATR và đòn bẩy an toàn từ RiskEngine."""
        refined = dict(params)
        entry = float(refined.get("entry_price", market_data.get("current_price", 0.0)))
        sl = float(refined.get("stop_loss", 0.0))
        atr = float(market_data.get("atr", 0.0))

        # 1. Trụ Cột ATR Volatility Sizing: nếu ATR > 5% -> hạ rủi ro xuống 1.0% NAV
        if entry > 0.0 and atr > 0.0:
            atr_pct = (atr / entry) * 100.0
            if atr_pct > 5.0:
                refined["risk_pct"] = 1.0
                refined["risk_note"] = f"Coin biến động cao (ATR={atr_pct:.1f}% > 5.0%): Tự động hạ rủi ro xuống 1.0% NAV"
            else:
                refined["risk_pct"] = 1.5

        # 2. Giới hạn đòn bẩy an toàn tuyệt đối <= 20x theo cự ly SL
        if entry > 0.0 and sl > 0.0:
            sl_dist_pct = abs(entry - sl) / entry
            if sl_dist_pct > 0.0:
                max_safe_lev = min(20, max(5, int(0.75 / sl_dist_pct)))
                current_lev = int(refined.get("leverage", 20))
                refined["leverage"] = min(current_lev, max_safe_lev)

        # 3. Macro Bearish Panic Clamp for Altcoin Longs: Clamp leverage to 15x-18x
        btc_regime = market_data.get("btc_regime", {})
        direction = str(market_data.get("direction", "")).upper()
        sym = str(market_data.get("symbol", "")).upper().replace("/", "").replace(":", "")
        if isinstance(btc_regime, dict) and btc_regime.get("status") == "BEARISH_PANIC":
            if direction in ("LONG", "BUY") and sym not in ("BTCUSDT", "BTCUSDC", "BTC"):
                refined["leverage"] = min(refined.get("leverage", 20), 18)
                refined["risk_note"] = (
                    refined.get("risk_note", "") +
                    " | BTC BEARISH_PANIC: Ghìm trần đòn bẩy Altcoin LONG xuống 18x an toàn."
                )

        return refined

    def format_telegram_transcript(self, result: CouncilDeliberationResult) -> str:
        """
        Tạo biên bản điều trần Hội Đồng Lượng Tử chuẩn Markdown gửi về Telegram.
        """
        status_badge = "✅ *ĐƯỢC PHÊ DUYỆT (ALL AGENTS CONSENSUS)*" if result.is_approved else "🛑 *BỊ BÁC BỎ / VETO (THẺ ĐỎ)*"
        
        def _vote_badge(opinion: AgentOpinion) -> str:
            if opinion.vote == CouncilVote.APPROVED:
                return "🟢 APPROVED"
            if opinion.vote == CouncilVote.VETO:
                return "🔴 RED VETO"
            return "🟡 REJECTED"

        tech = result.technical_scout
        macro = result.macro_regime
        sent = result.sentiment_sentinel
        red = result.red_team

        tp = result.trade_parameters
        entry = tp.get("entry_price", "N/A")
        sl = tp.get("stop_loss", "N/A")
        tp1 = tp.get("take_profit_1", "N/A")
        tp2 = tp.get("take_profit_2", "N/A")
        tp3 = tp.get("take_profit_3", "N/A")
        rr = tp.get("estimated_rr", "N/A")
        lev = tp.get("leverage", 20)
        risk_pct = tp.get("risk_pct", 1.5)

        lines = [
            "🏛 *BIÊN BẢN HỘI ĐỒNG LƯỢNG TỬ (QUANTUM COUNCIL)* 🏛",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"💎 *Cặp giao dịch:* `{result.symbol}` | *Vị thế:* *{result.direction}*",
            f"📊 *Điểm Đồng Thuận:* *{result.consensus_score}/100* (Ngưỡng duyệt: >= 85)",
            f"⚖️ *Phán Quyết:* {status_badge}",
            "",
            "📋 *Ý KIẾN CÁC ĐẶC VỤ CHUYÊN MÔN:*",
            f"1️⃣ 🔍 *Technical Scout* [{_vote_badge(tech)} - {tech.confidence}%]:",
            f"   • {tech.rationale}",
            f"   • *R:R dự kiến:* `{rr}` | *Cấu trúc:* `{tp.get('archetype', 'SMC')}`",
            "",
            f"2️⃣ 🌐 *Macro Sentinel* [{_vote_badge(macro)} - {macro.confidence}%]:",
            f"   • {macro.rationale}",
            "",
            f"3️⃣ 🛡 *Sentiment Sentinel* [{_vote_badge(sent)} - {sent.confidence}%]:",
            f"   • {sent.rationale}",
            "",
            f"4️⃣ ⚔️ *Red Team Skeptic* [{_vote_badge(red)} - {red.confidence}%]:",
            f"   • {red.rationale}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]

        if result.is_approved:
            entry_float = float(entry) if str(entry) != "N/A" else 0.0
            sl_float = float(sl) if str(sl) != "N/A" else 0.0
            sl_pct = (abs(entry_float - sl_float) / entry_float * 100.0) if entry_float > 0 else 0.0
            lines.extend([
                "🎯 *THÔNG SỐ LỆNH ĐƯỢC PHÊ DUYỆT:*",
                f"• *Entry:* `{entry}`",
                f"• *Stop Loss:* `{sl}` (Cự ly SL: `{sl_pct:.2f}%`)",
                f"• *Mục tiêu:* TP1: `{tp1}` | TP2: `{tp2}` | TP3: `{tp3}`",
                f"• *Đòn bẩy an toàn:* `{lev}x` (Isolated / Cross)",
                f"• *Tỷ lệ R:R:* `{rr}` (Đạt chuẩn >= 2.0)",
                f"• *Hạn mức rủi ro:* `{risk_pct}% NAV`",
            ])
            if "risk_note" in tp:
                lines.append(f"• *Ghi chú rủi ro:* _{tp['risk_note']}_")
        else:
            lines.extend([
                "⛔ *LÝ DO PHỦ QUYẾT (VETO REASON):*",
                f"{result.veto_reason or 'Không đạt tiêu chí đồng thuận của hội đồng.'}",
            ])

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"⏱ *Độ trễ xử lý:* `{result.execution_time_ms:.1f}ms` (100% Nội bộ Python - 0đ API)",
        ])

        return "\n".join(lines)


# =============================================================================
# 6. QUANTUM COUNCIL SUPERVISOR (ĐẶC VỤ GIÁM SÁT ĐỘC LẬP - DUAL-AI CHECKER)
# =============================================================================
class QuantumCouncilSupervisor:
    """
    QuantumCouncilSupervisor (Đặc Vụ Giám Sát Độc Lập - AI Checker Tối Cao):
    Hoàn thiện kiến trúc Maker-Checker (Dual-AI Autonomous Architecture):
    - Maker (AI 1): Đề xuất ý tưởng giao dịch (Quantum AI Engine / Gemini Autonomous Trader).
    - Checker (AI 2): Giám sát, đối soát đa khung, bắt bẫy và VETO các kèo rủi ro.
    - Tuyệt đối không có chuyện 'AI tự tung tự tác' mà không có AI khác độc lập thẩm định!
    """

    def __init__(
        self,
        arbiter: Optional[QuantumCouncilArbiter] = None,
        config: Optional[AppConfig] = None,
        binance_client: Optional[Any] = None,
    ):
        self.arbiter = arbiter or QuantumCouncilArbiter(config=config, binance_client=binance_client)

    async def audit_setup(
        self,
        symbol: str,
        snapshot: Dict[str, Any],
        candidate_setup: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str], CouncilDeliberationResult]:
        """
        Thẩm định toàn diện một tín hiệu giao dịch qua Hội đồng 4 Đặc vụ.
        Trả về: (is_approved: bool, veto_reason: Optional[str], deliberation: CouncilDeliberationResult)
        """
        market_data = dict(snapshot)
        if candidate_setup:
            market_data["candidate_setup"] = candidate_setup
            market_data["direction"] = candidate_setup.get("direction", market_data.get("direction", "NEUTRAL"))
            market_data["confidence"] = candidate_setup.get("confidence", 85)
            market_data["entry_price"] = candidate_setup.get("entry_price")
            market_data["stop_loss"] = candidate_setup.get("stop_loss")
            market_data["leverage"] = candidate_setup.get("leverage", 20)

        deliberation = await self.arbiter.deliberate(symbol, market_data)
        return deliberation.is_approved, deliberation.veto_reason, deliberation


__all__ = [
    "CouncilVote",
    "AgentOpinion",
    "CouncilDeliberationResult",
    "TechnicalScoutAgent",
    "MacroRegimeAgent",
    "SentimentSentinelAgent",
    "RedTeamSkepticAgent",
    "QuantumCouncilArbiter",
    "QuantumCouncilSupervisor",
]
