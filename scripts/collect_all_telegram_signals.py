"""Read-only collection and classification of all accessible Telegram groups/channels.

Never starts TelegramSignalListener, never calls Binance, never sends Telegram actions,
and never writes the production runtime DB.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from telethon import TelegramClient, utils
from telethon.tl.functions.messages import GetDialogFiltersRequest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.config import load_config
from core.models import SourceMetadata
from parser.normalizer import normalize_text
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from parser.validator import SignalValidator


def find_session(config) -> str:
    base = config.telegram.session_name
    candidates = [
        Path(base if str(base).endswith(".session") else f"{base}.session"),
        Path(config.data_dir) / "telegram_user.session",
        Path(os.environ.get("APPDATA", "")) / "telegram_binance_signal_executor" / "telegram_user.session",
        Path(os.environ.get("APPDATA", "")) / "telegram_binance_signal_executor" / "data" / "telegram_user.session",
        Path(os.environ.get("LOCALAPPDATA", "")) / "telegram-binance-signal-executor" / "telegram_user.session",
        PROJECT_ROOT / "data" / "telegram_user.session",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.with_suffix("")) if candidate.suffix == ".session" else str(candidate)
    raise RuntimeError("No existing Telegram session file found")


def media_kind(message: Any) -> str | None:
    if getattr(message, "photo", None) is not None:
        return "photo"
    document = getattr(message, "document", None)
    if str(getattr(document, "mime_type", "") or "").lower().startswith("image/"):
        return "image_document"
    return None


def folder_registry(filters: list[Any]) -> tuple[dict[int, list[str]], dict[int, set[int]]]:
    folders: dict[int, list[str]] = {}
    excluded: dict[int, set[int]] = {}
    for folder in filters:
        title = getattr(getattr(folder, "title", None), "text", getattr(folder, "title", ""))
        title = str(title or "")
        if not re.search(r"trade|kèo", title, re.IGNORECASE):
            continue
        folder_id = getattr(folder, "id", None)
        if folder_id is None:
            continue
        ids: list[int] = []
        for peer in list(getattr(folder, "pinned_peers", []) or []) + list(getattr(folder, "include_peers", []) or []):
            try:
                ids.append(utils.get_peer_id(peer))
            except Exception:
                continue
        for cid in ids:
            folders.setdefault(cid, []).append(title or f"Folder {folder_id}")
        for peer in getattr(folder, "exclude_peers", []) or []:
            try:
                excluded.setdefault(folder_id, set()).add(utils.get_peer_id(peer))
            except Exception:
                pass
    return folders, excluded


def classify_message(raw_text: str, chat_id: int, message_id: int, timestamp: datetime, parser: SignalParser, update_parser: ChannelUpdateParser, validator: SignalValidator, source_override: Any) -> dict[str, Any]:
    normalized = normalize_text(raw_text or "")
    update_type, update_value, update_detail = update_parser.parse_update(normalized) if normalized else (None, None, None)
    item: dict[str, Any] = {
        "category": "UNKNOWN" if not normalized else "COMMENTARY_NEWS",
        "update_type": getattr(update_type, "value", None),
        "update_value": str(update_value) if update_value is not None else None,
        "update_detail": update_detail,
        "parser_status": None,
        "symbol": None,
        "side": None,
        "entries": [],
        "stop_loss": None,
        "take_profits": [],
        "leverage_requested": None,
        "validation_reason": None,
    }
    if update_type is not None and getattr(update_type, "value", "UNKNOWN") != "UNKNOWN":
        item["category"] = "TRADE_UPDATE"
        if update_type.value in {"COMMENTARY", "CORRECT_SIGNAL"}:
            item["category"] = "COMMENTARY_NEWS"
        return item
    if not normalized:
        return item
    try:
        meta = SourceMetadata(chat_id=chat_id, message_id=message_id, telegram_timestamp=timestamp)
        parsed = parser.parse(raw_text, meta)
        item.update({
            "symbol": parsed.symbol_candidate,
            "side": parsed.side.value if parsed.side else None,
            "entries": [str(x) for x in parsed.entries],
            "stop_loss": str(parsed.stop_loss) if parsed.stop_loss else None,
            "take_profits": [str(x) for x in parsed.take_profits],
            "leverage_requested": parsed.leverage_requested,
            "parser_status": parsed.validation_status.value,
            "validation_reason": parsed.blocking_reason,
        })
        if parsed.symbol_candidate:
            item["category"] = "SIGNAL"
            _, validated = validator.validate_and_resolve(parsed, source_override)
            if validated is not None:
                item["validated"] = True
            else:
                item["validated"] = False
        if re.search(r"(?:join|vip|premium|referral|invite|bitunix|mexc|bingx|bitget|bybit|okx)", normalized, re.I):
            item["category"] = "EXCHANGE_PROMO" if not parsed.symbol_candidate else item["category"]
    except Exception as exc:
        item["parser_status"] = "ERROR"
        item["validation_reason"] = f"{type(exc).__name__}: {exc}"
    return item


async def collect(args: argparse.Namespace) -> Path:
    config = load_config()
    session = os.environ.get("TELEGRAM_READONLY_SESSION") or find_session(config)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.output or PROJECT_ROOT / "audit_output" / f"telegram_understanding_{stamp}")
    out.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    messages_path = out / "MESSAGES_CLASSIFIED.jsonl"
    manifest_path = out / "COLLECTION_REPORT.json"
    parser = SignalParser()
    update_parser = ChannelUpdateParser()
    validator = SignalValidator(config)
    client = TelegramClient(session, config.telegram.api_id, config.telegram.api_hash)
    summary: dict[str, Any] = {"started_utc": datetime.now(timezone.utc).isoformat(), "days": args.days, "cutoff_utc": cutoff.isoformat(), "read_only": True, "binance_calls": False, "telegram_write_calls": False, "chats": [], "counts": {}, "errors": []}
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session is not authorized")
        raw_filters = await client(GetDialogFiltersRequest())
        filters = getattr(raw_filters, "filters", raw_filters if isinstance(raw_filters, list) else [])
        folder_ids, _ = folder_registry(filters)
        dialogs = await client.get_dialogs(limit=args.max_dialogs)
        targets = [d for d in dialogs if (d.is_channel or d.is_group) and folder_ids.get(d.id)]
        summary["scope"] = "trade_folders_only"
        summary["folder_filter"] = "folder title matched trade or kèo"
        summary["chats"] = [{"chat_id": d.id, "title": d.title, "is_channel": bool(d.is_channel), "is_group": bool(d.is_group), "folders": folder_ids.get(d.id, [])} for d in targets]
        counts: dict[str, int] = {}
        total = 0
        per_chat_counts: dict[str, int] = {}
        for dialog in targets:
            source_override = config.sources.get(dialog.id)
            chat_total = 0
            try:
                async for msg in client.iter_messages(dialog.entity):
                    if msg.date and msg.date < cutoff:
                        break
                    if chat_total >= args.max_messages_per_dialog:
                        break
                    chat_total += 1
                    total += 1
                    raw = msg.raw_text or ""
                    ts = msg.date or datetime.now(timezone.utc)
                    classification = classify_message(raw, dialog.id, msg.id, ts, parser, update_parser, validator, source_override)
                    record = {
                        "chat_id": dialog.id,
                        "chat_title": dialog.title,
                        "folders": folder_ids.get(dialog.id, []),
                        "message_id": msg.id,
                        "sender_id": getattr(msg, "sender_id", None),
                        "telegram_timestamp": ts.isoformat(),
                        "edit_timestamp": msg.edit_date.isoformat() if getattr(msg, "edit_date", None) else None,
                        "reply_to_msg_id": getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None),
                        "media_kind": media_kind(msg),
                        "text_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                        "raw_text": raw,
                        "classification": classification,
                    }
                    with messages_path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                    category = classification.get("category", "UNKNOWN")
                    counts[category] = counts.get(category, 0) + 1
                per_chat_counts[str(dialog.id)] = chat_total
            except Exception as exc:
                summary["errors"].append({"chat_id": dialog.id, "title": dialog.title, "error": f"{type(exc).__name__}: {exc}"})
                per_chat_counts[str(dialog.id)] = chat_total
        summary["counts"] = counts
        summary["per_chat_counts"] = per_chat_counts
        summary["total_messages"] = total
        summary["coverage_complete_per_dialog"] = all(v < args.max_messages_per_dialog for v in per_chat_counts.values())
    finally:
        await client.disconnect()
    summary["finished_utc"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "COLLECTION_REPORT.md").write_text(
        f"# Telegram collection\n\nWindow: {args.days} days\n\nTotal messages: {summary.get('total_messages', 0)}\n\n"
        f"Read-only: yes\nBinance calls: no\nTelegram write calls: no\n\nCounts:\n```json\n{json.dumps(counts, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only all-dialog Telegram signal collector")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--max-dialogs", type=int, default=500)
    ap.add_argument("--max-messages", type=int, default=100000)
    ap.add_argument("--max-messages-per-dialog", type=int, default=20000)
    ap.add_argument("--output")
    print(asyncio.run(collect(ap.parse_args())))

if __name__ == "__main__":
    main()
