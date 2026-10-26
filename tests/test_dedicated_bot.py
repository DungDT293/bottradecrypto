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
    assert any("JARVIS" in str(c[0][1]) or "QUANTUM" in str(c[0][1]) for c in bot.send_message.call_args_list)

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

    # 4. User sends /debate <BTC> with angle brackets
    bot.send_message.reset_mock()
    with patch("services.quantum_council_harness.QuantumCouncilArbiter.deliberate", new_callable=AsyncMock) as mock_delib:
        mock_delib.return_value = MagicMock(debate_html="<b>BTC DEBATE</b>")
        with patch("services.quantum_ai_engine.QuantumAIEngine.get_market_kline_analysis", new_callable=AsyncMock) as mock_kline:
            mock_kline.return_value = {"symbol": "BTCUSDT", "current_price": 68000.0, "ema20": 67800.0, "ema50": 67500.0}
            update_btc = {
                "update_id": 103,
                "message": {
                    "message_id": 4,
                    "chat": {"id": 123456},
                    "text": "/debate <BTC>"
                }
            }
            await bot.handle_update(update_btc)
            assert bot.send_message.called
            assert "BTCUSDT" in bot.send_message.call_args_list[0][0][1]

    # 5. /positions with live Binance Futures camelCase schema
    bot.send_message.reset_mock()
    with patch("exchange.binance_client.BinanceFuturesClient.get_open_positions", new_callable=AsyncMock) as mock_pos:
        mock_pos.return_value = [
            {
                "symbol": "SOLUSDT",
                "positionAmt": "-2.54",
                "entryPrice": "100.10",
                "markPrice": "100.73",
                "unRealizedProfit": "-1.60",
                "leverage": "30",
                "marginType": "cross"
            }
        ]
        with patch("exchange.binance_client.BinanceFuturesClient.get_open_algo_orders", new_callable=AsyncMock) as mock_algo:
            mock_algo.return_value = [
                {
                    "symbol": "SOLUSDT",
                    "orderType": "STOP_MARKET",
                    "triggerPrice": "101.84",
                    "algoStatus": "NEW"
                }
            ]
            with patch("exchange.binance_client.BinanceFuturesClient.get_open_orders", new_callable=AsyncMock) as mock_open:
                mock_open.return_value = []
                update_pos = {
                    "update_id": 104,
                    "message": {
                        "message_id": 5,
                        "chat": {"id": 123456},
                        "text": "/positions"
                    }
                }
                await bot.handle_update(update_pos)
                assert bot.send_message.called
                pos_output = bot.send_message.call_args[0][1]
                assert "SOLUSDT" in pos_output
                assert "SHORT 30x" in pos_output
                assert "100.1" in pos_output
                assert "100.73" in pos_output
                assert "-1.60 USDT" in pos_output
                assert "101.84" in pos_output
