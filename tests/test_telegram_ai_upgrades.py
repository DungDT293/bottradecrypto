"""
tests/test_telegram_ai_upgrades.py
=============================================================================
Tests for upgraded Telegram Bot capabilities:
- Gemini Key Pool 5-key rotation in dedicated bot
- AI Open Positions Audit (_cmd_ai_audit_positions)
- Potential Setups Scanner Radar (_cmd_jarvis_scan)
- Conversational Jarvis Q&A (_cmd_ask & natural chat)
=============================================================================
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from config.config import AppConfig
from telegram.dedicated_bot import DedicatedTelegramBot, get_main_reply_keyboard, get_main_inline_keyboard


@pytest.fixture
def mock_config():
    cfg = AppConfig()
    cfg.notifications.notification_bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    cfg.notifications.notification_chat_id = "7031661467"
    return cfg


@pytest.mark.asyncio
async def test_keyboards_include_new_gemini_ai_options(mock_config):
    reply_kb = get_main_reply_keyboard()
    reply_texts = [btn["text"] for row in reply_kb["keyboard"] for btn in row]
    assert "🧠 AI Đánh Giá Vị Thế" in reply_texts
    assert "🎯 Quét Kèo Tiềm Năng" in reply_texts
    assert "💬 Hỏi Trợ Lý Jarvis (/ask)" in reply_texts

    inline_kb = get_main_inline_keyboard()
    callbacks = [btn["callback_data"] for row in inline_kb["inline_keyboard"] for btn in row]
    assert "nav_ai_audit" in callbacks
    assert "nav_scan" in callbacks
    assert "nav_ask" in callbacks


@pytest.mark.asyncio
async def test_cmd_ai_audit_positions_no_positions(mock_config):
    bot = DedicatedTelegramBot(config=mock_config)
    bot.send_message = AsyncMock(return_value=True)

    with patch("exchange.binance_client.BinanceFuturesClient.get_open_positions", new_callable=AsyncMock) as mock_get_pos, \
         patch("exchange.binance_client.BinanceFuturesClient.get_open_algo_orders", new_callable=AsyncMock) as mock_get_algo, \
         patch("exchange.binance_client.BinanceFuturesClient.get_open_orders", new_callable=AsyncMock) as mock_get_open:
        mock_get_pos.return_value = []
        mock_get_algo.return_value = []
        mock_get_open.return_value = []

        await bot._cmd_ai_audit_positions(chat_id=7031661467)

        bot.send_message.assert_called_once()
        args, kwargs = bot.send_message.call_args
        assert "ZERO OPEN POSITIONS" in args[1]
        assert "100% tài sản đang ở trạng thái tiền mặt" in args[1]


@pytest.mark.asyncio
async def test_cmd_ai_audit_positions_with_positions(mock_config):
    bot = DedicatedTelegramBot(config=mock_config)
    bot.send_message = AsyncMock(return_value=True)

    fake_positions = [
        {
            "symbol": "BTCUSDT",
            "positionAmt": "0.01",
            "entryPrice": "80000.0",
            "markPrice": "80200.0",
            "unRealizedProfit": "2.0",
            "leverage": "35",
            "marginType": "cross",
        }
    ]

    mock_gemini_resp = {
        "positions": [
            {
                "symbol": "BTCUSDT",
                "health": "STRONG",
                "action": "HOLD",
                "action_label": "Tiếp Tục Gồng",
                "key_defense": "Kháng cự 81,500 / SL hòa vốn",
                "rationale": "Cấu trúc nến 1H tôn trọng EMA20, áp lực mua duy trì tốt.",
            }
        ],
        "portfolio_risk_verdict": "Danh mục an toàn, tỷ lệ ký quỹ thấp.",
    }

    with patch("exchange.binance_client.BinanceFuturesClient.get_open_positions", new_callable=AsyncMock) as mock_get_pos, \
         patch("exchange.binance_client.BinanceFuturesClient.get_open_algo_orders", new_callable=AsyncMock) as mock_get_algo, \
         patch("exchange.binance_client.BinanceFuturesClient.get_open_orders", new_callable=AsyncMock) as mock_get_open, \
         patch.object(bot, "_query_gemini_ai", new_callable=AsyncMock) as mock_ai:

        mock_get_pos.return_value = fake_positions
        mock_get_algo.return_value = []
        mock_get_open.return_value = []
        mock_ai.return_value = mock_gemini_resp

        await bot._cmd_ai_audit_positions(chat_id=7031661467)

        # 2 messages sent: 1 waiting notice, 1 full report
        assert bot.send_message.call_count == 2
        last_msg = bot.send_message.call_args[0][1]
        assert "THẨM ĐỊNH VỊ THẾ BẰNG GEMINI AI" in last_msg
        assert "BTCUSDT" in last_msg
        assert "KHỎE MẠNH (THUẬN TREND)" in last_msg
        assert "Tiếp Tục Gồng" in last_msg
        assert "Danh mục an toàn" in last_msg


@pytest.mark.asyncio
async def test_cmd_jarvis_scan_with_gemini(mock_config):
    bot = DedicatedTelegramBot(config=mock_config)
    bot.send_message = AsyncMock(return_value=True)

    mock_scan_ai = {
        "radar_summary": "Dòng tiền tập trung quanh nhóm layer 1.",
        "setups": [
            {
                "symbol": "SOLUSDT",
                "side": "LONG",
                "confidence": 88,
                "risk_reward": "2.5:1",
                "entry_zone": "178.5 - 179.0",
                "stop_loss": "176.5",
                "take_profit_1": "182.5",
                "take_profit_2": "185.0",
                "take_profit_3": "189.0",
                "thesis": "RSI 1H phân kỳ ẩn tại hỗ trợ EMA50.",
            }
        ],
    }

    with patch.object(bot, "_query_gemini_ai", new_callable=AsyncMock) as mock_ai:
        mock_ai.return_value = mock_scan_ai

        await bot._cmd_jarvis_scan(chat_id=7031661467)

        assert bot.send_message.call_count >= 2
        final_call = bot.send_message.call_args[0][1]
        assert "KÈO TIỀM NĂNG GEMINI AI" in final_call
        assert "SOLUSDT" in final_call
        assert "LONG (R:R 2.5:1)" in final_call
        assert "88%" in final_call


@pytest.mark.asyncio
async def test_cmd_ask_conversational_response(mock_config):
    bot = DedicatedTelegramBot(config=mock_config)
    bot.send_message = AsyncMock(return_value=True)

    with patch.object(bot, "_query_gemini_ai", new_callable=AsyncMock) as mock_ai, \
         patch("exchange.binance_client.BinanceFuturesClient.get_open_positions", new_callable=AsyncMock) as mock_pos, \
         patch("exchange.binance_client.BinanceFuturesClient.get_market_trend_context", new_callable=AsyncMock) as mock_btc, \
         patch("services.market_sentiment_news_guardian.MarketSentimentNewsGuardian.fetch_macro_crypto_headlines", new_callable=AsyncMock) as mock_news:
        mock_pos.return_value = []
        mock_btc.return_value = {"last_close": 80100.0, "change_24h": 0.5}
        mock_news.return_value = ["[Binance] BTC options update"]
        mock_ai.return_value = "Thưa Ngài Leon, xu hướng Bitcoin trên khung 4H vẫn duy trì cấu trúc tích lũy đi ngang trên mốc $79,500. Ngài nên kiên nhẫn quan sát trước khi mở thêm vị thế mới."

        await bot._cmd_ask(chat_id=7031661467, query="BTC có vượt 81k được không?")

        assert bot.send_message.call_count == 2
        final_call = bot.send_message.call_args[0][1]
        assert "QUANTUM JARVIS MARK 85 - CỐ VẤN TRỰC TUYẾN" in final_call
        assert "Thưa Ngài Leon" in final_call
        assert "79,500" in final_call


@pytest.mark.asyncio
async def test_handle_natural_chat_routes_to_ai_audit_and_ask(mock_config):
    bot = DedicatedTelegramBot(config=mock_config)
    bot._cmd_ai_audit_positions = AsyncMock()
    bot._cmd_jarvis_scan = AsyncMock()
    bot._cmd_ask = AsyncMock()

    # 1. Routing to AI Audit
    await bot._handle_natural_chat(chat_id=7031661467, text="Jarvis đánh giá vị thế giúp tôi")
    bot._cmd_ai_audit_positions.assert_called_once()

    # 2. Routing to Radar Scan
    await bot._handle_natural_chat(chat_id=7031661467, text="có kèo tiềm năng nào không")
    bot._cmd_jarvis_scan.assert_called_once()

    # 3. Routing general question to Gemini Ask
    await bot._handle_natural_chat(chat_id=7031661467, text="Theo mày thì tối nay thị trường chạy thế nào?")
    bot._cmd_ask.assert_called_once_with(7031661467, "Theo mày thì tối nay thị trường chạy thế nào?", None)
