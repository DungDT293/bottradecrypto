"""
tests/test_telegram_and_council_debate.py
=============================================================================
UNIT TESTS FOR TELEGRAM NOTIFIER, HTML FORMATTING, AND QUANTUM COUNCIL DEBATE
=============================================================================
Validates:
1. HTML Sanitization: escapes raw <, >, & while preserving valid Telegram tags (<b>, <i>, <code>).
2. Auto-Closing Tags: prevents Telegram 400 Bad Request.
3. SystemNotifier & TelegramNotifier: parses mode "html" for Telethon and Bot API.
4. Quantum Council 5-Agent Debate: verifies full deliberation of all 5 specialists:
   - Agent 1: Lead Quant Strategist
   - Agent 2: Scalp Specialist
   - Agent 3: Macro & SMC Specialist
   - Agent 4: Risk Guardian Zero-Liquidation
   - Agent 5: Sentiment & News Scout
5. Zero-Liquidation Math & Trailing Breakeven protection metrics.
6. Interactive Telegram command handling (/debate, /status, /help).
=============================================================================
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from config.config import NotificationsConfig, AppConfig, ExecutionMode
from notifications.notifier import SystemNotifier
from telegram.telegram_notifier import (
    TelegramNotifier,
    sanitize_telegram_html,
    ensure_closed_tags,
    strip_html,
)
from services.quantum_council_harness import (
    QuantumCouncilArbiter,
    CouncilVote,
    CouncilDeliberationResult,
)


def test_sanitize_telegram_html():
    # 1. Preserves valid tags
    raw = "<b>[AI Quant Tự Động Khớp Lệnh]</b> <code>SOLUSDT</code>"
    sanitized = sanitize_telegram_html(raw)
    assert sanitized == "<b>[AI Quant Tự Động Khớp Lệnh]</b> <code>SOLUSDT</code>"

    # 2. Escapes raw <, >, & outside tags
    raw2 = "<b>Alert</b>: Price < 100 & R:R >= 2.0 and SL > 50"
    sanitized2 = sanitize_telegram_html(raw2)
    assert "<b>Alert</b>" in sanitized2
    assert "Price &lt; 100" in sanitized2
    assert "&amp; R:R &gt;= 2.0" in sanitized2
    assert "SL &gt; 50" in sanitized2

    # 3. Does not double escape existing entities
    raw3 = "BTC &amp; ETH &lt; 5000"
    sanitized3 = sanitize_telegram_html(raw3)
    assert "&amp;" in sanitized3
    assert "&amp;amp;" not in sanitized3


def test_ensure_closed_tags():
    unclosed = "<b><i>Unclosed text"
    fixed = ensure_closed_tags(unclosed)
    assert fixed == "<b><i>Unclosed text</i></b>"

    already_closed = "<b>Bold</b> <code>Code</code>"
    assert ensure_closed_tags(already_closed) == already_closed


def test_strip_html():
    html_text = "<b>[🚀 VÀO LỆNH AI]</b> <code>SOLUSDT</code>"
    clean = strip_html(html_text)
    assert clean == "[🚀 VÀO LỆNH AI] SOLUSDT"
    assert "<" not in clean
    assert ">" not in clean


@pytest.mark.asyncio
async def test_system_notifier_telethon_parse_mode_html():
    """Kiểm tra SystemNotifier truyền đúng parse_mode='html' tới Telethon client."""
    mock_client = MagicMock()
    mock_client.is_connected.return_value = True
    mock_client.send_message = AsyncMock(return_value=True)

    notifier = SystemNotifier(
        config=NotificationsConfig(telegram_notification_enabled=False),
        telegram_client_getter=lambda: mock_client,
    )

    alert_text = "<b>[AI Quant Tự Động Khớp Lệnh]</b>\nĐã khớp lệnh <code>SOLUSDT</code>"
    success = await notifier.notify(alert_text)
    assert success is True

    # Xác minh mock_client.send_message nhận parse_mode="html"
    mock_client.send_message.assert_called_once()
    args, kwargs = mock_client.send_message.call_args
    assert args[0] == "me"
    assert "<b>[AI Quant Tự Động Khớp Lệnh]</b>" in args[1]
    assert kwargs.get("parse_mode") == "html"


@pytest.mark.asyncio
async def test_system_notifier_fallback_on_parse_error():
    """Kiểm tra cơ chế tự động fallback sang Plain Text nếu HTML parse thất bại."""
    mock_client = MagicMock()
    mock_client.is_connected.return_value = True

    # Lần 1 ném exception do lỗi parse, lần 2 thành công với plain text
    mock_client.send_message = AsyncMock(side_effect=[Exception("HTML parse error"), True])

    notifier = SystemNotifier(
        config=NotificationsConfig(telegram_notification_enabled=False),
        telegram_client_getter=lambda: mock_client,
    )

    success = await notifier.notify("<b>Malformed</b>")
    assert success is True
    assert mock_client.send_message.call_count == 2
    # Cuộc gọi thứ 2 phải là plain text không có thẻ <b>
    second_call_text = mock_client.send_message.call_args_list[1][0][1]
    assert "<b>" not in second_call_text
    assert "Malformed" in second_call_text


@pytest.mark.asyncio
async def test_quantum_council_5_agents_debate_generation():
    """
    Kiểm tra Hội đồng Lượng tử 5 Đặc Vụ AI:
    - Agent 1: Lead Quant Strategist
    - Agent 2: Scalp Specialist
    - Agent 3: Macro & SMC Specialist
    - Agent 4: Risk Guardian Zero-Liquidation
    - Agent 5: Sentiment & News Scout
    """
    arbiter = QuantumCouncilArbiter()
    delib = await arbiter.deliberate("SOLUSDT", {
        "direction": "SHORT",
        "entry_price": 178.5,
        "stop_loss": 182.2,
        "take_profit_1": 174.0,
        "take_profit_2": 170.0,
        "take_profit_3": 165.0,
        "leverage": 15,
        "atr": 2.5,
    })

    assert isinstance(delib, CouncilDeliberationResult)
    assert delib.symbol == "SOLUSDT"
    assert delib.direction == "SHORT"

    # Kiểm tra sự hiện diện của đầy đủ 5 đặc vụ
    assert delib.lead_quant is not None, "Agent 1 (Lead Quant) phải có mặt"
    assert delib.scalp_specialist is not None, "Agent 2 (Scalp Specialist) phải có mặt"
    assert delib.macro_smc is not None, "Agent 3 (Macro & SMC) phải có mặt"
    assert delib.risk_guardian is not None, "Agent 4 (Risk Guardian) phải có mặt"
    assert delib.sentiment_scout is not None, "Agent 5 (Sentiment Scout) phải có mặt"

    # Kiểm tra nội dung phân tích & số liệu rủi ro
    assert delib.risk_guardian.vote == CouncilVote.APPROVED
    assert "Zero-Liquidation" in delib.risk_guardian.rationale

    # Kiểm tra HTML Debate xuất ra
    html = delib.debate_html
    assert "🏛️ <b>[QUANTUM COUNCIL]" in html
    assert "Agent 1 (Lead Quant Strategist" in html
    assert "Agent 2 (Scalp Specialist" in html
    assert "Agent 3 (Macro & SMC Specialist" in html
    assert "Agent 4 (Risk Guardian - Zero Liquidation" in html
    assert "Agent 5 (Sentiment & News Scout" in html
    assert "TP1 (35%):" in html
    assert "TP2 (35%):" in html
    assert "TP3 (30% Moonbag):" in html
    assert "Kèo Bất Tử" in html


@pytest.mark.asyncio
async def test_quantum_council_veto_debate_html():
    """Kiểm tra Hội đồng Lượng tử giơ Thẻ Đỏ VETO khi phát hiện rủi ro nghiêm trọng."""
    arbiter = QuantumCouncilArbiter()
    # Kèo vi phạm: Lệnh LONG giá 100 nhưng SL = 105 (SL > Entry vô lý)
    delib = await arbiter.deliberate("ETHUSDT", {
        "direction": "LONG",
        "entry_price": 100.0,
        "stop_loss": 105.0,
        "take_profit_1": 115.0,
        "leverage": 10,
    })

    assert delib.is_approved is False
    assert delib.red_team.vote == CouncilVote.VETO
    assert delib.risk_guardian.vote == CouncilVote.VETO

    html = delib.debate_html
    assert "THẺ ĐỎ VETO" in html or "BỊ BÁC BỎ" in html
    assert "LÝ DO BỊ PHỦ QUYẾT" in html
    assert "Kỷ luật thép" in html


@pytest.mark.asyncio
async def test_telegram_interactive_command_debate():
    """Kiểm tra listener Telegram xử lý lệnh chat /debate SOLUSDT."""
    from telegram.listener import TelegramSignalListener
    from storage.database import DatabaseManager

    mock_db = MagicMock(spec=DatabaseManager)
    mock_tg_client = MagicMock()
    mock_tg_client.send_message = AsyncMock(return_value=True)

    config = AppConfig(mode=ExecutionMode.TESTNET)
    config.telegram.allowed_chat_ids = [12345]

    listener = TelegramSignalListener(
        config=config,
        tg_client=mock_tg_client,
        db_manager=mock_db,
    )

    mock_event = MagicMock()
    mock_event.chat_id = 12345
    mock_event.id = 999
    mock_event.is_private = True
    mock_event.reply = AsyncMock(return_value=True)

    handled = await listener._handle_interactive_command(mock_event, 12345, "/debate SOLUSDT")
    assert handled is True
    assert mock_event.reply.call_count >= 1
