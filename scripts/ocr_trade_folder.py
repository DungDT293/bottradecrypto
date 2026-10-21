"""Read-only OCR scan of Telegram Trade folders; never parses or trades signals."""
import argparse
import asyncio
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from telethon import TelegramClient, utils
from telethon.tl.functions.messages import GetDialogFiltersRequest

from config.config import load_config

EXCHANGES = {
    "BINANCE_FUTURES": re.compile(r"binance[ _-]*(?:futures|360)|@binance[_-]?360|binance\.com", re.I),
    "BYBIT": re.compile(r"\bbybit\b", re.I), "OKX": re.compile(r"\bokx\b", re.I),
    "BITGET": re.compile(r"\bbitget\b", re.I), "MEXC": re.compile(r"\bmexc\b", re.I),
    "BINGX": re.compile(r"\bbingx\b", re.I),
}
RESULT_MARKERS = re.compile(r"\b(?:roi|pnl|profit|gain|last price|entry price|target|tp\d*|closed|winner|referral|invite)\b", re.I)
REFERRAL_MARKERS = re.compile(r"\b(?:referral|ref\.?\s*code|invite\s*code|bonus|register|qr\s*code)\b", re.I)


def require_tesseract() -> str:
    path = shutil.which("tesseract")
    if not path:
        raise RuntimeError("Tesseract OCR executable not found on PATH; install it locally, then rerun.")
    subprocess.run([path, "--version"], check=True, capture_output=True, text=True, timeout=10)
    return path


def classify_ocr(text: str) -> dict[str, Any]:
    exchange = next((name for name, rx in EXCHANGES.items() if rx.search(text)), None)
    result = bool(RESULT_MARKERS.search(text)); referral = bool(REFERRAL_MARKERS.search(text))
    return {"exchange_claim": exchange, "confidence": "HIGH" if exchange and (result or referral) else ("MEDIUM" if exchange else "UNKNOWN"), "evidence_type": "PROFIT_SCREENSHOT_CLAIM" if result else "IMAGE_MESSAGE_UNVERIFIED", "verification_status": "CLAIM_ONLY" if result or exchange or referral else "UNVERIFIED", "outcome": "UNVERIFIED", "is_trade_fill": False, "has_referral_promotion": referral or bool(exchange)}


def media_kind(message: Any) -> str | None:
    if getattr(message, "photo", None) is not None: return "photo"
    document = getattr(message, "document", None)
    if str(getattr(document, "mime_type", "") or "").lower().startswith("image/"): return "image_document"
    return None


async def trade_chats(client: TelegramClient) -> list[dict[str, Any]]:
    raw = await client(GetDialogFiltersRequest()); filters = getattr(raw, "filters", raw if isinstance(raw, list) else [])
    ids: dict[int, str] = {}
    for folder in filters:
        title = getattr(getattr(folder, "title", None), "text", getattr(folder, "title", ""))
        if not re.search(r"trade|kèo", str(title), re.I): continue
        excluded = {utils.get_peer_id(p) for p in (getattr(folder, "exclude_peers", []) or [])}
        for peer in list(getattr(folder, "pinned_peers", []) or []) + list(getattr(folder, "include_peers", []) or []):
            cid = utils.get_peer_id(peer)
            if cid not in excluded: ids[cid] = str(title)
    dialogs = {d.id: d for d in await client.get_dialogs(limit=500)}
    return [{"chat_id": cid, "title": getattr(dialogs.get(cid), "title", title)} for cid, title in ids.items()]


async def scan(args: argparse.Namespace) -> Path:
    tesseract = require_tesseract(); config = load_config()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"); out = Path(args.output or Path("audit_output") / f"ocr_trade_folder_{stamp}")
    images = out / "images"; texts = out / "ocr_text"; images.mkdir(parents=True, exist_ok=True); texts.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days); manifest_path = out / "manifest.jsonl"; records = []
    client = TelegramClient(str(Path(config.telegram.session_name)), config.telegram.api_id, config.telegram.api_hash); await client.connect()
    try:
        if not await client.is_user_authorized(): raise RuntimeError("Telegram session is not authorized.")
        chats = await trade_chats(client); count = 0
        for chat in chats:
            entity = await client.get_entity(chat["chat_id"])
            async for msg in client.iter_messages(entity):
                if msg.date and msg.date < cutoff: break
                kind = media_kind(msg)
                if not kind: continue
                if count >= args.max_messages: break
                count += 1; record = {"chat_id": chat["chat_id"], "chat_title": chat["title"], "message_id": msg.id, "date": msg.date.isoformat() if msg.date else None, "media_kind": kind, "status": "pending"}
                try:
                    path = await msg.download_media(file=str(images))
                    if not path or Path(path).stat().st_size > args.max_image_bytes: record["status"] = "skipped_too_large"
                    else:
                        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest(); ocr = subprocess.run([tesseract, str(path), "stdout", "--dpi", "300"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=args.ocr_timeout)
                        if ocr.returncode: raise RuntimeError(ocr.stderr.strip() or f"tesseract exit {ocr.returncode}")
                        raw_ocr = ocr.stdout[:args.max_text]; (texts / f"{chat['chat_id']}_{msg.id}.txt").write_text(raw_ocr, encoding="utf-8")
                        record.update(classify_ocr(raw_ocr + "\n" + (msg.raw_text or "")))
                        record.update({"status": "downloaded", "sha256": digest, "ocr_text": raw_ocr, "caption": msg.raw_text or ""})
                except Exception as exc: record.update({"status": "error", "error": str(exc)[:300]})
                records.append(record)
                with manifest_path.open("a", encoding="utf-8") as f: f.write(json.dumps(record, ensure_ascii=False) + "\n")
    finally: await client.disconnect()
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "window_days": args.days, "cutoff_utc": cutoff.isoformat(), "records": len(records), "claim_only": sum(r.get("verification_status") == "CLAIM_ONLY" for r in records), "errors": sum(r.get("status") == "error" for r in records), "no_trade_actions": True, "no_binance_calls": True, "output": str(out)}
    (out / "OCR_REPORT.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"); return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only OCR scan of Telegram Trade folder images"); parser.add_argument("--days", type=int, default=90); parser.add_argument("--max-messages", type=int, default=5000); parser.add_argument("--max-image-bytes", type=int, default=15_000_000); parser.add_argument("--ocr-timeout", type=int, default=30); parser.add_argument("--max-text", type=int, default=20_000); parser.add_argument("--output"); print(asyncio.run(scan(parser.parse_args())))


if __name__ == "__main__": main()
