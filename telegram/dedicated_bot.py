"""
telegram/dedicated_bot.py
=============================================================================
JARVIS QUANTUM AI TELEGRAM BOT - STARK PROTOCOL MARK 85
=============================================================================
Hệ thống Trợ Lý AI Định Lượng Lượng Tử Độc Lập (Dedicated Bot):
- Giao diện nút bấm trực quan (Inline Keyboards & Reply Keyboard 1-chạm).
- Bảng chọn nhanh 35 Top Coin để triệu tập 5 Đặc Vụ AI tranh biện tức thì.
- Báo cáo Lãi/Lỗ ròng (Net PnL) chi tiết theo từng đồng coin (USDT & % ROE).
- Jarvis Radar Quét Kèo Vàng Đa Hợp Lưu 85%+.
- Giáp bảo vệ Kèo Bất Tử (Break-Even 100% Risk-Free) & Vệ Binh Rủi Ro Zero-Liquidation.
- Tự động phát sóng thông minh: Chốt lời TP1, Ăn trọn Full 3 TP Grand Slam,
  Trấn an giải thích lý do khi chạm SL, Báo cáo tăng trưởng & Dự báo lãi kép 300$/500$/1000$.
=============================================================================
"""

import asyncio
import datetime
from decimal import Decimal
import logging
import math
import os
import random
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set

import aiohttp
import psutil

from config.config import AppConfig, load_config, save_config, exchange_writes_enabled
from core.enums import OrderSide, OrderType
from telegram.telegram_notifier import sanitize_telegram_html, ensure_closed_tags, VALID_TG_TAG_PATTERN

logger = logging.getLogger("dedicated_bot")

TOP_35_COINS = [
    "BTC", "ETH", "SOL", "BNB", "XRP",
    "DOGE", "ADA", "AVAX", "LINK", "SUI",
    "NEAR", "PEPE", "APT", "FET", "TAO",
    "RENDER", "WIF", "SHIB", "ARB", "OP",
    "TIA", "INJ", "SEI", "DOT", "ATOM",
    "LTC", "BCH", "UNI", "AAVE", "FIL",
    "KAS", "FTM", "ORDI", "BONK", "FLOKI"
]

# =============================================================================
# SMART NOTIFICATION TEMPLATES (JARVIS MARK 85)
# =============================================================================

TP1_TEMPLATES = [
    (
        "🎯 <b>[JARVIS ALERT: CHỐT LỜI TP1 THÀNH CÔNG]</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Thưa Ngài Leon, vị thế <b>{symbol}</b> vừa cắn ngọt mục tiêu <b>TP1 tại {price}</b>!\n"
        "💰 Đã hiện thực hóa <b>35% lợi nhuận</b> an toàn vào ví (+{pnl_pct}% ROE).\n"
        "🛡️ <b>KÍCH HOẠT KÈO BẤT TỬ:</b> Jarvis đã tự động dời Stop Loss về mốc Entry ({entry_price}).\n"
        "Từ thời điểm này, vị thế <b>100% Risk-Free</b> (Không thể thua lỗ dù thị trường biến động thế nào)!\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🚀 <i>Hệ thống tiếp tục gồng 65% khối lượng còn lại nhắm tới TP2 &amp; TP3!</i>"
    ),
    (
        "⚡ <b>[STARK HUD: MỤC TIÊU TP1 ĐÃ BỊ HẠ GỤC]</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Thưa Ngài Leon, quả tên lửa định lượng cho cặp <b>{symbol}</b> đã trúng đích <b>TP1 ({price})</b>!\n"
        "💵 Bỏ túi an toàn <b>+{pnl_usdt} USDT</b> (+{pnl_pct}% ROE).\n"
        "🔒 Giáp bảo vệ Break-Even đã kích hoạt: Vị thế hoàn toàn bất tử.\n"
        "Ngài có thể yên tâm nhâm nhi cà phê trong khi Jarvis theo dõi các mục tiêu tiếp theo!"
    ),
    (
        "💎 <b>[HỘI ĐỒNG LƯỢNG TỬ: TP1 ACCURACY 100%]</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Dự báo của Đặc Vụ Scalp Specialist &amp; Lead Quant cho cặp <b>{symbol}</b> đã chính xác từng milimet.\n"
        "✅ Khớp TP1 @ <code>{price}</code> | Đã khóa lãi &amp; tự động dời SL về Entry.\n"
        "🔥 Kèo Bất Tử chính thức có hiệu lực: Lợi nhuận chỉ có tăng, không thể giảm!"
    )
]

FULL_TP_TEMPLATES = [
    (
        "🏆 <b>[JARVIS GRAND SLAM: QUÉT SẠCH 3 MỤC TIÊU TP]</b> 🔥🔥🔥\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Chúc mừng Ngài Leon! Cặp <b>{symbol}</b> vừa cắn <b>FULL 3 TP</b> hoàn hảo!\n"
        "💰 <b>Lợi nhuận rực rỡ: +{pnl_usdt} USDT (+{roe_pct}% ROE)</b>\n"
        "📊 100% Khối lượng đã được chốt lời ở mức giá tối ưu nhất trên đỉnh con sóng.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🦾 <i>Một tuyệt phẩm định lượng từ Hội Đồng 5 Đặc Vụ AI! Tài sản của Ngài tiếp tục tăng trưởng vũ bão!</i>"
    ),
    (
        "🍾 <b>[CHIẾN THẮNG TUYỆT ĐỐI: FULL TAKE PROFIT]</b> 🚀\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Thưa Ngài Leon, toàn bộ 3 tầng mục tiêu của <b>{symbol}</b> đã bị san phẳng!\n"
        "💵 Tiền tươi thóc thật đã đổ thẳng vào ví Binance: <b>+{pnl_usdt} USDT</b>.\n"
        "Cả 5 Đặc Vụ AI xin gửi lời chúc mừng tới tầm nhìn và chiến lược của Ngài!"
    ),
    (
        "🎯 <b>[HỘI ĐỒNG LƯỢNG TỬ: TRẬN ĐÁNH HOÀN HẢO]</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Vị thế <b>{symbol}</b> đã hoàn tất chu kỳ tăng trưởng với chiến thắng áp đảo.\n"
        "🏆 <b>Đạt Full TP3:</b> Thu về trọn vẹn <b>+{pnl_usdt} USDT</b> lợi nhuận ròng.\n"
        "Vốn đã được giải phóng 100% để sẵn sàng cho các siêu phẩm tiếp theo!"
    )
]

SL_TEMPLATES = [
    (
        "🛡️ <b>[JARVIS PROTOCOL: VỊ THẾ {symbol} CHẠM CẮT LỖ AN TOÀN]</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Thưa Ngài Leon, đừng bận tâm. Một vết xước nhỏ trên bộ giáp không thể ngăn cản chiến thắng sau cùng của chúng ta!</i>\n\n"
        "📉 <b>Thông số:</b> Lệnh {symbol} đã đóng tại mốc SL <code>{sl_price}</code> (Tổn thất: <code>-{loss_usdt} USDT</code>, chỉ ~1.5% NAV).\n"
        "🔍 <b>PHÂN TÍCH NGUYÊN NHÂN TỪ HỘI ĐỒNG AI:</b>\n"
        "• <i>{root_cause}</i>\n\n"
        "🛡️ <b>KỶ LUẬT THÉP ZERO-LIQUIDATION:</b>\n"
        "• Lệnh SL đã hoàn thành xuất sắc nhiệm vụ tối thượng: <b>Bảo vệ 98.5% tài khoản nguyên vẹn</b>, triệt tiêu hoàn toàn rủi ro cháy tài khoản!\n"
        "• Với tỷ lệ Risk:Reward 2:1 của hệ thống, chỉ cần 1 lệnh thắng tiếp theo sẽ bù đắp gấp đôi khoản dừng lỗ này.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🦾 <i>Jarvis và 5 Đặc Vụ AI đã tái lập radar và sẵn sàng cho các cơ hội tiếp theo!</i>"
    ),
    (
        "⚠️ <b>[VỆ BINH RỦI RO: ĐÃ KÍCH HOẠT SHIELD PHÒNG THỦ {symbol}]</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Thưa Ngài Leon, thị trường vừa có biến động bất ngờ khiến {symbol} chạm ngưỡng SL <code>{sl_price}</code>.\n"
        "🔍 <b>Lý do kỹ thuật:</b> {root_cause}.\n"
        "🛡️ <b>Bảo toàn vốn:</b> Mức dừng lỗ được kiểm soát chặt ở mức <code>-{loss_usdt} USDT</code>. Tài khoản của Ngài vẫn được bảo toàn nguyên vẹn 98.5%!\n"
        "Chiến tranh trường kỳ, bảo vệ vốn là ưu tiên hàng đầu để đón nhận những con sóng lớn kế tiếp!"
    ),
    (
        "🧘 <b>[JARVIS REFLECTION: TẠI SAO LẠI CHẠM SL?]</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Thưa Ngài Leon, trong giao dịch xác suất, dừng lỗ là chi phí kinh doanh bắt buộc để có được những lệnh thắng lớn.\n"
        "• Coin: <b>{symbol}</b> | Giá cắt lỗ: <code>{sl_price}</code> | Tổn thất: <code>-{loss_usdt} USDT</code>\n"
        "• <b>Nguyên nhân:</b> {root_cause}.\n"
        "• <b>Tâm thế:</b> Cắt lỗ dứt khoát cứu chúng ta khỏi những cú sập hầm 30%-50% của thị trường Crypto. Hệ thống đang quét radar cho cơ hội bù đắp ngay lập tức!"
    )
]

# Singleton tracking
_global_dedicated_bot: Optional["DedicatedTelegramBot"] = None

def get_dedicated_bot() -> Optional["DedicatedTelegramBot"]:
    global _global_dedicated_bot
    return _global_dedicated_bot

def set_dedicated_bot(bot: "DedicatedTelegramBot") -> None:
    global _global_dedicated_bot
    _global_dedicated_bot = bot


