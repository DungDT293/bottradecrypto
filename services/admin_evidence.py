"""Classify media-bearing Telegram messages without treating them as trade fills."""
from dataclasses import dataclass
import re
from typing import Any, Optional


@dataclass(frozen=True)
class AdminEvidence:
    evidence_type: str
    media_kind: str
    exchange_claim: Optional[str]
    confidence: str
    verification_status: str
    outcome: str
    is_trade_fill: bool
    has_referral_promotion: bool
    caption_has_result_markers: bool
    detail: str


_RESULT_MARKERS = re.compile(
    r"\b(?:roi|pnl|last\s+price|target\s+(?:achieved|hit)|"
    r"tp\d*\s*hit|all\s+tp(?:s)?\s+hit|winner|gain|result|closed(?:\s+in\s+profit)?)\b",
    re.IGNORECASE,
)
_BINANCE_MARKERS = re.compile(
    r"(?:binance\s+futures|binance[_\s-]?360|@binance[_\s-]?360|binance\.com)",
    re.IGNORECASE,
)
_REFERRAL_MARKERS = re.compile(
    r"(?:referral\s+code|invite\s+code|ref\.?\s*code|register|referral|bonus|qr\s*code)",
    re.IGNORECASE,
)
_BRAG_REGEX = re.compile(
    r"(?:"
    r"\b(?:ROI|PNL)\s*[:=]?\s*[\+\-]?\d+"
    r"|[\+\-]?\d+(?:\.\d+)?%\s*(?:ROI|PROFIT|GAIN)"
    r"|\b(?:BINANCE\s+FUTURES|BINANCE).*(?:ROI|PNL)"
    r"|\b(?:TARGET\s+(?:\d+\s+)?(?:ACHIEVED|HIT)|TP\d*\s*HIT|ALL\s+TP(?:S)?\s+HIT|CLOSED\s+IN\s+PROFIT|MASSIVE\s+PROFIT)\b"
    r")",
    re.IGNORECASE,
)


def is_brag_media_claim(raw_text: str) -> bool:
    """Return True if message text contains explicit profit/result bragging patterns."""
    if not raw_text:
        return False
    return bool(_BRAG_REGEX.search(raw_text))


def _document_is_image(document: Any) -> bool:
    mime = str(getattr(document, "mime_type", "") or "").lower()
    return mime.startswith("image/")


def detect_media_kind(event: Any) -> Optional[str]:
    """Inspect Telethon metadata only. Never downloads media."""
    if getattr(event, "photo", None) is not None:
        return "photo"
    document = getattr(event, "document", None)
    if document is not None and _document_is_image(document):
        return "image_document"
    media = getattr(event, "media", None)
    if media is not None:
        if _document_is_image(getattr(media, "document", None)):
            return "image_document"
        if getattr(media, "photo", None) is not None:
            return "photo"
    return None


def classify_media_claim(raw_text: str, media_kind: str) -> AdminEvidence:
    """Return conservative evidence labels; never infer a fill or realized PnL."""
    caption = raw_text or ""
    result_markers = bool(_RESULT_MARKERS.search(caption))
    binance = bool(_BINANCE_MARKERS.search(caption))
    referral = bool(_REFERRAL_MARKERS.search(caption))
    if result_markers or binance or referral:
        exchange_claim = "BINANCE_FUTURES" if binance else None
        confidence = "HIGH" if binance and (result_markers or referral) else "MEDIUM"
        evidence_type = "PROFIT_SCREENSHOT_CLAIM" if result_markers else "MEDIA_CLAIM"
        detail = "Media/caption claim; not exchange fill evidence"
    else:
        exchange_claim = None
        confidence = "UNKNOWN"
        evidence_type = "IMAGE_MESSAGE_UNVERIFIED"
        detail = "Image message without verifiable exchange/result markers"
    return AdminEvidence(
        evidence_type=evidence_type,
        media_kind=media_kind,
        exchange_claim=exchange_claim,
        confidence=confidence,
        verification_status="CLAIM_ONLY" if evidence_type != "IMAGE_MESSAGE_UNVERIFIED" else "UNVERIFIED",
        outcome="UNVERIFIED",
        is_trade_fill=False,
        has_referral_promotion=referral or binance,
        caption_has_result_markers=result_markers,
        detail=detail,
    )
