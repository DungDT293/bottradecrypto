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


@pytest.mark.asyncio
async def test_dedicated_bot_remote_actions():
    from decimal import Decimal
    from exchange.exchange_info import SymbolFilterInfo
    from core.enums import ExecutionMode

    bot = DedicatedTelegramBot(bot_token="123456789:ABCdefGHIjkLMNopqrstuvwxyz")
    bot.config.mode = ExecutionMode.LIVE
    bot.config.live_trading_enabled = True
    bot.send_message = AsyncMock(return_value=True)

    # 1. Close single position via callback act_cls_SOLUSDT is strictly rejected by Safety Notice
    update_cls = {
        "update_id": 201,
        "callback_query": {
            "id": "cb_cls_1",
            "from": {"id": 123456},
            "data": "act_cls_SOLUSDT",
            "message": {"chat": {"id": 123456}}
        }
    }
    await bot.handle_update(update_cls)
    assert any("CHẾ ĐỘ GIÁM SÁT AN TOÀN" in str(c) for c in bot.send_message.call_args_list)

    # 2. Move SL to Break-Even via callback act_be_SOLUSDT is strictly rejected by Safety Notice
    bot.send_message.reset_mock()
    update_be = {
        "update_id": 202,
        "callback_query": {
            "id": "cb_be_1",
            "from": {"id": 123456},
            "data": "act_be_SOLUSDT",
            "message": {"chat": {"id": 123456}}
        }
    }
    await bot.handle_update(update_be)
    assert any("CHẾ ĐỘ GIÁM SÁT AN TOÀN" in str(c) for c in bot.send_message.call_args_list)

    # 3. Toggle Ferrari Mode via callback act_toggle_ferrari informs user it's centrally managed on Desktop
    bot.send_message.reset_mock()
    update_ferrari = {
        "update_id": 203,
        "callback_query": {
            "id": "cb_ferrari_1",
            "from": {"id": 123456},
            "data": "act_toggle_ferrari",
            "message": {"chat": {"id": 123456}}
        }
    }
    await bot.handle_update(update_ferrari)
    assert any("CẤU HÌNH ĐƯỢC QUẢN LÝ TẬP TRUNG TRÊN DESKTOP" in str(c) for c in bot.send_message.call_args_list)

    # 4. Margin Health via /margin
    bot.send_message.reset_mock()
    with patch("exchange.binance_client.BinanceFuturesClient._request", new_callable=AsyncMock) as mock_req, \
         patch("exchange.binance_client.BinanceFuturesClient.get_open_positions", new_callable=AsyncMock) as mock_open_pos, \
         patch("exchange.binance_client.BinanceFuturesClient.close", new_callable=AsyncMock):

        mock_req.return_value = {
            "totalWalletBalance": "100.50",
            "totalMarginBalance": "100.50",
            "availableBalance": "75.20",
            "totalMaintMargin": "2.10",
            "totalPositionInitialMargin": "25.30"
        }
        mock_open_pos.return_value = [
            {"symbol": "SOLUSDT", "positionAmt": "-2.54", "markPrice": "100.5", "liquidationPrice": "130.0"}
        ]

        update_margin = {
            "update_id": 204,
            "message": {
                "message_id": 10,
                "chat": {"id": 123456},
                "text": "/margin"
            }
        }
        await bot.handle_update(update_margin)
        assert any("SỨC KHỎE KÝ QUỸ" in str(c) for c in bot.send_message.call_args_list)

    # 5. Ping via /ping
    bot.send_message.reset_mock()
    with patch("exchange.binance_client.BinanceFuturesClient.sync_time", new_callable=AsyncMock), \
         patch("exchange.binance_client.BinanceFuturesClient.close", new_callable=AsyncMock):

        update_ping = {
            "update_id": 205,
            "message": {
                "message_id": 11,
                "chat": {"id": 123456},
                "text": "/ping"
            }
        }
        await bot.handle_update(update_ping)
        assert any("JARVIS TELEMETRY" in str(c) for c in bot.send_message.call_args_list)


@pytest.mark.asyncio
async def test_dedicated_bot_natural_language_chat():
    from core.enums import ExecutionMode

    bot = DedicatedTelegramBot(bot_token="123456789:ABCdefGHIjkLMNopqrstuvwxyz")
    bot.config.mode = ExecutionMode.LIVE
    bot.config.live_trading_enabled = True
    bot.send_message = AsyncMock(return_value=True)

    # 1. Natural chat "đóng sol"
    with patch.object(bot, "_action_close_position", new_callable=AsyncMock) as mock_cls:
        update_chat = {
            "update_id": 301,
            "message": {
                "message_id": 20,
                "chat": {"id": 123456},
                "text": "đóng sol"
            }
        }
        await bot.handle_update(update_chat)
        assert mock_cls.called
        assert mock_cls.call_args[0][1] == "SOLUSDT"

    # 2. Natural chat "bật ferrari"
    with patch.object(bot, "_action_toggle_ferrari", new_callable=AsyncMock) as mock_ferrari:
        update_ferrari = {
            "update_id": 302,
            "message": {
                "message_id": 21,
                "chat": {"id": 123456},
                "text": "bật ferrari giúp tôi"
            }
        }
        await bot.handle_update(update_ferrari)
        assert mock_ferrari.called

    # 3. Natural chat "ký quỹ của tôi thế nào"
    with patch.object(bot, "_cmd_margin_health", new_callable=AsyncMock) as mock_margin:
        update_margin = {
            "update_id": 303,
            "message": {
                "message_id": 22,
                "chat": {"id": 123456},
                "text": "ký quỹ của tôi thế nào"
            }
        }
        await bot.handle_update(update_margin)
        assert mock_margin.called

    # 4. Natural chat "thị trường sao rồi jarvis"
    with patch.object(bot, "_cmd_macro", new_callable=AsyncMock) as mock_macro:
        update_macro = {
            "update_id": 304,
            "message": {
                "message_id": 23,
                "chat": {"id": 123456},
                "text": "thị trường sao rồi jarvis"
            }
        }
        await bot.handle_update(update_macro)
        assert mock_macro.called


@pytest.mark.asyncio
async def test_notify_early_cut():
    bot = DedicatedTelegramBot(bot_token="123456789:ABCdefGHIjkLMNopqrstuvwxyz")
    bot.broadcast = AsyncMock(return_value=1)

    res = await bot.notify_early_cut(
        symbol="SOLUSDT",
        exit_price=101.5,
        loss_pct=-0.85,
        loss_usdt=0.35,
        root_cause="Nến 1H đóng vượt cản EMA50 với RSI=62.4",
    )
    assert res == 1
    assert bot.broadcast.called
    msg_sent = bot.broadcast.call_args[0][0]
    assert "CẮT LỖ SỚM CHỦ ĐỘNG" in msg_sent
    assert "SOLUSDT" in msg_sent
    assert "EMA50" in msg_sent