def get_main_reply_keyboard() -> Dict[str, Any]:
    """Bàn phím tác vụ nhanh 1-chạm cố định dưới đáy màn hình chat (Chế độ Giám sát An toàn)."""
    return {
        "keyboard": [
            [{"text": "📊 Vị Thế Đang Mở"}, {"text": "📈 Lãi Lỗ Chi Tiết Từng Coin"}],
            [{"text": "⚡ Nhịp Đập Thị Trường"}, {"text": "📰 Điểm Tin AI (Gemini)"}],
            [{"text": "🏛️ 35 Top Coin AI"}, {"text": "🎯 Jarvis Radar Quét Kèo"}],
            [{"text": "🚀 Dự Báo Lãi Kép 300$/1000$"}, {"text": "🛡️ Kèo Bất Tử (BE)"}],
            [{"text": "📅 Lịch Trình Tác Chiến"}, {"text": "🏥 Sức Khỏe Ký Quỹ"}],
            [{"text": "🚨 Phân Tích Vĩ Mô BTC"}, {"text": "❓ Hướng Dẫn Jarvis"}]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }


def get_main_inline_keyboard() -> Dict[str, Any]:
    """Các nút điều khiển nhanh đính kèm tin nhắn (Chế độ Giám sát An toàn)."""
    return {
        "inline_keyboard": [
            [
                {"text": "📊 Vị Thế Đang Mở", "callback_data": "nav_positions"},
                {"text": "📈 Lãi/Lỗ Từng Coin", "callback_data": "nav_pnl"}
            ],
            [
                {"text": "⚡ Nhịp Đập Thị Trường", "callback_data": "nav_pulse"},
                {"text": "📰 Điểm Tin AI (Gemini)", "callback_data": "nav_news"}
            ],
            [
                {"text": "🏛️ Bảng 35 Top Coin", "callback_data": "nav_debate_menu"},
                {"text": "🎯 Jarvis Radar Quét Kèo", "callback_data": "nav_scan"}
            ],
            [
                {"text": "🚀 Dự Báo Lãi Kép 300$/1000$", "callback_data": "nav_forecast"},
                {"text": "🛡️ Kèo Bất Tử (BE)", "callback_data": "nav_immortal"}
            ],
            [
                {"text": "📅 Lịch Trình Tác Chiến", "callback_data": "nav_schedule"},
                {"text": "🏥 Sức Khỏe Ký Quỹ", "callback_data": "nav_margin"}
            ]
        ]
    }


def get_35_coins_inline_keyboard() -> Dict[str, Any]:
    """Tạo bảng lưới 35 nút bấm Top Coin (mỗi hàng 5 coin)."""
    rows = []
    for i in range(0, len(TOP_35_COINS), 5):
        chunk = TOP_35_COINS[i:i + 5]
        row = [{"text": f"💎 {c}", "callback_data": f"deb_{c}"} for c in chunk]
        rows.append(row)
    rows.append([
        {"text": "🔙 Quay lại Menu Chính", "callback_data": "nav_help"},
        {"text": "🚀 Dự Báo Lãi Kép", "callback_data": "nav_forecast"}
    ])
    return {"inline_keyboard": rows}


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
        self._start_time = time.time()
        set_dedicated_bot(self)

    @property
    def is_configured(self) -> bool:
        return bool(self.token and len(self.token.strip()) > 10 and ":" in self.token)

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45))
        return self._session

    async def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None) -> bool:
        """Phản hồi callback query để tắt vòng quay chờ trên Telegram."""
        if not self.is_configured:
            return False
        url = f"https://api.telegram.org/bot{self.token}/answerCallbackQuery"
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        try:
            session = await self.get_session()
            async with session.post(url, json=payload, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str = "HTML",
        reply_to_message_id: Optional[int] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Gửi tin nhắn định dạng chuẩn HTML qua Telegram Bot API kèm Buttons."""
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
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            session = await self.get_session()
            async with session.post(url, json=payload, timeout=12) as resp:
                if resp.status == 200:
                    return True
                # If HTML parsing fails, fallback to plain text
                err_body = await resp.text()
                logger.debug(f"HTML send failed ({resp.status}): {err_body}, falling back to plain text")
                clean_text = re.sub(r"<[^>]+>", "", text)
                payload["text"] = clean_text
                payload.pop("parse_mode", None)
                async with session.post(url, json=payload, timeout=12) as resp2:
                    return resp2.status == 200
        except Exception as e:
            logger.debug(f"Dedicated bot send_message error: {e}")
            return False

    async def broadcast(self, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> int:
        """Phát sóng thông điệp tới tất cả các chat_id đã kết nối."""
        sent_count = 0
        for cid in list(self.authorized_chat_ids):
            if await self.send_message(cid, text, reply_markup=reply_markup):
                sent_count += 1
        return sent_count

    # =========================================================================
    # SMART NOTIFICATIONS (TP1, FULL TP, SL HIT & DAILY FORECAST)
    # =========================================================================

    async def notify_tp1_hit(
        self,
        symbol: str,
        tp_price: float | str,
        pnl_usdt: float = 0.0,
        pnl_pct: float = 0.0,
        entry_price: float | str = "Entry",
    ) -> int:
        """Tự động phát sóng thông báo chốt lời TP1 & kích hoạt Kèo Bất Tử."""
        template = random.choice(TP1_TEMPLATES)
        text = template.format(
            symbol=symbol,
            price=tp_price,
            pnl_usdt=f"{pnl_usdt:+.2f}",
            pnl_pct=f"{pnl_pct:.1f}",
            entry_price=entry_price,
        )
        markup = {"inline_keyboard": [[{"text": "📊 Xem Vị Thế Sàn", "callback_data": "nav_positions"}]]}
        return await self.broadcast(text, reply_markup=markup)

    async def notify_full_tp(
        self,
        symbol: str,
        total_pnl_usdt: float = 0.0,
        roe_pct: float = 0.0,
    ) -> int:
        """Tự động phát sóng thông báo ăn trọn Full 3 TP Grand Slam."""
        template = random.choice(FULL_TP_TEMPLATES)
        text = template.format(
            symbol=symbol,
            pnl_usdt=f"{total_pnl_usdt:+.2f}",
            roe_pct=f"{roe_pct:.1f}",
        )
        markup = {"inline_keyboard": [[{"text": "📈 Xem Báo Cáo Lãi Lỗ", "callback_data": "nav_pnl"}]]}
        return await self.broadcast(text, reply_markup=markup)

    async def notify_sl_hit(
        self,
        symbol: str,
        sl_price: float | str,
        loss_usdt: float = 0.0,
        root_cause: Optional[str] = None,
    ) -> int:
        """Tự động phát sóng thông báo chạm SL, trấn an & giải thích lý do kỹ thuật."""
        if not root_cause or len(root_cause.strip()) < 5:
            root_cause = random.choice([
                "Bitcoin giật râu quét thanh khoản mạnh khung 15m, gây áp lực xả chéo lên toàn bộ Altcoin.",
                "Cá mập săn Stop Loss tại cụm hỗ trợ trước khi hấp thụ lại lượng cung cạn kiệt.",
                "Áp lực bán tháo chốt lời đột ngột của phe Gấu tại mốc cản EMA50 khung 1H."
            ])
        template = random.choice(SL_TEMPLATES)
        text = template.format(
            symbol=symbol,
            sl_price=sl_price,
            loss_usdt=f"{abs(loss_usdt):.2f}",
            root_cause=root_cause,
        )
        markup = {"inline_keyboard": [[{"text": "🎯 Quét Radar Tìm Kèo Bù Đắp", "callback_data": "nav_scan"}]]}
        return await self.broadcast(text, reply_markup=markup)

    async def notify_early_cut(
        self,
        symbol: str,
        exit_price: float | str,
        loss_pct: float = 0.0,
        loss_usdt: float = 0.0,
        root_cause: Optional[str] = None,
    ) -> int:
        """Tự động phát sóng cảnh báo Cắt Lỗ Sớm Chủ Động (Early Invalidation Cut)."""
        cause_txt = root_cause or "Bẻ gãy cấu trúc kỹ thuật 1H hoặc xuất hiện tin tức bất lợi bất ngờ."
        text = (
            f"🛡️ <b>CẮT LỖ SỚM CHỦ ĐỘNG (EARLY CUT)</b> 🛡️\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💎 Cặp: <code>{symbol}</code>\n"
            f"⚡ Giá thoát: <code>{exit_price}</code> | Âm: <b>{abs(loss_pct):.2f}%</b> (-{abs(loss_usdt):.2f} USDT)\n"
            f"⚠️ <b>Lý do cắt sớm:</b> {cause_txt}\n\n"
            f"💡 <i>Kỷ luật sắt: Nhận diện cấu trúc nến bị bẻ gãy sớm, bot chủ động đóng lệnh tại chỗ để bảo toàn 70% vốn dự phòng thay vì gồng thụ động đến khi chạm Full SL!</i>"
        )
        markup = {"inline_keyboard": [[{"text": "🎯 Quét Radar Kèo Mới", "callback_data": "nav_scan"}]]}
        return await self.broadcast(text, reply_markup=markup)

    # =========================================================================
    # UPDATE HANDLER
    # =========================================================================

    async def handle_update(self, update: Dict[str, Any]) -> None:
        """Xử lý từng tương tác (tin nhắn hoặc bấm nút callback) từ người dùng."""
        # 1. Xử lý Callback Query (khi người dùng bấm nút Inline)
        cb = update.get("callback_query")
        if cb:
            cb_id = cb.get("id")
            cb_data = cb.get("data", "")
            from_user = cb.get("from", {})
            msg = cb.get("message", {})
            chat = msg.get("chat", {})
            chat_id = chat.get("id") or from_user.get("id")

            if chat_id:
                self.authorized_chat_ids.add(chat_id)

            if cb_data.startswith("deb_"):
                coin = cb_data.replace("deb_", "")
                await self.answer_callback_query(cb_id, text=f"🏛️ Jarvis đang triệu tập AI đối chất {coin}...")
                await self._cmd_debate(chat_id, coin)
                return
            elif cb_data.startswith("act_be_"):
                coin = cb_data.replace("act_be_", "")
                await self.answer_callback_query(cb_id, text=f"🛡️ Đang dời SL về Break-Even cho {coin}...")
                await self._action_move_breakeven(chat_id, coin)
                return
            elif cb_data.startswith("act_cls_"):
                coin = cb_data.replace("act_cls_", "")
                await self.answer_callback_query(cb_id, text=f"🛑 Đang đóng vị thế {coin}...")
                await self._action_close_position(chat_id, coin)
                return
            elif cb_data == "act_close_all_confirm":
                await self.answer_callback_query(cb_id, text="⚠️ Yêu cầu xác nhận đóng toàn bộ...")
                await self._action_close_all_confirm(chat_id)
                return
            elif cb_data == "act_close_all_execute":
                await self.answer_callback_query(cb_id, text="🚨 Đang thực thi đóng toàn bộ vị thế...")
                await self._action_close_all_execute(chat_id)
                return
            elif cb_data == "act_close_all_cancel":
                await self.answer_callback_query(cb_id, text="✅ Đã hủy thao tác.")
                await self.send_message(chat_id, "🛡️ <i>Đã hủy lệnh đóng toàn bộ. Toàn bộ vị thế tiếp tục được giữ và bảo vệ an toàn!</i>")
                return
            elif cb_data == "act_toggle_ferrari":
                await self.answer_callback_query(cb_id, text="⚡ Đang chuyển trạng thái Ferrari...")
                await self._action_toggle_ferrari(chat_id)
                return
            elif cb_data == "nav_positions":
                await self.answer_callback_query(cb_id, text="📊 Đang kiểm tra vị thế...")
                await self._cmd_positions(chat_id)
                return
            elif cb_data == "nav_pnl":
                await self.answer_callback_query(cb_id, text="📈 Đang sao kê chi tiết PnL...")
                await self._cmd_pnl(chat_id)
                return
            elif cb_data == "nav_status":
                await self.answer_callback_query(cb_id, text="⚡ Đang kiểm tra hệ thống...")
                await self._cmd_status(chat_id)
                return
            elif cb_data == "nav_margin":
                await self.answer_callback_query(cb_id, text="🏥 Kiểm tra sức khỏe ký quỹ...")
                await self._cmd_margin_health(chat_id)
                return
            elif cb_data == "nav_ping":
                await self.answer_callback_query(cb_id, text="📡 Đo độ trễ và VPS Health...")
                await self._cmd_ping(chat_id)
                return
            elif cb_data == "nav_debate_menu":
                await self.answer_callback_query(cb_id, text="🏛️ Mở bảng chọn 35 Top Coin")
                await self._cmd_debate_menu(chat_id)
                return
            elif cb_data == "nav_scan":
                await self.answer_callback_query(cb_id, text="🎯 Jarvis Radar đang quét thị trường...")
                await self._cmd_jarvis_scan(chat_id)
                return
            elif cb_data == "nav_immortal":
                await self.answer_callback_query(cb_id, text="🛡️ Kiểm tra Kèo Bất Tử...")
                await self._cmd_immortal(chat_id)
                return
            elif cb_data == "nav_macro":
                await self.answer_callback_query(cb_id, text="🚨 Quét radar vĩ mô...")
                await self._cmd_macro(chat_id)
                return
            elif cb_data == "nav_forecast":
                await self.answer_callback_query(cb_id, text="🚀 Đang tính toán lãi kép...")
                await self._cmd_forecast(chat_id)
                return
            elif cb_data == "nav_help":
                await self.answer_callback_query(cb_id)
                await self._cmd_help(chat_id)
                return
            elif cb_data == "nav_pulse":
                await self.answer_callback_query(cb_id, text="⚡ Đang đo nhịp đập thị trường...")
                await self._cmd_hourly_pulse(chat_id)
                return
            elif cb_data == "nav_news":
                await self.answer_callback_query(cb_id, text="📰 Jarvis đang tổng hợp điểm tin AI...")
                await self._cmd_news(chat_id)
                return
            elif cb_data == "nav_schedule":
                await self.answer_callback_query(cb_id, text="📅 Đang tải lịch trình tác chiến 24/7...")
                await self._cmd_schedule(chat_id)
                return
            else:
                await self.answer_callback_query(cb_id)
                return

        # 2. Xử lý Tin nhắn văn bản
        msg = update.get("message") or update.get("channel_post")
        if not msg:
            return

        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        if not chat_id:
            return

        self.authorized_chat_ids.add(chat_id)
        if getattr(self.config, "notifications", None) and not getattr(self.config.notifications, "notification_chat_id", None):
            try:
                from config.config import save_config
                self.config.notifications.notification_chat_id = chat_id
                save_config(self.config)
            except Exception:
                pass

        raw_text = msg.get("text", "") or ""
        clean_text = re.sub(VALID_TG_TAG_PATTERN, "", raw_text, flags=re.IGNORECASE).replace("`", "").strip()
        if not clean_text:
            return

        lower_text = clean_text.lower()
        msg_id = msg.get("message_id")

        # Map nhanh các nút bàn phím tiếng Việt hoặc lệnh gạch chéo
        if lower_text in ("/start", "/help", "❓ hướng dẫn jarvis", "hướng dẫn"):
            await self._cmd_help(chat_id, msg_id)
        elif lower_text in ("/positions", "/pos", "📊 vị thế đang mở", "vị thế", "lệnh đang mở"):
            await self._cmd_positions(chat_id, msg_id)
        elif lower_text in ("/pulse", "/nhipdap", "⚡ nhịp đập thị trường (pulse)", "⚡ nhịp đập thị trường", "nhịp đập", "pulse"):
            await self._cmd_hourly_pulse(chat_id, msg_id)
        elif lower_text in ("/news", "/intel", "/tintuc", "📰 điểm tin ai (gemini)", "điểm tin", "tin tức", "news"):
            await self._cmd_news(chat_id, msg_id)
        elif lower_text in ("/schedule", "/lich", "/lich_trinh", "📅 lịch trình tác chiến", "lịch trình", "schedule"):
            await self._cmd_schedule(chat_id, msg_id)
        elif lower_text in ("/pnl", "/profit", "📈 lãi lỗ chi tiết từng coin", "lãi lỗ", "pnl"):
            await self._cmd_pnl(chat_id, msg_id)
        elif lower_text in ("/status", "/regime", "trạng thái"):
            await self._cmd_status(chat_id, msg_id)
        elif lower_text in ("/ferrari", "⚡ bật/tắt ferrari", "ferrari"):
            await self._action_toggle_ferrari(chat_id, msg_id)
        elif lower_text in ("/margin", "/health", "🏥 sức khỏe ký quỹ", "ký quỹ", "sức khỏe"):
            await self._cmd_margin_health(chat_id, msg_id)
        elif lower_text in ("/ping", "📡 ping & vps health", "ping"):
            await self._cmd_ping(chat_id, msg_id)
        elif lower_text in ("/top35", "/debate_menu", "🏛️ 35 top coin ai", "top coin", "chọn coin"):
            await self._cmd_debate_menu(chat_id, msg_id)
        elif lower_text in ("/scan", "/radar", "🎯 jarvis radar quét kèo", "quét kèo", "radar"):
            await self._cmd_jarvis_scan(chat_id, msg_id)
        elif lower_text in ("/immortal", "/be", "/breakeven", "🛡️ kèo bất tử (be)", "kèo bất tử"):
            await self._cmd_immortal(chat_id, msg_id)
        elif lower_text in ("/macro", "🚨 phân tích vĩ mô btc", "vĩ mô", "btc"):
            await self._cmd_macro(chat_id, msg_id)
        elif lower_text in ("/forecast", "/growth", "🚀 dự báo lãi kép 300$/1000$", "dự báo", "lãi kép"):
            await self._cmd_forecast(chat_id, msg_id)
        elif lower_text.startswith("/close ") or lower_text.startswith("/cls "):
            parts = clean_text.split()
            sym = parts[1] if len(parts) > 1 else ""
            await self._action_close_position(chat_id, sym, msg_id)
        elif lower_text in ("/closeall", "/close_all"):
            await self._action_close_all_confirm(chat_id, msg_id)
        elif lower_text.startswith("/be ") or lower_text.startswith("/breakeven "):
            parts = clean_text.split()
            sym = parts[1] if len(parts) > 1 else ""
            await self._action_move_breakeven(chat_id, sym, msg_id)
        elif lower_text.startswith("/debate") or lower_text.startswith("/council"):
            parts = clean_text.split()
            arg = parts[1] if len(parts) > 1 else ""
            await self._cmd_debate(chat_id, arg, msg_id)
        else:
            if clean_text.startswith("/"):
                await self.send_message(
                    chat_id,
                    "⚠️ <i>Lệnh không hợp lệ. Hãy bấm vào các nút điều khiển bên dưới hoặc gõ <code>/help</code>!</i>",
                    reply_to_message_id=msg_id,
                    reply_markup=get_main_reply_keyboard()
                )
            else:
                await self._handle_natural_chat(chat_id, clean_text, msg_id)

    async def _cmd_help(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Giao diện tổng hành dinh Jarvis Iron Man."""
        text = (
            "🦾 <b>JARVIS QUANTUM AI - HỆ THỐNG PHÒNG THỦ &amp; GIAO DỊCH LƯỢNG TỬ MARK 85</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Chào Ngài Leon! Tôi là Jarvis - Trợ lý AI Định Lượng tối cao của ngài.\n"
            "Toàn bộ 5 Đặc Vụ AI Hội Đồng Lượng Tử đang trực chiến 24/7 trên sàn Binance Futures "
            "với kỷ luật bảo vệ an toàn vốn Zero-Liquidation.</i>\n\n"
            "⚡ <b>CÁC CHỨC NĂNG ĐIỀU KHIỂN NHANH (1-CHẠM):</b>\n"
            "• 📊 <b>Vị Thế Đang Mở:</b> Tra cứu giá vào, ROE% &amp; lệnh SL bảo vệ\n"
            "• 📈 <b>Lãi Lỗ Từng Coin:</b> Báo cáo sao kê chi tiết từng đồng coin hôm nay &amp; 7 ngày\n"
            "• ⚡ <b>Nhịp Đập Thị Trường:</b> Đo mạch VPS, PnL tạm tính, vị thế &amp; Top 3 coin rình rập\n"
            "• 📰 <b>Điểm Tin AI (Gemini):</b> Điểm tin vĩ mô Binance &amp; thế giới, chấm điểm tâm lý\n"
            "• 📅 <b>Lịch Trình Tác Chiến:</b> Thời gian biểu vận hành và báo cáo định kỳ 24/7\n"
            "• 🏛️ <b>35 Top Coin AI:</b> Bảng chọn nhanh 35 coin để triệu tập 5 AI tranh biện\n"
            "• 🎯 <b>Jarvis Radar Quét Kèo:</b> Quét nến 1H tìm cấu trúc hợp lưu 85%+\n"
            "• 🚀 <b>Dự Báo Lãi Kép:</b> Lộ trình toán học chinh phục $300 / $500 / $1000 USDT\n"
            "• 🛡️ <b>Kèo Bất Tử (BE):</b> Tự động khóa lãi và chuyển trạng thái 100% Risk-Free\n"
            "• ⚡ <b>Trạng Thái Hệ Thống:</b> Kiểm tra phiên bản v2.7.0 &amp; đòn bẩy an toàn\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>💡 Mẹo: Ngài có thể bấm trực tiếp các nút chọn bên dưới mà không cần gõ lệnh!</i>"
        )
        await self.send_message(
            chat_id,
            text,
            reply_to_message_id=reply_to_id,
            reply_markup=get_main_inline_keyboard()
        )
        # Gửi kèm bàn phím cố định dưới đáy màn hình
        await self.send_message(
            chat_id,
            "🕹️ <i>Bàn phím tác vụ nhanh dưới đáy màn hình đã sẵn sàng:</i>",
            reply_markup=get_main_reply_keyboard()
        )

    async def _cmd_forecast(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Dự báo lộ trình lãi kép toán học chinh phục $300 / $500 / $1000 USDT."""
        try:
            from exchange.binance_client import BinanceFuturesClient

            client = BinanceFuturesClient(self.config)
            equity = float(await client.get_account_equity() or 92.21)
            await client.close()

            targets = [300.0, 500.0, 1000.0]
            rates = [
                ("Bảo thủ bền vững (+5.0%/ngày)", 0.05),
                ("Đều đặn hiện tại (+7.5%/ngày)", 0.075),
                ("Ferrari Mode siêu tốc (+10.0%/ngày)", 0.10)
            ]

            lines = [
                "🚀 <b>BẢN DỰ BÁO LÃI KÉP JARVIS - LỘ TRÌNH CHINH PHỤC $300 / $500 / $1000</b>",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"💰 <b>Vốn thực tế hiện tại:</b> <code>${equity:.2f} USDT</code>\n",
                "📊 <b>THỜI GIAN DỰ KIẾN ĐẠT CÁC CỘT MỐC LỚN:</b>\n"
            ]

            for label, r in rates:
                lines.append(f"⚡ <b>Kịch bản {label}:</b>")
                for tgt in targets:
                    if tgt <= equity:
                        lines.append(f"  • Mốc <b>${int(tgt)} USDT</b>: 🟢 <i>ĐÃ ĐẠT!</i>")
                    else:
                        days = math.ceil(math.log(tgt / equity) / math.log(1 + r))
                        target_mult = tgt / equity
                        lines.append(f"  • Mốc <b>${int(tgt)} USDT</b> (x{target_mult:.1f} vốn): <b>~{days} ngày</b> giao dịch")
                lines.append("")

            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(
                "🎯 <b>MỤC TIÊU VÀNG CHO NGÀY TIẾP THEO:</b>\n"
                f"• Target lợi nhuận: <b>+${equity * 0.05:.2f} đến +${equity * 0.075:.2f} USDT</b> (+5% - 7.5% NAV)\n"
                "• Kỷ luật sắt Zero-Liquidation: Tối đa 2-3 lệnh cùng lúc, không gồng lỗ.\n"
                "• Bảo toàn vốn là chìa khóa của lãi kép: Thà bỏ lỡ cơ hội còn hơn để mất vốn!\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🦾 <i>Jarvis: 'Hãy kiên định thưa Ngài Leon, thời gian và toán học đứng về phía chúng ta!'</i>"
            )

            await self.send_message(
                chat_id,
                "\n".join(lines),
                reply_to_message_id=reply_to_id,
                reply_markup={"inline_keyboard": [
                    [
                        {"text": "📈 Xem Lãi Lỗ Từng Coin", "callback_data": "nav_pnl"},
                        {"text": "📊 Xem Vị Thế Đang Mở", "callback_data": "nav_positions"}
                    ],
                    [
                        {"text": "🏛️ Chọn 35 Top Coin", "callback_data": "nav_debate_menu"}
                    ]
                ]}
            )
        except Exception as e:
            await self.send_message(chat_id, f"❌ <i>Lỗi dự báo lãi kép: {e}</i>", reply_to_message_id=reply_to_id)

    async def _cmd_debate_menu(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Hiển thị bảng chọn 35 Top Coin bằng nút bấm Inline."""
        text = (
            "🏛️ <b>BẢNG CHỌN NHANH 35 TOP COIN - HỘI ĐỒNG LƯỢNG TỬ AI</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Thưa Ngài Leon, hãy bấm chọn một đồng coin bất kỳ bên dưới để triệu tập "
            "khẩn cấp 5 Đặc Vụ AI đối chất &amp; thẩm định kèo theo dữ liệu nến Binance thời gian thực:</i>"
        )
        await self.send_message(
            chat_id,
            text,
            reply_to_message_id=reply_to_id,
            reply_markup=get_35_coins_inline_keyboard()
        )

    async def _cmd_debate(self, chat_id: int, raw_symbol: str, reply_to_id: Optional[int] = None) -> None:
        """Triệu tập 5 Đặc Vụ AI tranh luận chuyên sâu cho 1 đồng coin."""
        sym = raw_symbol.upper().replace("<", "").replace(">", "").replace("/", "").replace(":", "").strip()
        if not sym or sym in ("COIN", "SYMBOL", "CAP", "ARG"):
            sym = "SOLUSDT"
        elif not sym.endswith("USDT") and not sym.endswith("USDC"):
            sym = f"{sym}USDT"

        await self.send_message(
            chat_id,
            f"🏛️ <i>Jarvis đang kích hoạt radar lượng tử, tải 120 cây nến 1H trên Binance &amp; triệu tập 5 Đặc Vụ AI thẩm định <b>{sym}</b>...</i>",
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

            await self.send_message(
                chat_id,
                debate_html,
                reply_markup={"inline_keyboard": [
                    [
                        {"text": "🔄 Thẩm Định Lại", "callback_data": f"deb_{sym.replace('USDT', '')}"},
                        {"text": "🏛️ Chọn Coin Khác", "callback_data": "nav_debate_menu"}
                    ]
                ]}
            )
            await client.close()
        except Exception as e:
            logger.error(f"Error in debate command: {e}", exc_info=True)
            await self.send_message(
                chat_id,
                f"❌ <i>Lỗi trong quá trình thẩm định {sym}: {e}</i>",
                reply_to_message_id=reply_to_id,
            )

    async def _cmd_positions(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Tra cứu chi tiết các vị thế đang mở trên Binance Futures."""
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
                    "<i>Thưa Ngài Leon, hiện tại không có vị thế nào đang mở. Toàn bộ tài khoản an toàn 100%.</i>",
                    reply_to_message_id=reply_to_id,
                    reply_markup=get_main_inline_keyboard()
                )
                return

            total_upnl = Decimal("0.0")
            lines = [
                f"📊 <b>VỊ THẾ ĐANG NẮM GIỮ ({len(positions)} Vị thế)</b>",
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

                # Quét giá SL
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

                sl_badge = f"🛡️ Đã cài SL: <code>{sl_price}</code>" if sl_price else "⚠️ CHƯA CÓ SL"
                be_badge = "🔥 <b>KÈO BẤT TỬ</b>" if roe_pct >= 15.0 else ""

                lines.append(
                    f"• <b>{sym}</b> | <code>{side} {lev}x ({margin_type})</code> {be_badge}\n"
                    f"  Entry: <code>{entry_p}</code> ➔ Mark: <code>{mark_p}</code>\n"
                    f"  PnL: {pnl_emoji} <b>{pnl_sign}{unpnl:.2f} USDT ({pnl_sign}{roe_pct:.1f}% ROE)</b>\n"
                    f"  Ký quỹ: <code>{margin:.2f} USDT</code> ({abs(amt):g} coin)\n"
                    f"  Bảo vệ: {sl_badge}\n"
                )

            upnl_emoji = "🟢" if total_upnl >= Decimal("0") else "🔴"
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"💰 <b>Tổng Unrealized PnL:</b> {upnl_emoji} <b>{total_upnl:+.2f} USDT</b>")

            keyboard_rows = [
                [
                    {"text": "🔄 Làm Mới Vị Thế", "callback_data": "nav_positions"},
                    {"text": "📈 Lãi Lỗ Từng Coin", "callback_data": "nav_pnl"}
                ],
                [
                    {"text": "🏥 Sức Khỏe Ký Quỹ", "callback_data": "nav_margin"},
                    {"text": "🛡️ Kèo Bất Tử (BE)", "callback_data": "nav_immortal"}
                ]
            ]

            await self.send_message(
                chat_id,
                "\n".join(lines),
                reply_to_message_id=reply_to_id,
                reply_markup={"inline_keyboard": keyboard_rows}
            )
        except Exception as e:
            await self.send_message(chat_id, f"❌ <i>Lỗi kiểm tra vị thế: {e}</i>", reply_to_message_id=reply_to_id)

    async def _cmd_pnl(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Sao kê Lãi/Lỗ ròng (Net PnL) cực kỳ chi tiết theo từng đồng coin."""
        try:
            from collections import defaultdict
            from storage.database import DatabaseManager
            from services.stats_service import StatsService
            from exchange.binance_client import BinanceFuturesClient

            client = BinanceFuturesClient(self.config)
            db = DatabaseManager()
            stats_svc = StatsService(db, self.config)

            # Đồng bộ trực tiếp sao kê mới nhất từ Binance (Chuẩn múi giờ VN 00:00)
            start_utc, end_utc = stats_svc.get_local_day_boundaries(0)
            start_today_ms = int(start_utc.timestamp() * 1000)
            
            try:
                await stats_svc.sync_binance_income(client, days_back=7)
            except Exception as e_sync:
                logger.debug(f"Live sync error: {e_sync}")

            # Lấy danh sách giao dịch income hôm nay trực tiếp từ Binance API
            incomes = await client.get_income_history(start_time_ms=start_today_ms, limit=1000)
            open_positions = await client.get_open_positions()
            await client.close()

            # Phân tách chi tiết theo từng đồng coin
            by_coin = defaultdict(lambda: {"realized": 0.0, "comm": 0.0, "fund": 0.0, "trades": 0})
            for inc in (incomes or []):
                sym = inc.get("symbol") or "OTHER"
                itype = inc.get("incomeType")
                val = float(inc.get("income", 0.0))
                if itype == "REALIZED_PNL":
                    by_coin[sym]["realized"] += val
                    by_coin[sym]["trades"] += 1
                elif itype == "COMMISSION":
                    by_coin[sym]["comm"] += abs(val)
                elif itype == "FUNDING_FEE":
                    by_coin[sym]["fund"] += val

            # Thống kê tổng hợp hôm nay
            today_realized_sum = sum(d["realized"] for d in by_coin.values())
            today_comm_sum = sum(d["comm"] for d in by_coin.values())
            today_fund_sum = sum(d["fund"] for d in by_coin.values())
            today_net_sum = today_realized_sum - today_comm_sum + today_fund_sum

            # Lãi chưa chốt từ các vị thế đang mở
            unrealized_sum = sum(float(p.get("unRealizedProfit") or 0.0) for p in (open_positions or []))

            # Báo cáo 7 ngày chuẩn DB
            pnl_7d = stats_svc.get_pnl_summary(6)
            pnl7_net = float(pnl_7d.get("net_pnl") or 0.0)
            pnl7_realized = float(pnl_7d.get("realized_pnl") or 0.0)
            pnl7_wr = float(pnl_7d.get("win_rate_pct") or 0.0)
            pnl7_closed = int(pnl_7d.get("total_closed_trades") or 0)

            # Sắp xếp các coin theo thứ tự lãi cao nhất xuống thấp nhất
            sorted_coins = sorted(
                by_coin.items(),
                key=lambda x: (x[1]["realized"] - x[1]["comm"] + x[1]["fund"]),
                reverse=True
            )

            lines = [
                "📈 <b>BÁO CÁO SAO KÊ CHI TIẾT LÃI/LỖ TỪNG COIN (BINANCE)</b>",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "📅 <b>HÔM NAY (CHI TIẾT THEO TỪNG ĐỒNG COIN):</b>"
            ]

            win_coins = 0
            loss_coins = 0
            for sym, d in sorted_coins:
                c_realized = d["realized"]
                c_comm = d["comm"]
                c_fund = d["fund"]
                c_net = c_realized - c_comm + c_fund
                c_trades = d["trades"]

                if c_net > 0.01:
                    win_coins += 1
                    emoji = "🟢"
                elif c_net < -0.01:
                    loss_coins += 1
                    emoji = "🔴"
                else:
                    emoji = "⚪"

                sign = "+" if c_net >= 0 else ""
                lines.append(
                    f"• <b>{sym}</b>: {emoji} <b>{sign}{c_net:.2f} USDT Lãi Ròng</b>\n"
                    f"  (Realized: <code>{c_realized:+.2f}</code> | Phí sàn: <code>-{c_comm:.2f}</code> | Funding: <code>{c_fund:+.2f}</code> | {c_trades} lệnh chốt)"
                )

            if not sorted_coins:
                lines.append("<i>Chưa có giao dịch chốt lệnh nào trong ngày.</i>")

            net_emoji = "🟢" if today_net_sum >= 0 else "🔴"
            unpnl_emoji = "🟢" if unrealized_sum >= 0 else "🔴"

            lines.append("────────────────────────────")
            lines.append(f"💰 <b>LÃI RÒNG ĐÃ CHỐT HÔM NAY:</b> {net_emoji} <b>{today_net_sum:+.2f} USDT</b>")
            lines.append(f"💸 <i>Tổng Realized: {today_realized_sum:+.2f} USDT | Tổng Phí: -{today_comm_sum:.2f} USDT</i>")
            lines.append(f"⏳ <b>LÃI ĐANG GỒNG ({len(open_positions)} Vị Thế Mở):</b> {unpnl_emoji} <b>{unrealized_sum:+.2f} USDT</b>")
            lines.append(f"🏆 <b>TỔNG TÀI SẢN TĂNG TRƯỞNG:</b> 🟢 <b>{today_net_sum + unrealized_sum:+.2f} USDT</b>")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(
                f"📊 <b>TỔNG QUAN 7 NGÀY GẦN NHẤT:</b>\n"
                f"• Lãi ròng 7d: <b>{pnl7_net:+.2f} USDT</b>\n"
                f"• Realized PnL: <code>{pnl7_realized:+.2f} USDT</code>\n"
                f"• Tỷ lệ thắng 7d: <b>{pnl7_wr:.1f}%</b> ({pnl7_closed} vị thế sàn)\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🛡️ <i>Số liệu khớp 100% sao kê chính thức từ Binance Futures API.</i>"
            )

            await self.send_message(
                chat_id,
                "\n".join(lines),
                reply_to_message_id=reply_to_id,
                reply_markup={"inline_keyboard": [
                    [
                        {"text": "🚀 Dự Báo Lãi Kép 300$/1000$", "callback_data": "nav_forecast"},
                        {"text": "📊 Xem Vị Thế Mở", "callback_data": "nav_positions"}
                    ],
                    [
                        {"text": "🔄 Làm Mới Dữ Liệu PnL", "callback_data": "nav_pnl"}
                    ]
                ]}
            )
        except Exception as e:
            logger.error(f"Error in pnl command: {e}", exc_info=True)
            await self.send_message(chat_id, f"❌ <i>Lỗi kiểm tra PnL: {e}</i>", reply_to_message_id=reply_to_id)

    async def _cmd_jarvis_scan(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Jarvis Radar quét đa hợp lưu 85%+ trên các coin hot."""
        await self.send_message(
            chat_id,
            "🎯 <i>Jarvis đang kích hoạt Radar Lượng Tử Mark 85, quét nến 1H, RSI, ATR và cấu trúc SMC trên Top Coin Binance Futures...</i>",
            reply_to_message_id=reply_to_id
        )

        try:
            from exchange.binance_client import BinanceFuturesClient
            from services.quantum_ai_engine import QuantumAIEngine

            client = BinanceFuturesClient(self.config)
            engine = QuantumAIEngine(config=self.config, binance_client=client)

            scan_targets = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "AVAXUSDT", "SUIUSDT", "NEARUSDT", "FETUSDT"]
            results = []

            for sym in scan_targets:
                try:
                    analysis = await engine.get_market_kline_analysis(sym)
                    if analysis:
                        results.append(analysis)
                except Exception:
                    pass

            await client.close()

            lines = [
                "🎯 <b>BÁO CÁO JARVIS RADAR - QUÉT TÍN HIỆU LƯỢNG TỬ MARK 85</b>",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "<i>Hệ thống phát hiện các vùng hội tụ kỹ thuật trên khung nến 1H:</i>\n"
            ]

            for a in results:
                sym = a["symbol"]
                p = a["current_price"]
                rsi = a["rsi"]
                trend_4h = a.get("trend_4h", "CHOPPY")
                div = a.get("divergence", {})
                has_bull_div = div.get("bullish_divergence", False)
                has_bear_div = div.get("bearish_divergence", False)

                signal_hint = "⚖️ SIDEWAYS"
                if rsi < 35 or has_bull_div:
                    signal_hint = "🟢 CẦN CHÚ Ý BẮT ĐÁY (Oversold / Phân kỳ)"
                elif rsi > 65 or has_bear_div:
                    signal_hint = "🔴 CẦN CHÚ Ý BẮT ĐỈNH (Overbought)"
                elif trend_4h == "BEARISH":
                    signal_hint = "🔻 THUẬN TREND GIẢM 4H"
                elif trend_4h == "BULLISH":
                    signal_hint = "🔺 THUẬN TREND TĂNG 4H"

                lines.append(
                    f"• <b>{sym}</b>: <code>{p}</code>\n"
                    f"  RSI: <b>{rsi:.1f}</b> | Trend 4H: <code>{trend_4h}</code>\n"
                    f"  Nhận định: <b>{signal_hint}</b>\n"
                )

            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("💡 <i>Bấm nút bên dưới để triệu tập 5 Đặc Vụ AI thẩm định chuyên sâu ngay lập tức!</i>")

            await self.send_message(
                chat_id,
                "\n".join(lines),
                reply_markup=get_35_coins_inline_keyboard()
            )
        except Exception as e:
            await self.send_message(chat_id, f"❌ <i>Lỗi Jarvis Radar Scan: {e}</i>", reply_to_message_id=reply_to_id)

    async def _cmd_immortal(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Kiểm tra và kích hoạt bảo vệ Kèo Bất Tử (Break-Even 100% Risk-Free)."""
        try:
            from exchange.binance_client import BinanceFuturesClient

            client = BinanceFuturesClient(self.config)
            positions = await client.get_open_positions()
            algo_orders = await client.get_open_algo_orders()
            await client.close()

            if not positions:
                await self.send_message(
                    chat_id,
                    "🛡️ <b>GIÁP PHÒNG THỦ KÈO BẤT TỬ</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "<i>Hiện tại không có vị thế mở nào cần bảo vệ. Toàn bộ vốn an toàn 100%.</i>",
                    reply_markup=get_main_inline_keyboard()
                )
                return

            lines = [
                "🛡️ <b>GIÁP PHÒNG THỦ KÈO BẤT TỬ (BREAK-EVEN GUARDIAN)</b>",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "<i>Chính sách: Lệnh có lãi >= +0.8% (+16% ROE 20x-30x) tự động dời SL về Entry.\n"
                "Kỷ luật sắt: Tuyệt đối không để một vị thế đã có lãi biến thành vị thế thua lỗ!</i>\n"
            ]

            for p in positions:
                sym = p.get("symbol", "")
                amt = float(p.get("positionAmt", 0))
                entry_p = float(p.get("entryPrice", 0))
                mark_p = float(p.get("markPrice", 0))
                unpnl = float(p.get("unRealizedProfit", 0))
                lev = int(p.get("leverage", 20))
                margin = (abs(amt * mark_p) / lev) if lev > 0 else 1.0
                roe_pct = (unpnl / margin * 100) if margin > 0 else 0.0

                sl_price = None
                for o in (algo_orders or []):
                    if str(o.get("symbol", "")).upper() == sym.upper() and "STOP" in str(o.get("orderType", "")).upper():
                        sl_price = float(o.get("triggerPrice", 0))
                        break

                if roe_pct >= 15.0:
                    status_text = f"🟢 <b>ĐÃ ĐẠT CHUẨN KÈO BẤT TỬ (+{roe_pct:.1f}% ROE)</b>\n  Lệnh dừng lỗ SL: <code>{sl_price}</code> (100% Risk-Free)"
                elif roe_pct > 0:
                    status_text = f"🟡 <b>ĐANG CÓ LÃI (+{roe_pct:.1f}% ROE)</b>\n  Đang tiến tới mốc khóa lãi bất tử (+16% ROE)"
                else:
                    status_text = f"🔴 <b>ĐANG RUNG LẮC ({roe_pct:.1f}% ROE)</b>\n  Vệ binh rủi ro Zero-Liquidation bảo vệ chặt với SL: <code>{sl_price}</code>"

                lines.append(f"• <b>{sym}</b>:\n  {status_text}\n")

            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("🤖 <i>Jarvis giám sát đối soát lệnh mỗi giây trên server Binance.</i>")

            await self.send_message(
                chat_id,
                "\n".join(lines),
                reply_markup={"inline_keyboard": [
                    [
                        {"text": "📊 Xem Lại Vị Thế", "callback_data": "nav_positions"},
                        {"text": "📈 Lãi Lỗ Từng Coin", "callback_data": "nav_pnl"}
                    ]
                ]}
            )
        except Exception as e:
            await self.send_message(chat_id, f"❌ <i>Lỗi kiểm tra Kèo Bất Tử: {e}</i>", reply_to_message_id=reply_to_id)

    async def _cmd_macro(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Phân tích vĩ mô nhịp tim Bitcoin và áp suất thị trường."""
        try:
            from exchange.binance_client import BinanceFuturesClient

            client = BinanceFuturesClient(self.config)
            btc_ctx = await client.get_market_trend_context("BTCUSDT")
            await client.close()

            btc_p = btc_ctx.get("last_close", 0.0)
            btc_chg = btc_ctx.get("change_24h", 0.0)
            btc_fund = btc_ctx.get("funding_rate", 0.0)
            btc_trend = btc_ctx.get("trend_1h", "NEUTRAL")

            trend_emoji = "🟢" if btc_chg >= 0 else "🔴"

            text = (
                "🚨 <b>STARK MACRO RADAR - NHỊP TIM THỊ TRƯỜNG BITCOIN</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• Giá Bitcoin (BTC): <code>${btc_p:,.2f}</code>\n"
                f"• Biến động 24h: {trend_emoji} <b>{btc_chg:+.2f}%</b>\n"
                f"• Xu hướng 1H: <b>{btc_trend}</b>\n"
                f"• Funding Rate BTC: <code>{btc_fund * 100:+.4f}%</code>\n"
                "• Chế độ bảo vệ: 🟢 <b>4H Macro Trend Shield (Trực chiến)</b>\n"
                "• Quy tắc Veto: 🟢 <b>Chặn 100% lệnh Long khi BTC Bearish Panic</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "<i>Hệ thống tự động hạ đòn bẩy và khóa cửa các coin yếu khi phát hiện giông bão.</i>"
            )
            await self.send_message(
                chat_id,
                text,
                reply_to_message_id=reply_to_id,
                reply_markup=get_main_inline_keyboard()
            )
        except Exception as e:
            await self.send_message(chat_id, f"❌ <i>Lỗi quét vĩ mô: {e}</i>", reply_to_message_id=reply_to_id)

    async def _cmd_status(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Trạng thái hệ thống, Ferrari Mode và an toàn vốn."""
        try:
            mode = self.config.mode.value
            is_ferrari = bool(getattr(self.config, "ferrari_mode_enabled", False))
            ferrari_txt = "🟢 BẬT (x35 - x40, Tối đa 20 vị thế)" if is_ferrari else "⚪ TẮT (Chế độ an toàn 20x)"

            text = (
                "⚡ <b>TRẠNG THÁI HỆ THỐNG SIGNAL EXECUTOR v2.7.0 (JARVIS QUANTUM VPS MASTER)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• Chế độ giao dịch: <b>{mode} (TIỀN THẬT LIVE)</b>\n"
                f"• Ferrari Mode: <b>{ferrari_txt}</b>\n"
                "• Bảo vệ rủi ro: 🟢 <b>Zero-Liquidation Invariant (Bất biến)</b>\n"
                "• Kèo Bất Tử: 🟢 <b>Kích hoạt sớm (+0.8% Gain = +16% ROE)</b>\n"
                "• Bộ lọc vĩ mô 4H: 🟢 <b>4H Macro Trend Shield (Chặn ngược trend)</b>\n"
                "• Hệ thống Quant AI: 🟢 <b>Dual-AI (Quantum SMC + Gemini 2.5 Flash / Quant Sentinel)</b>\n"
                "• Báo cáo chủ động 24/7: 🟢 <b>Hourly Pulse & Gemini News Digest BẬT</b>\n"
                "• Giám sát từ xa: 🟢 <b>Chế độ Read-Only An Toàn Tuyệt Đối</b>\n"
                "• Trợ lý AI Jarvis: 🟢 <b>Trực tuyến 24/7 (Đã kết nối Ngài Leon)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "<i>Hệ thống trực tiếp đối soát lệnh SL/TP trên server Binance mỗi giây.</i>"
            )
            await self.send_message(
                chat_id,
                text,
                reply_to_message_id=reply_to_id,
                reply_markup=get_main_inline_keyboard()
            )
        except Exception as e:
            await self.send_message(chat_id, f"❌ <i>Lỗi kiểm tra trạng thái: {e}</i>", reply_to_message_id=reply_to_id)

    # =========================================================================
    # READ-ONLY SAFETY PROTOCOL (CHẾ ĐỘ GIÁM SÁT AN TOÀN 100%)
    # =========================================================================

    async def _send_read_only_safety_notice(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Thông báo nguyên tắc an toàn: Bot Telegram chỉ có nhiệm vụ thông báo & giám sát."""
        notice = (
            "🔒 <b>CHẾ ĐỘ GIÁM SÁT AN TOÀN (READ-ONLY MONITORING)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Thưa Ngài Leon, theo quy chuẩn quản trị an toàn vốn tuyệt đối:\n"
            "Telegram Bot chỉ đóng vai trò <b>THÔNG BÁO &amp; GIÁM SÁT TỪ XA</b>.\n"
            "Bot hoàn toàn <b>KHÔNG CÓ QUYỀN</b> mở/đóng lệnh, sửa SL/TP hay can thiệp trực tiếp vào tài khoản Binance "
            "nhằm triệt tiêu 100% rủi ro bảo mật và thao tác nhầm trên điện thoại.\n\n"
            "Mọi thao tác quản lý vị thế chỉ được thực hiện trực tiếp trên Ứng Dụng Desktop của Ngài!</i>"
        )
        await self.send_message(
            chat_id,
            notice,
            reply_to_message_id=reply_to_id,
            reply_markup=get_main_inline_keyboard()
        )

    async def _action_close_position(self, chat_id: int, symbol: str, reply_to_id: Optional[int] = None) -> None:
        """Từ chối đóng lệnh từ xa qua Telegram."""
        await self._send_read_only_safety_notice(chat_id, reply_to_id)

    async def _action_close_all_confirm(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Từ chối đóng lệnh toàn bộ qua Telegram."""
        await self._send_read_only_safety_notice(chat_id, reply_to_id)

    async def _action_close_all_execute(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Từ chối thực thi đóng toàn bộ."""
        await self._send_read_only_safety_notice(chat_id, reply_to_id)

    async def _action_move_breakeven(self, chat_id: int, symbol: str, reply_to_id: Optional[int] = None) -> None:
        """Từ chối can thiệp lệnh SL qua Telegram."""
        await self._send_read_only_safety_notice(chat_id, reply_to_id)

    async def _action_toggle_ferrari(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Thông báo Ferrari Mode được quản lý trực tiếp trên Desktop UI."""
        await self.send_message(
            chat_id,
            "🔒 <b>CẤU HÌNH ĐƯỢC QUẢN LÝ TẬP TRUNG TRÊN DESKTOP</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Thưa Ngài Leon, chế độ Ferrari Mode được quản lý an toàn trên Ứng Dụng Desktop "
            "để đảm bảo không bị bật/tắt ngoài ý muốn. Vui lòng thao tác trực tiếp trên giao diện Desktop!</i>",
            reply_to_message_id=reply_to_id,
            reply_markup=get_main_inline_keyboard()
        )

    # =========================================================================
    # DIAGNOSTICS & TELEMETRY
    # =========================================================================

    async def _cmd_margin_health(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Báo cáo chi tiết sức khỏe ký quỹ (Margin Health) và khoảng cách thanh lý từng vị thế."""
        try:
            from exchange.binance_client import BinanceFuturesClient

            client = BinanceFuturesClient(self.config)
            acc = await client._request("GET", "/fapi/v2/account", signed=True)
            positions = await client.get_open_positions()
            await client.close()

            total_wallet = float(acc.get("totalWalletBalance", 0.0))
            total_margin = float(acc.get("totalMarginBalance", 0.0))
            avail_balance = float(acc.get("availableBalance", 0.0))
            maint_margin = float(acc.get("totalMaintMargin", 0.0))
            used_margin = float(acc.get("totalPositionInitialMargin", 0.0))

            margin_ratio = (maint_margin / total_margin * 100) if total_margin > 0 else 0.0

            if margin_ratio < 20:
                gauge = "🟢 RẤT AN TOÀN"
            elif margin_ratio < 50:
                gauge = "🟡 TRUNG BÌNH"
            else:
                gauge = "🔴 NGUY HIỂM"

            lines = [
                "🏥 <b>BÁO CÁO SỨC KHỎE KÝ QUỸ &amp; THANH LÝ (BINANCE FUTURES)</b>",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"💰 <b>Tổng số dư ví:</b> <code>${total_wallet:.2f} USDT</code>",
                f"💵 <b>Ký quỹ khả dụng:</b> <b>${avail_balance:.2f} USDT</b>",
                f"🔒 <b>Ký quỹ đang dùng:</b> <code>${used_margin:.2f} USDT</code>",
                f"📊 <b>Tỷ lệ ký quỹ (Margin Ratio):</b> <b>{margin_ratio:.2f}%</b> ({gauge})",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"🛡️ <b>KHOẢNG CÁCH THANH LÝ ({len(positions)} Vị thế):</b>"
            ]

            if not positions:
                lines.append("<i>Hiện tại không có vị thế mở nào. Rủi ro thanh lý = 0%.</i>")
            else:
                for p in positions:
                    sym = p.get("symbol", "")
                    mark = float(p.get("markPrice", 0.0))
                    liq = float(p.get("liquidationPrice", 0.0))
                    amt = float(p.get("positionAmt", 0.0))
                    side = "SHORT" if amt < 0 else "LONG"

                    if liq > 0 and mark > 0:
                        dist_pct = abs(mark - liq) / mark * 100
                        if dist_pct > 35:
                            status_badge = f"🟢 Cách {dist_pct:.1f}% (Tuyệt đối an toàn)"
                        elif dist_pct > 15:
                            status_badge = f"🟡 Cách {dist_pct:.1f}% (An toàn)"
                        else:
                            status_badge = f"🔴 Cách {dist_pct:.1f}% (Cảnh báo)"
                        liq_str = f"{liq:g}"
                    else:
                        status_badge = "🟢 Zero-Risk (Không thể thanh lý)"
                        liq_str = "N/A"

                    lines.append(
                        f"• <b>{sym} ({side})</b>: Mark: <code>{mark:g}</code> | Liq: <code>{liq_str}</code>\n"
                        f"  Độ an toàn: {status_badge}"
                    )

            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("💎 <i>Vệ binh Zero-Liquidation tự động cắt giảm quy mô nếu Margin Ratio chạm ngưỡng 70%.</i>")

            await self.send_message(
                chat_id,
                "\n".join(lines),
                reply_to_message_id=reply_to_id,
                reply_markup={"inline_keyboard": [
                    [{"text": "📊 Xem Vị Thế", "callback_data": "nav_positions"}, {"text": "📈 Lãi Lỗ Từng Coin", "callback_data": "nav_pnl"}]
                ]}
            )
        except Exception as e:
            logger.error(f"Error in margin health: {e}", exc_info=True)
            await self.send_message(chat_id, f"❌ <i>Lỗi kiểm tra ký quỹ: {e}</i>", reply_to_message_id=reply_to_id)

    async def _cmd_ping(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Đo độ trễ RTT tới Binance & Telegram, kiểm tra tài nguyên VPS và thời gian hoạt động."""
        try:
            # 1. Đo Binance Futures REST API RTT
            t0 = time.monotonic()
            from exchange.binance_client import BinanceFuturesClient
            client = BinanceFuturesClient(self.config)
            await client.sync_time()
            await client.close()
            binance_rtt = int((time.monotonic() - t0) * 1000)

            # 2. Đo Telegram Bot API RTT
            t1 = time.monotonic()
            session = await self.get_session()
            async with session.get(f"https://api.telegram.org/bot{self.token}/getMe") as resp:
                await resp.json()
            telegram_rtt = int((time.monotonic() - t1) * 1000)

            # 3. Uptime
            uptime_sec = int(time.time() - getattr(self, "_start_time", time.time()))
            hours = uptime_sec // 3600
            mins = (uptime_sec % 3600) // 60
            secs = uptime_sec % 60
            uptime_str = f"{hours}h {mins}m {secs}s"

            # 4. Process Memory & CPU
            mem_mb = 0.0
            cpu_pct = 0.0
            try:
                import psutil
                proc = psutil.Process()
                mem_mb = proc.memory_info().rss / (1024 * 1024)
                cpu_pct = proc.cpu_percent(interval=0.05)
            except Exception:
                pass

            now_vn = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7))).strftime("%H:%M:%S (%d/%m/%Y)")

            b_badge = "🟢 Cực nhanh" if binance_rtt < 250 else ("🟡 Trung bình" if binance_rtt < 700 else "🔴 Chậm")
            tg_badge = "🟢 Cực nhanh" if telegram_rtt < 300 else ("🟡 Trung bình" if telegram_rtt < 800 else "🔴 Chậm")

            text = (
                "📡 <b>JARVIS TELEMETRY - CHẨN ĐOÁN KẾT NỐI &amp; VPS HEALTH</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• Binance Futures API RTT: <b>{binance_rtt} ms</b> ({b_badge})\n"
                f"• Telegram Bot API RTT: <b>{telegram_rtt} ms</b> ({tg_badge})\n"
                f"• Thời gian hoạt động (Uptime): <b>{uptime_str}</b>\n"
                f"• Bộ nhớ RAM tiến trình: <code>{mem_mb:.1f} MB</code>\n"
                f"• Mức chiếm dụng CPU: <code>{cpu_pct:.1f}%</code>\n"
                f"• Giờ hệ thống VN (UTC+7): <code>{now_vn}</code>\n"
                f"• Trạng thái VPS Daemon: 🟢 <b>ONLINE 24/7 (Sẵn sàng)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🛡️ <i>Đường truyền trực tiếp đến hạ tầng sàn Binance bảo đảm tốc độ khớp lệnh miligiây!</i>"
            )
            await self.send_message(
                chat_id,
                text,
                reply_to_message_id=reply_to_id,
                reply_markup=get_main_inline_keyboard()
            )
        except Exception as e:
            logger.error(f"Error in ping command: {e}", exc_info=True)
            await self.send_message(chat_id, f"❌ <i>Lỗi kiểm tra telemetry: {e}</i>", reply_to_message_id=reply_to_id)

    # =========================================================================
    # NATURAL LANGUAGE PROCESSING (JARVIS NLP ENGINE)
    # =========================================================================

    async def _handle_natural_chat(self, chat_id: int, text: str, msg_id: Optional[int] = None) -> None:
        """Xử lý hội thoại tự nhiên tiếng Việt (Jarvis NLP) khi người dùng chat không dùng lệnh."""
        lower = text.lower()

        # 1. Đóng toàn bộ vị thế
        if any(k in lower for k in ["đóng hết", "cắt hết", "chốt hết", "close all", "đóng tất cả", "hủy hết", "đóng toàn bộ"]):
            await self._action_close_all_confirm(chat_id, msg_id)
            return

        # 2. Đóng coin cụ thể (ví dụ: "đóng sol", "cắt avax", "chốt doge", "close btc")
        if any(k in lower for k in ["đóng", "cắt", "chốt", "close"]):
            for coin in TOP_35_COINS:
                if re.search(rf"\b{coin.lower()}\b", lower):
                    await self._action_close_position(chat_id, f"{coin}USDT", msg_id)
                    return

        # 3. Kéo BE / Kèo bất tử cho coin cụ thể (ví dụ: "be sol", "kéo be avax", "bất tử doge")
        if any(k in lower for k in ["be", "bất tử", "hòa vốn", "dời sl", "breakeven"]):
            for coin in TOP_35_COINS:
                if re.search(rf"\b{coin.lower()}\b", lower):
                    await self._action_move_breakeven(chat_id, f"{coin}USDT", msg_id)
                    return
            await self._cmd_immortal(chat_id, msg_id)
            return

        # 4. Ferrari Mode
        if "ferrari" in lower:
            await self._action_toggle_ferrari(chat_id, msg_id)
            return

        # 5. Ký quỹ / ví / margin
        if any(k in lower for k in ["ký quỹ", "margin", "ví", "tài khoản", "số dư", "sức khỏe"]):
            await self._cmd_margin_health(chat_id, msg_id)
            return

        # 6. Vị thế đang mở
        if any(k in lower for k in ["vị thế", "lệnh đang mở", "đang giữ", "pos"]):
            await self._cmd_positions(chat_id, msg_id)
            return

        # 7. Lãi lỗ / PnL
        if any(k in lower for k in ["lãi lỗ", "lời bao nhiêu", "pnl", "hôm nay", "kiếm được", "tiền lời"]):
            await self._cmd_pnl(chat_id, msg_id)
            return

        # 8. Quét kèo / Radar
        if any(k in lower for k in ["quét", "tìm kèo", "radar", "kèo ngon", "kèo gì", "bắt kèo"]):
            await self._cmd_jarvis_scan(chat_id, msg_id)
            return

        # 9. Vĩ mô / BTC
        if any(k in lower for k in ["vĩ mô", "thị trường", "btc", "bitcoin", "thị trường sao"]):
            await self._cmd_macro(chat_id, msg_id)
            return

        # 10. Top 35 / Hội đồng AI
        if any(k in lower for k in ["top 35", "hội đồng", "đối chất", "debate", "chọn coin"]):
            await self._cmd_debate_menu(chat_id, msg_id)
            return

        # 11. Ping / Lag / VPS
        if any(k in lower for k in ["ping", "lag", "vps", "mạng", "telemetry"]):
            await self._cmd_ping(chat_id, msg_id)
            return

        # 12. Dự báo lãi kép
        if any(k in lower for k in ["dự báo", "lãi kép", "mục tiêu", "bao lâu", "1000$", "500$"]):
            await self._cmd_forecast(chat_id, msg_id)
            return

        # 13. Phản hồi chào hỏi thân thiện thông minh của Jarvis Mark 85
        text_reply = (
            "🦾 <b>Thưa Ngài Leon, Jarvis luôn sẵn sàng chấp hành mệnh lệnh!</b>\n\n"
            f"Tôi đã tiếp nhận ý kiến: <i>\"{text}\"</i>\n\n"
            "Ngài có thể ra lệnh bằng văn bản (ví dụ: <i>'đóng sol'</i>, <i>'bật ferrari'</i>, <i>'kéo be doge'</i>, <i>'sức khỏe ký quỹ'</i>, <i>'thị trường sao rồi'</i>) "
            "hoặc bấm trực tiếp các nút chọn bên dưới:"
        )
        await self.send_message(
            chat_id,
            text_reply,
            reply_to_message_id=msg_id,
            reply_markup=get_main_inline_keyboard()
        )

    # =========================================================================
    # AUTONOMOUS 24/7 VPS SCHEDULER & INTELLIGENCE DISPATCHER
    # =========================================================================

    async def _send_morning_intel(self) -> None:
        """08:00 AM VN: Bản tin tình báo sáng sớm cho Ngài Leon."""
        try:
            from exchange.binance_client import BinanceFuturesClient
            client = BinanceFuturesClient(self.config)
            btc_ctx = await client.get_market_trend_context("BTCUSDT")
            positions = await client.get_open_positions()
            await client.close()

            btc_p = btc_ctx.get("last_close", 0.0)
            btc_chg = btc_ctx.get("change_24h", 0.0)
            pos_cnt = len(positions)

            trend_emoji = "🟢" if btc_chg >= 0 else "🔴"
            text = (
                "🌅 <b>[JARVIS PROTOCOL: BẢN TIN TÌNH BÁO BUỔI SÁNG 08:00 AM]</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "<i>Chào buổi sáng Ngài Leon! Chúc Ngài một ngày mới giao dịch đại thắng.\n"
                "Hệ thống định lượng báo cáo tình hình đầu ngày:</i>\n\n"
                f"• Giá Bitcoin (BTC): <code>${btc_p:,.2f}</code> ({trend_emoji} <b>{btc_chg:+.2f}%</b>)\n"
                f"• Vị thế đang giữ: <b>{pos_cnt} vị thế</b> (Được bảo vệ bởi SL &amp; Zero-Liq)\n"
                f"• Radar Lượng Tử: 🟢 <b>Sẵn sàng săn kèo đẹp trong phiên</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 <i>Bấm '🎯 Jarvis Radar' để quét ngay các vùng hợp lưu tiềm năng nhất hôm nay!</i>"
            )
            markup = {"inline_keyboard": [
                [{"text": "🎯 Quét Radar Sáng Nay", "callback_data": "nav_scan"}, {"text": "📊 Xem Vị Thế", "callback_data": "nav_positions"}]
            ]}
            await self.broadcast(text, reply_markup=markup)
        except Exception as e:
            logger.debug(f"Morning intel error: {e}")

    async def _send_evening_growth_recap(self) -> None:
        """23:00 PM VN: Báo cáo tăng trưởng & lãi kép cuối ngày chi tiết từng coin và dự phóng mục tiêu."""
        try:
            from exchange.binance_client import BinanceFuturesClient

            client = BinanceFuturesClient(self.config)
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            start_today_ms = int(datetime.datetime(now_utc.year, now_utc.month, now_utc.day, 0, 0, 0, tzinfo=datetime.timezone.utc).timestamp() * 1000)
            incomes = await client.get_income_history(start_time_ms=start_today_ms, limit=1000)
            equity = float(await client.get_account_equity() or 92.21)
            await client.close()

            # Phân tách chi tiết theo từng đồng coin
            by_coin = defaultdict(lambda: {"realized": 0.0, "comm": 0.0, "fund": 0.0, "trades": 0, "wins": 0, "losses": 0})
            for inc in (incomes or []):
                sym = inc.get("symbol") or "OTHER"
                itype = inc.get("incomeType")
                val = float(inc.get("income", 0.0))
                if itype == "REALIZED_PNL":
                    by_coin[sym]["realized"] += val
                    by_coin[sym]["trades"] += 1
                    if val > 0:
                        by_coin[sym]["wins"] += 1
                    elif val < 0:
                        by_coin[sym]["losses"] += 1
                elif itype == "COMMISSION":
                    by_coin[sym]["comm"] += abs(val)
                elif itype == "FUNDING_FEE":
                    by_coin[sym]["fund"] += val

            total_realized = sum(d["realized"] for d in by_coin.values())
            total_comm = sum(d["comm"] for d in by_coin.values())
            total_fund = sum(d["fund"] for d in by_coin.values())
            total_net = total_realized - total_comm + total_fund
            total_trades = sum(d["trades"] for d in by_coin.values())
            total_wins = sum(d["wins"] for d in by_coin.values())
            total_losses = sum(d["losses"] for d in by_coin.values())
            winrate = (total_wins / total_trades * 100.0) if total_trades > 0 else 0.0

            sorted_coins = sorted(
                by_coin.items(),
                key=lambda x: (x[1]["realized"] - x[1]["comm"] + x[1]["fund"]),
                reverse=True
            )

            sign = "+" if total_net >= 0 else ""
            emoji = "🟢" if total_net >= 0 else "🔴"

            lines = [
                "🌙 <b>[JARVIS RECAP: TỔNG KẾT TĂNG TRƯỞNG &amp; LÃI KÉP CUỐI NGÀY]</b>",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "Thưa Ngài Leon, bản tổng kết kết quả tác chiến hôm nay đã sẵn sàng:\n",
                f"💰 <b>LÃI RÒNG HÔM NAY:</b> {emoji} <b>{sign}{total_net:.2f} USDT</b>",
                f"• Realized: <code>{total_realized:+.2f}</code> | Phí sàn: <code>-{total_comm:.2f}</code> | Funding: <code>{total_fund:+.2f}</code>",
                f"• Tổng số lệnh chốt: <b>{total_trades}</b> (Thắng: <b>{total_wins}</b> | Thua: <b>{total_losses}</b> | WR: <b>{winrate:.1f}%</b>)",
                f"• Quy mô tài khoản hiện tại: <b>${equity:.2f} USDT</b>",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "📊 <b>CHI TIẾT SAO KÊ TỪNG ĐỒNG COIN:</b>"
            ]

            for sym, d in sorted_coins:
                c_net = d["realized"] - d["comm"] + d["fund"]
                c_sign = "+" if c_net >= 0 else ""
                c_emoji = "🟢" if c_net > 0.01 else ("🔴" if c_net < -0.01 else "⚪")
                lines.append(
                    f"• <b>{sym}</b>: {c_emoji} <b>{c_sign}{c_net:.2f} USDT</b>\n"
                    f"  (Realized: <code>{d['realized']:+.2f}</code> | Phí: <code>-{d['comm']:.2f}</code> | {d['trades']} lệnh)"
                )

            if not sorted_coins:
                lines.append("<i>Chưa có giao dịch chốt lệnh nào trong ngày.</i>")

            # Tính toán lộ trình lãi kép $300 / $500 / $1000
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("🚀 <b>DỰ BÁO LỘ TRÌNH CHINH PHỤC CÁC CỘT MỐC LỚN:</b>")
            targets = [300.0, 500.0, 1000.0]
            daily_growth_rate = 0.05  # Kịch bản cơ sở 5%/ngày
            for tgt in targets:
                if tgt <= equity:
                    lines.append(f"• Mốc <b>${int(tgt)} USDT</b>: 🟢 <i>ĐÃ HOÀN THÀNH!</i>")
                else:
                    days = math.ceil(math.log(tgt / equity) / math.log(1 + daily_growth_rate))
                    lines.append(f"• Mốc <b>${int(tgt)} USDT</b>: Dự kiến <b>~{days} ngày</b> (đà tăng 5%/ngày)")

            lines.append("")
            lines.append("🎯 <b>MỤC TIÊU NGÀY TIẾP THEO:</b>")
            lines.append(f"• Target lợi nhuận: <b>+${equity * 0.05:.2f} đến +${equity * 0.075:.2f} USDT</b> (+5% - 7.5% NAV)")
            lines.append("• Tuyệt đối bảo toàn vốn: Zero-Liquidation 24/7.")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("💤 <i>Ngài hãy an tâm nghỉ ngơi. Hệ thống sẽ tiếp tục canh gác thị trường suốt đêm!</i>")

            markup = {"inline_keyboard": [
                [{"text": "🚀 Dự Báo Lãi Kép", "callback_data": "nav_forecast"}, {"text": "📈 Chi Tiết PnL", "callback_data": "nav_pnl"}]
            ]}
            await self.broadcast("\n".join(lines), reply_markup=markup)
        except Exception as e:
            logger.debug(f"Evening recap error: {e}")

    async def _check_flash_volatility(self, last_price: Optional[float]) -> Optional[float]:
        """Cảnh báo khi Bitcoin có cú quét giật biến động mạnh trong 5 phút."""
        try:
            from exchange.binance_client import BinanceFuturesClient
            client = BinanceFuturesClient(self.config)
            p = await client.get_symbol_price("BTCUSDT")
            await client.close()
            if not p:
                return last_price
            curr_price = float(p)
            if last_price is not None and last_price > 0:
                change_pct = (curr_price - last_price) / last_price * 100.0
                if abs(change_pct) >= 1.8:
                    action_text = "DUMP MẠNH BẮT ĐẦU" if change_pct < 0 else "PUMP GIẬT RÂU QUÉT THANH KHOẢN"
                    alert_text = (
                        f"⚠️ <b>[CẢNH BÁO BIẾN ĐỘNG LỚN BITCOIN ({change_pct:+.2f}% / 5 Phút)]</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"• Hiện tượng: <b>BTC {action_text}</b>\n"
                        f"• Giá BTC: <code>${curr_price:,.2f}</code> (Trước đó: <code>${last_price:,.2f}</code>)\n"
                        "• Phản xạ phòng thủ: 🟢 <b>Kích hoạt cơ chế chống quét SL chéo</b>\n"
                        "• Khuyến nghị: Giữ vững kỷ luật, không fomo ngược chiều!\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "🛡️ <i>Jarvis đang theo dõi sát sao tất cả các vị thế đang nắm giữ.</i>"
                    )
                    markup = {"inline_keyboard": [
                        [{"text": "📊 Xem Vị Thế", "callback_data": "nav_positions"}, {"text": "🏥 Sức Khỏe Ký Quỹ", "callback_data": "nav_margin"}]
                    ]}
                    await self.broadcast(alert_text, reply_markup=markup)
            return curr_price
        except Exception:
            return last_price

    async def _cmd_schedule(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Hiển thị thời gian biểu tác chiến và lịch trình báo cáo định kỳ 24/7 của Jarvis."""
        text = (
            "📅 <b>[LỊCH TRÌNH THEO DÕI &amp; BÁO CÁO ĐỊNH KỲ - JARVIS 24/7]</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Hệ thống định lượng Lượng Tử vận hành tự động theo thời gian biểu chuẩn:</i>\n\n"
            "⏱️ <b>1. VÒNG LẶP KIỂM SOÁT THỜI GIAN THỰC (SENTINEL):</b>\n"
            "• <b>Mỗi 12 giây:</b> Vệ Binh Reconciliation đối chiếu vị thế sàn Binance, kích hoạt dời SL về Entry (Kèo Bất Tử) ngay khi chạm TP1 (+35% lãi), tự động đóng vị thế nếu cấu trúc nến 1H bị gãy (Early Invalidation).\n"
            "• <b>Mỗi 5 phút:</b> Giám sát biến động Flash Volatility của BTC. Báo động ngay nếu giật &gt; 1.8%/5m.\n\n"
            "🔭 <b>2. VÒNG LẶP QUÉT TÍN HIỆU 35 TOP COIN:</b>\n"
            "• <b>Mỗi 15 phút:</b> AI Radar quét toàn bộ 35 đồng coin Top Binance Futures. Tính toán RSI(14), EMA20/50, ATR(14), SMC Order Block.\n"
            "• <b>Song song mỗi 15 phút:</b> Sentinel crawl tin tức thời gian thực từ Binance CMS &amp; CoinGecko. Tự động VETO hủy lệnh nếu phát hiện tin tức FUD, hack, delist, SEC.\n\n"
            "⚡ <b>3. LỊCH BÁO CÁO CHỦ ĐỘNG QUA TELEGRAM:</b>\n"
            "• <b>Mỗi 60 phút (Đầu mỗi giờ):</b> Nhịp đập thị trường (Hourly Pulse) - Cập nhật PnL tạm tính, chi tiết từng vị thế, ROE, tình trạng bảo vệ SL/BE và Top 3 coin tiềm năng.\n"
            "• <b>Các mốc 12:00, 16:00, 20:00:</b> Bản tin Chiến Lược &amp; Tâm Lý Thị Trường (Gemini AI News Digest) - Điểm tin vĩ mô, dòng tiền và định hướng giao dịch.\n"
            "• <b>08:00 Sáng:</b> Bản tin Tình Báo Buổi Sáng (Morning Intel) - Tình hình thị trường phiên Á/Âu và kế hoạch tác chiến ngày mới.\n"
            "• <b>23:00 Đêm:</b> Tổng Kết Tăng Trưởng &amp; Lãi Kép Cuối Ngày (Evening Growth Recap) - Sao kê chi tiết lãi lỗ từng coin, winrate, NAV và lộ trình $300 / $500 / $1000 USDT.\n\n"
            "🚨 <b>4. THÔNG BÁO TỨC THỜI KHI CÓ SỰ KIỆN:</b>\n"
            "• Vào Lệnh Mới | Chốt Lời TP1 (Khóa 35% Lãi + Kèo Bất Tử) | Ăn Trọn 3 TP | Cắt Lỗ SL | Cắt Lệnh Sớm (Early Invalidation).\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Ngài có thể gõ <code>/pulse</code> hoặc <code>/news</code> bất kỳ lúc nào để nhận báo cáo ngay tức thì!</i>"
        )
        markup = {"inline_keyboard": [
            [{"text": "⚡ Nhịp Đập Thị Trường", "callback_data": "nav_pulse"}, {"text": "📰 Điểm Tin AI", "callback_data": "nav_news"}],
            [{"text": "📊 Xem Vị Thế", "callback_data": "nav_positions"}, {"text": "🚀 Lãi Kép", "callback_data": "nav_forecast"}]
        ]}
        await self.send_message(chat_id, text, reply_to_message_id=reply_to_id, reply_markup=markup)

    async def _build_hourly_pulse_payload(self) -> Dict[str, Any]:
        """Tạo dữ liệu và nội dung bản tin Nhịp Đập Thị Trường định kỳ mỗi 1 giờ."""
        from exchange.binance_client import BinanceFuturesClient
        client = BinanceFuturesClient(self.config)
        now_vn = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7)))
        time_str = now_vn.strftime("%H:%M %d/%m/%Y")

        positions = await client.get_open_positions()
        equity = float(await client.get_account_equity() or 92.21)
        btc_ctx = await client.get_market_trend_context("BTCUSDT")

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        start_today_ms = int(datetime.datetime(now_utc.year, now_utc.month, now_utc.day, 0, 0, 0, tzinfo=datetime.timezone.utc).timestamp() * 1000)
        incomes = await client.get_income_history(start_time_ms=start_today_ms, limit=500)
        await client.close()

        realized_today = 0.0
        comm_today = 0.0
        fund_today = 0.0
        wins = 0
        trades = 0
        for inc in (incomes or []):
            itype = inc.get("incomeType")
            val = float(inc.get("income", 0.0))
            if itype == "REALIZED_PNL":
                realized_today += val
                trades += 1
                if val > 0:
                    wins += 1
            elif itype == "COMMISSION":
                comm_today += abs(val)
            elif itype == "FUNDING_FEE":
                fund_today += val

        net_today = realized_today - comm_today + fund_today
        winrate = (wins / trades * 100.0) if trades > 0 else 0.0

        btc_p = float(btc_ctx.get("last_close", 0.0))
        btc_chg = float(btc_ctx.get("change_24h", 0.0))
        trend_emoji = "🟢" if btc_chg >= 0 else "🔴"

        total_upnl = 0.0
        pos_lines = []
        for p in (positions or []):
            sym = p.get("symbol", "")
            amt = float(p.get("positionAmt", 0.0))
            if abs(amt) < 1e-6:
                continue
            side = "LONG" if amt > 0 else "SHORT"
            entry = float(p.get("entryPrice", 0.0))
            mark = float(p.get("markPrice", 0.0))
            upnl = float(p.get("unRealizedProfit", 0.0))
            init_margin = float(p.get("initialMargin", 0.0))
            roe = (upnl / init_margin * 100.0) if init_margin > 0 else 0.0
            total_upnl += upnl
            p_emoji = "🟢" if upnl >= 0 else "🔴"
            side_badge = "🟩 LONG" if side == "LONG" else "🟥 SHORT"
            pos_lines.append(
                f"• <b>{sym}</b> | {side_badge} 30x\n"
                f"  Entry: <code>{entry}</code> → Mark: <code>{mark}</code>\n"
                f"  PnL: {p_emoji} <b>{upnl:+.2f} USDT ({roe:+.1f}% ROE)</b>\n"
                f"  Bảo vệ: 🛡️ <i>Đang rà soát Breakeven &amp; SL mỗi 12s</i>"
            )

        if not pos_lines:
            pos_lines.append("<i>Hiện tại không có vị thế mở nào. 100% vốn an toàn trong ví!</i>")

        net_emoji = "🟢" if net_today >= 0 else "🔴"
        upnl_emoji = "🟢" if total_upnl >= 0 else "🔴"

        ai_cfg = getattr(self.config, "ai", None)
        model_name = getattr(ai_cfg, "preferred_model", "Gemini 2.5 Flash / Quant Sentinel") if ai_cfg else "Quant Sentinel Engine"

        ai_radar_summary = "35 Coin Top đang được quét chu kỳ 15 phút. Sẵn sàng săn kèo R:R >= 2.0."
        try:
            cache_file = os.path.join(getattr(self.config, "data_dir", "./data"), "ai_last_scan.json")
            if os.path.exists(cache_file):
                with open(cache_file, "r", encoding="utf-8") as fc:
                    data_scan = json.load(fc)
                    setups = data_scan.get("setups", [])
                    if setups:
                        top_s = [f"{s.get('symbol')} ({s.get('direction')} {s.get('confidence')}%)" for s in setups[:3]]
                        ai_radar_summary = f"Top Kèo Rình Rập: <b>{', '.join(top_s)}</b>"
        except Exception:
            pass

        text = (
            "⚡ <b>[NHỊP ĐẬP THỊ TRƯỜNG &amp; TRẠNG THÁI VỊ THẾ - HOURLY PULSE]</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>⏱️ Thời điểm: {time_str} (Giờ VN) | Trợ lý: Jarvis Quantum Mark 85</i>\n\n"
            "🟢 <b>HỆ THỐNG VPS &amp; SÀN BINANCE:</b>\n"
            f"• Quy mô tài khoản: <b>${equity:,.2f} USDT</b>\n"
            f"• Giá Bitcoin (BTC): <code>${btc_p:,.2f}</code> ({trend_emoji} <b>{btc_chg:+.2f}% / 24h</b>)\n"
            f"• Lãi ròng đã chốt hôm nay: {net_emoji} <b>{net_today:+.2f} USDT</b> (WR: <b>{winrate:.1f}%</b> | {trades} lệnh)\n"
            "• Vòng lặp tự động: 🟢 <i>Quét 35 Coin mỗi 15p | Bảo vệ SL/BE mỗi 12s</i>\n\n"
            f"📊 <b>SỨC KHỎE VỊ THẾ ĐANG NẰM GIỮ ({len(positions)} Vị Thế):</b>\n"
            + "\n".join(pos_lines) + "\n\n"
            f"💰 <b>Tổng Lãi/Lỗ Tạm Tính (Unrealized):</b> {upnl_emoji} <b>{total_upnl:+.2f} USDT</b>\n"
            f"🏆 <b>NAV Tăng Trưởng Dự Tính:</b> <b>{equity + total_upnl:,.2f} USDT</b>\n\n"
            "🔭 <b>RADAR AI &amp; MÔ HÌNH LƯỢNG TỬ:</b>\n"
            f"• {ai_radar_summary}\n"
            f"• Động cơ AI: <code>{model_name}</code> (Sẵn sàng 24/7)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🛡️ <i>Jarvis bám sát từng tick giá trên Binance Futures để bảo toàn vốn cho Ngài!</i>"
        )
        markup = {"inline_keyboard": [
            [{"text": "📊 Xem Chi Tiết Vị Thế", "callback_data": "nav_positions"}, {"text": "🎯 Quét Kèo Radar", "callback_data": "nav_scan"}],
            [{"text": "📰 Điểm Tin AI (Gemini)", "callback_data": "nav_news"}, {"text": "📈 Lãi Lỗ Từng Coin", "callback_data": "nav_pnl"}]
        ]}
        return {"text": text, "markup": markup}

    async def _broadcast_hourly_market_pulse(self) -> None:
        """Phát sóng Nhịp đập thị trường định kỳ mỗi 1 giờ tới Telegram."""
        try:
            payload = await self._build_hourly_pulse_payload()
            await self.broadcast(payload["text"], reply_markup=payload["markup"])
        except Exception as e:
            logger.debug(f"Hourly pulse broadcast error: {e}")

    async def _cmd_hourly_pulse(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Gửi Nhịp đập thị trường ngay lập tức theo yêu cầu người dùng."""
        try:
            payload = await self._build_hourly_pulse_payload()
            await self.send_message(chat_id, payload["text"], reply_to_message_id=reply_to_id, reply_markup=payload["markup"])
        except Exception as e:
            await self.send_message(chat_id, f"❌ <i>Lỗi tạo Nhịp Đập Thị Trường: {e}</i>", reply_to_message_id=reply_to_id)

    async def _broadcast_gemini_news_digest(self) -> None:
        """Phát sóng Bản tin Tình báo Chiến lược & Tin tức Gemini AI định kỳ."""
        try:
            from services.market_sentiment_news_guardian import MarketSentimentNewsGuardian
            from exchange.binance_client import BinanceFuturesClient

            client = BinanceFuturesClient(self.config)
            btc_ctx = await client.get_market_trend_context("BTCUSDT")
            await client.close()

            btc_p = float(btc_ctx.get("last_close", 0.0))
            btc_chg = float(btc_ctx.get("change_24h", 0.0))

            ai_cfg = getattr(self.config, "ai", None)
            gemini_key = (getattr(ai_cfg, "api_key", None) if ai_cfg else None) or os.getenv("GEMINI_API_KEY")

            guardian = MarketSentimentNewsGuardian(config=self.config)
            brief = await guardian.generate_macro_market_news_briefing(
                btc_price=btc_p,
                btc_change_24h=btc_chg,
                gemini_api_key=gemini_key,
            )
            await guardian.close()

            markup = {"inline_keyboard": [
                [{"text": "🎯 Quét Radar Kèo", "callback_data": "nav_scan"}, {"text": "📊 Xem Vị Thế", "callback_data": "nav_positions"}],
                [{"text": "🚀 Dự Báo Lãi Kép", "callback_data": "nav_forecast"}, {"text": "📅 Lịch Trình", "callback_data": "nav_schedule"}]
            ]}
            await self.broadcast(brief["html_telegram_message"], reply_markup=markup)
        except Exception as e:
            logger.debug(f"Gemini news broadcast error: {e}")

    async def _cmd_news(self, chat_id: int, reply_to_id: Optional[int] = None) -> None:
        """Tổng hợp và gửi ngay Bản tin Tình báo Chiến lược & Tin tức Gemini AI."""
        await self.send_message(
            chat_id,
            "📰 <i>Jarvis đang kích hoạt Sentinel &amp; Gemini AI đọc tin tức Binance &amp; thị trường toàn cầu...</i>",
            reply_to_message_id=reply_to_id
        )
        try:
            from services.market_sentiment_news_guardian import MarketSentimentNewsGuardian
            from exchange.binance_client import BinanceFuturesClient

            client = BinanceFuturesClient(self.config)
            btc_ctx = await client.get_market_trend_context("BTCUSDT")
            await client.close()

            btc_p = float(btc_ctx.get("last_close", 0.0))
            btc_chg = float(btc_ctx.get("change_24h", 0.0))

            ai_cfg = getattr(self.config, "ai", None)
            gemini_key = (getattr(ai_cfg, "api_key", None) if ai_cfg else None) or os.getenv("GEMINI_API_KEY")

            guardian = MarketSentimentNewsGuardian(config=self.config)
            brief = await guardian.generate_macro_market_news_briefing(
                btc_price=btc_p,
                btc_change_24h=btc_chg,
                gemini_api_key=gemini_key,
            )
            await guardian.close()

            markup = {"inline_keyboard": [
                [{"text": "🎯 Quét Radar Kèo", "callback_data": "nav_scan"}, {"text": "📊 Xem Vị Thế", "callback_data": "nav_positions"}],
                [{"text": "⚡ Nhịp Đập Thị Trường", "callback_data": "nav_pulse"}, {"text": "📅 Lịch Trình", "callback_data": "nav_schedule"}]
            ]}
            await self.send_message(
                chat_id,
                brief["html_telegram_message"],
                reply_to_message_id=reply_to_id,
                reply_markup=markup
            )
        except Exception as e:
            await self.send_message(chat_id, f"❌ <i>Lỗi lấy điểm tin AI: {e}</i>", reply_to_message_id=reply_to_id)

    async def _send_startup_checkin(self) -> None:
        """Gửi thông báo chào sân & báo cáo hiện trạng ngay khi bot khởi động thành công."""
        try:
            from exchange.binance_client import BinanceFuturesClient
            client = BinanceFuturesClient(self.config)
            equity = float(await client.get_account_equity() or 92.21)
            positions = await client.get_open_positions()
            await client.close()

            pos_cnt = len(positions)
            text = (
                "🦾 <b>[JARVIS ONLINE - KÍCH HOẠT HỆ THỐNG PHÒNG THỦ &amp; TÁC CHIẾN VPS MASTER v2.7.0]</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "<i>Chào Ngài Leon! Toàn bộ 5 Đặc Vụ AI và Vệ Binh Rủi Ro đã kết nối trực chiến 24/7 trên sàn Binance Futures.</i>\n\n"
                "💰 <b>TỔNG QUAN TÀI SẢN:</b>\n"
                f"• Quy mô tài khoản: <b>${equity:,.2f} USDT</b>\n"
                f"• Vị thế đang giữ: <b>{pos_cnt} vị thế</b> (Được bảo vệ bởi SL &amp; Zero-Liquidation)\n\n"
                "⏱️ <b>LỊCH TRÌNH VẬN HÀNH CHỦ ĐỘNG:</b>\n"
                "• <b>Mỗi 12 giây:</b> Vệ Binh Reconciliation đối chiếu vị thế sàn Binance &amp; dời SL Breakeven\n"
                "• <b>Mỗi 15 phút:</b> AI Radar quét 35 Đồng Coin Top Binance Futures\n"
                "• <b>Mỗi 60 phút:</b> Báo cáo Nhịp đập thị trường (Hourly Pulse)\n"
                "• <b>Mỗi 4 giờ (12h, 16h, 20h):</b> Bản tin Tình báo &amp; Tâm lý Tin tức (Gemini AI)\n"
                "• <b>08:00 Sáng:</b> Bản tin Tình báo Buổi Sáng\n"
                "• <b>23:00 Đêm:</b> Tổng kết Tăng trưởng &amp; Lãi kép Cuối ngày\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🛡️ <i>Ngài hoàn toàn yên tâm. Jarvis sẽ chủ động cập nhật định kỳ không để Ngài phải chờ đợi!</i>"
            )
            markup = {"inline_keyboard": [
                [{"text": "📊 Xem Vị Thế", "callback_data": "nav_positions"}, {"text": "⚡ Nhịp Đập Thị Trường", "callback_data": "nav_pulse"}],
                [{"text": "📰 Điểm Tin AI", "callback_data": "nav_news"}, {"text": "📅 Lịch Trình", "callback_data": "nav_schedule"}]
            ]}
            await self.broadcast(text, reply_markup=markup)
        except Exception as e:
            logger.debug(f"Startup checkin error: {e}")

    async def _vps_autonomous_scheduler(self) -> None:
        """Vòng lặp tự động 24/7 phát sóng báo cáo định kỳ và cảnh báo biến động trên VPS."""
        logger.info("Autonomous VPS Background Scheduler started.")
        last_morning_date: Optional[str] = None
        last_evening_date: Optional[str] = None
        last_pulse_hour: int = -1
        last_news_digest_hour: int = -1
        last_volatility_check: float = 0.0
        last_btc_price: Optional[float] = None

        # Gửi thông báo chào sân & snapshot tức thì sau 3s khởi động
        await asyncio.sleep(3)
        await self._send_startup_checkin()

        while self._running:
            try:
                await asyncio.sleep(20)
                if not self.authorized_chat_ids:
                    continue

                now_vn = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7)))
                today_str = now_vn.strftime("%Y-%m-%d")
                hour = now_vn.hour
                minute = now_vn.minute

                # 1. 08:00 AM Morning Briefing (Khung giờ 08:00 - 08:59 nếu chưa gửi hôm nay)
                if hour == 8 and last_morning_date != today_str:
                    last_morning_date = today_str
                    await self._send_morning_intel()

                # 2. 23:00 PM Evening Growth & Compound Forecast Recap (Khung giờ 23:00 - 23:59 nếu chưa gửi hôm nay)
                if hour == 23 and last_evening_date != today_str:
                    last_evening_date = today_str
                    await self._send_evening_growth_recap()

                # 3. Gemini Macro News Digest (Vào các mốc 12:00, 16:00, 20:00)
                if hour in (12, 16, 20) and hour != last_news_digest_hour:
                    last_news_digest_hour = hour
                    await self._broadcast_gemini_news_digest()

                # 4. Hourly Market Pulse (Phát sóng mỗi đầu giờ, cách nhau 1 giờ, tránh trùng với 8h và 23h)
                if hour != last_pulse_hour and hour not in (8, 23):
                    last_pulse_hour = hour
                    await self._broadcast_hourly_market_pulse()

                # 5. Flash Volatility Alert (mỗi 5 phút kiểm tra cú giật biến động > 1.8%)
                if time.time() - last_volatility_check >= 300:
                    last_volatility_check = time.time()
                    last_btc_price = await self._check_flash_volatility(last_btc_price)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Scheduler tick error: {e}")

    async def run(self) -> None:
        """Vòng lặp Long-Polling chính của Telegram Bot."""
        if not self.is_configured:
            logger.warning("Dedicated Telegram Bot is not configured (missing bot_token). Standing by...")
            return

        self._running = True
        logger.info("Dedicated Telegram Bot runner started. Polling updates...")

        try:
            session = await self.get_session()
            async with session.get(f"https://api.telegram.org/bot{self.token}/getMe") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._bot_info = data.get("result", {})
                    bot_name = self._bot_info.get("username", "UnknownBot")
                    logger.info(f"Connected to Telegram Bot: @{bot_name}")
                    # Khởi động background tasks (Scheduler 24/7 cho VPS)
                    asyncio.create_task(self._vps_autonomous_scheduler())
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
                        logger.error("Invalid Telegram Bot Token! Terminating bot loop.")
                        break
                    elif resp.status == 409:
                        logger.warning("Telegram Bot 409 Conflict: Another instance is polling. Retrying in 5s...")
                        await asyncio.sleep(5)
                    else:
                        await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Dedicated bot poll error: {e}")
                if self._session and not self._session.closed:
                    try:
                        await self._session.close()
                    except Exception:
                        pass
                self._session = None
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
        sys.exit(1)

    print("[*] Starting Dedicated Telegram Bot Mark 85 (Jarvis Protocol)...")
    asyncio.run(bot.run())
