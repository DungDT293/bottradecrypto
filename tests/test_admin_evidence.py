from datetime import datetime, timezone

import pytest

from config.config import load_config
from services.admin_evidence import classify_media_claim, detect_media_kind
from storage.database import DatabaseManager, SignalRepository
from telegram.listener import TelegramSignalListener


class PhotoEvent:
    def __init__(self, text="", photo=True):
        self.chat_id = 1000
        self.id = 77
        self.raw_text = text
        self.date = datetime.now(timezone.utc)
        self.edit_date = None
        self.reply_to_msg_id = None
        self.sender_id = 999
        self.photo = object() if photo else None
        self.document = None
        self.media = self.photo


def test_binance_profit_claim_is_not_fill():
    evidence = classify_media_claim(
        "GTCUSDT Perpetual Binance Futures ROI +279.27% Referral Code 73416942",
        "photo",
    )
    assert evidence.exchange_claim == "BINANCE_FUTURES"
    assert evidence.verification_status == "CLAIM_ONLY"
    assert evidence.outcome == "UNVERIFIED"
    assert evidence.is_trade_fill is False
    assert evidence.has_referral_promotion is True


def test_generic_image_is_unverified():
    evidence = classify_media_claim("chart", "photo")
    assert evidence.exchange_claim is None
    assert evidence.verification_status == "UNVERIFIED"
    assert evidence.is_trade_fill is False


def test_media_signal_caption_never_creates_signal(tmp_path):
    db = DatabaseManager(str(tmp_path / "evidence.db"))
    config = load_config()
    config.telegram.allowed_chat_ids = [1000]
    listener = TelegramSignalListener(config, None, db)

    pytest.importorskip("pytest_asyncio")
    import asyncio
    asyncio.run(listener.handle_incoming_message(PhotoEvent(
        "BTC/USDT LONG Entry: 60000 SL: 58000 TP: 65000 Binance Futures ROI +1%"
    )))

    repo = SignalRepository(db)
    assert repo.get_signal_by_message(1000, 77) is None
    rows = repo.get_admin_evidence(1000, 77)
    assert len(rows) == 1
    assert rows[0]["verification_status"] == "CLAIM_ONLY"
    assert rows[0]["is_trade_fill"] == 0


def test_photo_detection_without_download():
    assert detect_media_kind(PhotoEvent()) == "photo"
    assert detect_media_kind(PhotoEvent(photo=False)) is None
