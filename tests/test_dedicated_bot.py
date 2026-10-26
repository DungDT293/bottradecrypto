import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram.dedicated_bot import DedicatedTelegramBot


@pytest.mark.asyncio
async def test_dedicated_bot_configuration():
    bot = DedicatedTelegramBot(bot_token="123456789:ABCdefGHIjkLMNopqrstuvwxyz")
    assert bot.is_configured is True
    assert bot.token == "123456789:ABCdefGHIjkLMNopqrstuvwxyz"

    bot_unconfigured = DedicatedTelegramBot(bot_token="")
    assert bot_unconfigured.is_configured is False


@pytest.mark.asyncio
async def test_dedicated_bot_handle_update_commands():
    bot = DedicatedTelegramBot(bot_token="123456789:ABCdefGHIjkLMNopqrstuvwxyz")
    bot.send_message = AsyncMock(return_value=True)

    # 1. /start command
    update_start = {
        "update_id": 100,
        "message": {
            "message_id": 1,
            "chat": {"id": 123456},
            "text": "/start"
        }
    }
    await bot.handle_update(update_start)
    assert 123456 in bot.authorized_chat_ids
    assert bot.send_message.called
    assert "QUANTUM AI COUNCIL" in bot.send_message.call_args[0][1]

    # 2. Command with accidental HTML tags like <b>/status</b>
    bot.send_message.reset_mock()
    update_html_status = {
        "update_id": 101,
        "message": {
            "message_id": 2,
            "chat": {"id": 123456},
            "text": "<b>/status</b>"
        }
    }
    await bot.handle_update(update_html_status)
    assert bot.send_message.called
    assert "TRẠNG THÁI HỆ THỐNG" in bot.send_message.call_args[0][1]

    # 3. Accidental HTML /debate SOLUSDT
    bot.send_message.reset_mock()
    with patch("services.quantum_council_harness.QuantumCouncilArbiter.deliberate", new_callable=AsyncMock) as mock_delib:
        mock_delib.return_value = MagicMock(debate_html="<b>DELIBERATION PASS</b>")
        with patch("exchange.binance_client.BinanceFuturesClient.get_symbol_price", new_callable=AsyncMock) as mock_price:
            mock_price.return_value = "100.5"
            update_debate = {
                "update_id": 102,
                "message": {
                    "message_id": 3,
                    "chat": {"id": 123456},
                    "text": "<b>/debate SOLUSDT</b>"
                }
            }
            await bot.handle_update(update_debate)
            assert bot.send_message.called

