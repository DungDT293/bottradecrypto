"""
telegram/dedicated_bot.py
=============================================================================
DEDICATED TELEGRAM BOT FOR QUANTUM COUNCIL AI DEBATE & TRADING TELEMETRY
=============================================================================
Cung cấp một Telegram Bot độc lập chuyên biệt (Dedicated Bot):
- Tương tác chat 2 chiều cực mượt qua Telegram Bot API (không cần session cá nhân).
- Xem 5 Đặc Vụ AI Hội Đồng Lượng Tử đối chất trực tiếp qua lệnh: /debate <symbol>
- Tra cứu vị thế đang mở thời gian thực: /positions
- Báo cáo PnL Hôm nay & 7 ngày chuẩn sàn Binance: /pnl
- Trạng thái hệ thống, Ferrari Mode & bảo vệ Zero-Liquidation: /status
- Tự động phát sóng biên bản tranh luận khi bot vào lệnh mới.
=============================================================================
"""

import asyncio
import logging
import os
import re
import sys
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set

import aiohttp

from config.config import AppConfig, load_config
from telegram.telegram_notifier import sanitize_telegram_html, ensure_closed_tags

logger = logging.getLogger("dedicated_bot")


class DedicatedTelegramBot:
    """
    Dedicated Telegram Bot Runner using standard Telegram Bot API long-polling.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        config: Optional[AppConfig] = None,
        authorized_chat_ids: Optional[Set[int]] = None,
    ):
        self.config = config or load_config()
        if bot_token is not None:
            self.token = bot_token
        else:
            self.token = (
                getattr(getattr(self.config, "notifications", None), "notification_bot_token", None)
                or os.environ.get("TELEGRAM_BOT_TOKEN")
            )
        self.authorized_chat_ids: Set[int] = set(authorized_chat_ids or [])
        cfg_chat = getattr(getattr(self.config, "notifications", None), "notification_chat_id", None)
        if cfg_chat:
            try:
                self.authorized_chat_ids.add(int(cfg_chat))
            except Exception:
                pass

        self._running = False
        self._last_update_id = 0
        self._session: Optional[aiohttp.ClientSession] = None
        self._bot_info: Dict[str, Any] = {}

    @property
    def is_configured(self) -> bool:
        return bool(self.token and len(self.token.strip()) > 10 and ":" in self.token)

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45))
        return self._session

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str = "HTML",
        reply_to_message_id: Optional[int] = None,
    ) -> bool:
        """Gửi tin nhắn định dạng chuẩn HTML qua Telegram Bot API."""
        if not self.is_configured:
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        safe_html = ensure_closed_tags(sanitize_telegram_html(text))

        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": safe_html,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id

        try:
            session = await self.get_session()
            async with session.post(url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    return True
                # If HTML parsing fails, fallback to plain text
                err_body = await resp.text()
                logger.debug(f"HTML send failed ({resp.status}): {err_body}, falling back to plain text")
                clean_text = re.sub(r"<[^>]+>", "", text)
                payload["text"] = clean_text
                payload.pop("parse_mode", None)
                async with session.post(url, json=payload, timeout=10) as resp2:
                    return resp2.status == 200
        except Exception as e:
            logger.debug(f"Dedicated bot send_message error: {e}")
            return False

    async def broadcast(self, text: str) -> int:
        """Phát sóng thông điệp tới tất cả các chat_id đã kết nối."""
        sent_count = 0
        for cid in list(self.authorized_chat_ids):
            if await self.send_message(cid, text):
                sent_count += 1
        return sent_count

    async def handle_update(self, update: Dict[str, Any]) -> None:
        """Xử lý từng tin nhắn đến từ người dùng."""
        msg = update.get("message") or update.get("channel_post")
        if not msg:
            return

        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        if not chat_id:
            return

        # Tự động ghi nhớ chat_id của người dùng để nhận thông báo tự động
        self.authorized_chat_ids.add(chat_id)
        if getattr(self.config, "notifications", None) and not getattr(self.config.notifications, "notification_chat_id", None):
            try:
                from config.config import save_config
                self.config.notifications.notification_chat_id = chat_id
                save_config(self.config)
            except Exception:
                pass

        raw_text = msg.get("text", "") or ""
        # Chỉ loại bỏ thẻ HTML Telegram hợp lệ (<b>, </b>, <i>...), KHÔNG xóa <coin> hay <BTC> của user!
        from telegram.telegram_notifier import VALID_TG_TAG_PATTERN
        clean_text = re.sub(VALID_TG_TAG_PATTERN, "", raw_text, flags=re.IGNORECASE).replace("`", "").strip()
        if not clean_text:
            return

        parts = clean_text.split()
        cmd = parts[0].lower() if parts else ""

        # Gỡ bỏ @botname nếu có (VD: /debate@MyBot SOLUSDT -> /debate)
        if "@" in cmd:
            cmd = cmd.split("@")[0]

        msg_id = msg.get("message_id")

        if cmd in ("/start", "/help"):
            await self._cmd_help(chat_id, msg_id)
        elif cmd in ("/debate", "/council"):
            arg = parts[1] if len(parts) > 1 else ""
            await self._cmd_debate(chat_id, arg, msg_id)
        elif cmd in ("/positions", "/position", "/pos"):
            await self._cmd_positions(chat_id, msg_id)
        elif cmd in ("/pnl", "/profit", "/stats"):
            await self._cmd_pnl(chat_id, msg_id)
        elif cmd in ("/status", "/regime", "/info"):
            await self._cmd_status(chat_id, msg_id)
        else:
            if clean_text.startswith("/"):
                await self.send_message(
                    chat_id,
                    "⚠️ <i>Lệnh không hợp lệ. Gõ <code>/help</code> để xem danh sách lệnh!</i>",
                    reply_to_message_id=msg_id,
                )

    async def _cmd_help(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        text = (
            "🏛️ <b>CHÀO MỪNG BẠN ĐẾN VỚI QUANTUM AI COUNCIL TRADING BOT!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Hệ thống Định Lượng Đa Tác Tử (5 AI Agents) giám sát thị trường Binance Futures 24/7 "
            "kết hợp kỷ luật <b>Zero-Liquidation &amp; Kèo Bất Tử</b>.\n\n"
            "⚡ <b>DANH SÁCH LỆNH ĐIỀU KHIỂN &amp; TRA CỨU:</b>\n"
            "• <code>/debate &lt;coin&gt;</code> - Triệu tập 5 đặc vụ AI đối chất &amp; thẩm định kèo (VD: <code>/debate SOLUSDT</code> hoặc <code>/debate BTC</code>)\n"
            "• <code>/positions</code> - Xem trực tiếp các vị thế đang mở trên Binance Futures\n"
            "• <code>/pnl</code> - Xem báo cáo Lãi/Lỗ ròng (Net PnL) và Win Rate hôm nay &amp; 7 ngày\n"
            "• <code>/status</code> - Xem trạng thái hệ thống, Ferrari Mode &amp; BTC Panic Regime\n"
            "• <code>/help</code> - Xem lại bảng hướng dẫn này\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>💡 Mẹo: Khi hệ thống tự động khớp lệnh trên sàn, toàn bộ biên bản tranh luận "
            "của 5 đặc vụ AI sẽ được tự động gửi trực tiếp vào đây!</i>"
        )
        await self.send_message(chat_id, text, reply_to_message_id=reply_to_id)

    async def _cmd_debate(self, chat_id: int, raw_symbol: str, reply_to_id: Optional[int] = None) -> None:
        sym = raw_symbol.upper().replace("<", "").replace(">", "").replace("/", "").replace(":", "").strip()
        if not sym or sym in ("COIN", "SYMBOL", "CAP", "ARG"):
            sym = "SOLUSDT"
        elif not sym.endswith("USDT") and not sym.endswith("USDC"):
            sym = f"{sym}USDT"

        await self.send_message(
            chat_id,
            f"🏛️ <i>Đang triệu tập khẩn cấp Hội Đồng Lượng Tử AI để thẩm định &amp; đối chất cặp <b>{sym}</b>...</i>",
            reply_to_message_id=reply_to_id,
        )

        try:
            from services.quantum_council_harness import QuantumCouncilArbiter
            from exchange.binance_client import BinanceFuturesClient
            from services.quantum_ai_engine import QuantumAIEngine

            client = BinanceFuturesClient(self.config)
            engine = QuantumAIEngine(config=self.config, binance_client=client)
            market_data = await engine.get_market_kline_analysis(sym)
            if not market_data:
                market_data = {"symbol": sym}
                px = await client.get_symbol_price(sym)
                if px and float(px) > 0:
                    market_data["current_price"] = float(px)

            arbiter = QuantumCouncilArbiter(config=self.config, binance_client=client)
            deliberation = await arbiter.deliberate(sym, market_data)
            debate_html = getattr(deliberation, "debate_html", "") or arbiter.format_telegram_transcript(deliberation)

            await self.send_message(chat_id, debate_html)
            await client.close()
        except Exception as e:
            logger.error(f"Error in debate command: {e}", exc_info=True)
            await self.send_message(
                chat_id,
                f"❌ <i>Lỗi trong quá trình thẩm định {sym}: {e}</i>",
                reply_to_message_id=reply_to_id,
            )

    async def _cmd_positions(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        try:
            from exchange.binance_client import BinanceFuturesClient

            client = BinanceFuturesClient(self.config)
            positions = await client.get_open_positions()
            algo_orders = await client.get_open_algo_orders()
            open_orders = await client.get_open_orders()
            await client.close()

            if not positions:
                await self.send_message(
                    chat_id,
                    "📊 <b>VỊ THẾ ĐANG MỞ (BINANCE FUTURES)</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "<i>Hiện tại không có vị thế nào đang mở. Toàn bộ vốn an toàn 100%.</i>",
                    reply_to_message_id=reply_to_id,
                )
                return

            total_upnl = Decimal("0.0")
            lines = [
                f"📊 <b>VỊ THẾ ĐANG MỞ TRÊN SÀN ({len(positions)} Vị thế)</b>",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            ]

            for p in positions:
                sym = p.get("symbol", "")
                amt_str = p.get("positionAmt", p.get("contracts", p.get("amount", "0")))
                amt = float(amt_str)
                side = "SHORT" if amt < 0 else "LONG"
                entry_p = float(p.get("entryPrice") or p.get("entry_price") or 0.0)
                mark_p = float(p.get("markPrice") or p.get("mark_price") or 0.0)
                unpnl = float(p.get("unRealizedProfit") or p.get("unrealized_pnl") or 0.0)
                lev = int(p.get("leverage") or 20)
                margin_type = str(p.get("marginType", "cross")).upper()
                notional = abs(amt * mark_p)
                margin = (notional / lev) if lev > 0 else 0.0
                roe_pct = (unpnl / margin * 100) if margin > 0 else 0.0
                total_upnl += Decimal(str(unpnl))

                pnl_emoji = "🟢" if unpnl >= 0 else "🔴"
                pnl_sign = "+" if unpnl >= 0 else ""

                # Check SL from algo orders or open orders
                sl_price = None
                for o in (algo_orders or []):
                    if str(o.get("symbol", "")).upper() == sym.upper():
                        ot = str(o.get("orderType", o.get("order_type", ""))).upper()
                        if "STOP" in ot:
                            sl_price = float(o.get("triggerPrice", o.get("trigger_price", 0)))
                            break
                if not sl_price:
                    for o in (open_orders or []):
                        if str(o.get("symbol", "")).upper() == sym.upper():
                            ot = str(o.get("type", o.get("order_type", ""))).upper()
                            if "STOP" in ot:
                                sl_price = float(o.get("stopPrice", o.get("price", 0)))
                                break

                sl_badge = f"🛡️ Đã cài SL: {sl_price}" if sl_price else "⚠️ CHƯA CÓ SL"

                lines.append(
                    f"• <b>{sym}</b> | <code>{side} {lev}x ({margin_type})</code>\n"
                    f"  Entry: <code>{entry_p}</code> ➔ Mark: <code>{mark_p}</code>\n"
                    f"  PnL: {pnl_emoji} <b>{pnl_sign}{unpnl:.2f} USDT ({pnl_sign}{roe_pct:.1f}% ROE)</b>\n"
                    f"  Ký quỹ: <code>{margin:.2f} USDT</code> ({abs(amt):g} coin)\n"
                    f"  Bảo vệ: <b>{sl_badge}</b>\n"
                )

            upnl_emoji = "🟢" if total_upnl >= Decimal("0") else "🔴"
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"💰 <b>Tổng Unrealized PnL:</b> {upnl_emoji} <b>{total_upnl:+.2f} USDT</b>")

            await self.send_message(chat_id, "\n".join(lines), reply_to_message_id=reply_to_id)
        except Exception as e:
            await self.send_message(chat_id, f"❌ <i>Lỗi kiểm tra vị thế: {e}</i>", reply_to_message_id=reply_to_id)

            await self.send_message(chat_id, "\n".join(lines), reply_to_message_id=reply_to_id)
        except Exception as e:
            await self.send_message(chat_id, f"❌ <i>Lỗi kiểm tra vị thế: {e}</i>", reply_to_message_id=reply_to_id)

    async def _cmd_pnl(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        try:
            from storage.database import DatabaseManager
            from services.stats_service import StatsService

            db = DatabaseManager()
            stats_svc = StatsService(db, self.config)
            pnl_today = stats_svc.get_pnl_summary(0)
            pnl_7d = stats_svc.get_pnl_summary(6)

            today_net = float(pnl_today.get("net_pnl") or 0.0)
            today_realized = float(pnl_today.get("realized_pnl") or 0.0)
            today_wr = float(pnl_today.get("win_rate_pct") or 0.0)
            today_closed = int(pnl_today.get("total_closed_trades") or 0)
            today_wins = int(pnl_today.get("win_count") or 0)

            pnl7_net = float(pnl_7d.get("net_pnl") or 0.0)
            pnl7_realized = float(pnl_7d.get("realized_pnl") or 0.0)
            pnl7_comm = float(pnl_7d.get("commission") or 0.0)
            pnl7_fund = float(pnl_7d.get("funding_fee") or 0.0)
            pnl7_wr = float(pnl_7d.get("win_rate_pct") or 0.0)
            pnl7_closed = int(pnl_7d.get("total_closed_trades") or 0)

            text = (
                "📈 <b>BÁO CÁO LÃI/LỖ SÀN BINANCE FUTURES</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📅 <b>HÔM NAY:</b>\n"
                f"• Lãi ròng (Net PnL): <b>{today_net:+.2f} USDT</b>\n"
                f"• Realized PnL: <code>{today_realized:+.2f} USDT</code>\n"
                f"• Tỷ lệ thắng: <b>{today_wr:.1f}%</b> ({today_wins}/{today_closed} vị thế chốt)\n\n"
                "📊 <b>7 NGÀY GẦN NHẤT:</b>\n"
                f"• Lãi ròng (Net PnL): <b>{pnl7_net:+.2f} USDT</b>\n"
                f"• Realized PnL: <code>{pnl7_realized:+.2f} USDT</code>\n"
                f"• Phí hoa hồng sàn: <code>-{pnl7_comm:.2f} USDT</code>\n"
                f"• Funding Fee: <code>{pnl7_fund:+.2f} USDT</code>\n"
                f"• Tỷ lệ thắng 7d: <b>{pnl7_wr:.1f}%</b> ({pnl7_closed} vị thế đã đóng)\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🛡️ <i>Số liệu khớp 1:1 theo sao kê chính thức từ Binance Futures API.</i>"
            )
            await self.send_message(chat_id, text, reply_to_message_id=reply_to_id)
        except Exception as e:
            await self.send_message(chat_id, f"❌ <i>Lỗi kiểm tra PnL: {e}</i>", reply_to_message_id=reply_to_id)

    async def _cmd_status(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        try:
            mode = self.config.mode.value
            is_ferrari = bool(getattr(self.config, "ferrari_mode_enabled", False))
            ferrari_txt = "🟢 BẬT (x35 - x40, Tối đa 20 vị thế)" if is_ferrari else "⚪ TẮT (Chế độ an toàn 20x)"

            text = (
                "⚡ <b>TRẠNG THÁI HỆ THỐNG SIGNAL EXECUTOR v2.4.0</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• Chế độ giao dịch: <b>{mode} (TIỀN THẬT)</b>\n"
                f"• Ferrari Mode: <b>{ferrari_txt}</b>\n"
                "• Bảo vệ rủi ro: 🟢 <b>Zero-Liquidation Invariant (Bất biến)</b>\n"
                "• Kèo Bất Tử: 🟢 <b>Kích hoạt sớm (+0.8% Gain = +16% ROE)</b>\n"
                "• Bộ lọc vĩ mô 4H: 🟢 <b>4H Macro Trend Shield (Chặn ngược trend)</b>\n"
                "• Số lượng kênh tinh hoa: <b>7 Kênh đã duyệt</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "<i>Hệ thống trực tiếp đối soát lệnh SL/TP trên server Binance mỗi giây.</i>"
            )
            await self.send_message(chat_id, text, reply_to_message_id=reply_to_id)
        except Exception as e:
            await self.send_message(chat_id, f"❌ <i>Lỗi kiểm tra trạng thái: {e}</i>", reply_to_message_id=reply_to_id)

    async def run(self) -> None:
        """Vòng lặp Long-Polling chính của Telegram Bot."""
        if not self.is_configured:
            logger.warning("Dedicated Telegram Bot is not configured (missing bot_token). Standing by...")
            return

        self._running = True
        logger.info("Dedicated Telegram Bot runner started. Polling updates...")

        # Lấy thông tin bot
        try:
            session = await self.get_session()
            async with session.get(f"https://api.telegram.org/bot{self.token}/getMe") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._bot_info = data.get("result", {})
                    bot_name = self._bot_info.get("username", "UnknownBot")
                    logger.info(f"Connected to Telegram Bot: @{bot_name}")
                else:
                    logger.error(f"Invalid Telegram bot token! Status: {resp.status}")
                    return
        except Exception as e:
            logger.error(f"Cannot connect to Telegram Bot API: {e}")
            return

        while self._running:
            try:
                session = await self.get_session()
                url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                params = {"offset": self._last_update_id + 1, "timeout": 25}

                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        updates = data.get("result", [])
                        for u in updates:
                            self._last_update_id = max(self._last_update_id, u.get("update_id", 0))
                            asyncio.create_task(self.handle_update(u))
                    elif resp.status in (401, 404):
                        logger.error(f"Invalid Telegram Bot Token! Terminating bot loop.")
                        break
                    else:
                        await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Dedicated bot poll error: {e}")
                await asyncio.sleep(3)

    def stop(self) -> None:
        self._running = False
        if self._session and not self._session.closed:
            asyncio.create_task(self._session.close())


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Dedicated Telegram Bot for Quantum Council AI")
    parser.add_argument("--token", type=str, help="Telegram Bot Token from @BotFather", default=None)
    args = parser.parse_args()

    bot = DedicatedTelegramBot(bot_token=args.token)
    if not bot.is_configured:
        print("\n[!] CHƯA CÓ TELEGRAM BOT TOKEN!")
        print("Cách tạo bot Telegram riêng trong 30 giây:")
        print("1. Mở Telegram, tìm kiếm bot '@BotFather'")
        print("2. Gõ lệnh: /newbot")
        print("3. Đặt tên hiển thị cho bot (VD: Quantum AI Debate)")
        print("4. Đặt username kết thúc bằng 'bot' (VD: my_quant_debate_bot)")
        print("5. Copy chuỗi HTTP API Token (VD: 123456789:ABCdefGHI...) và chạy lại:")
        print("   python -m telegram.dedicated_bot --token <TOKEN>\n")
        sys.exit(1)

    print(f"[*] Starting Dedicated Telegram Bot...")
    asyncio.run(bot.run())

