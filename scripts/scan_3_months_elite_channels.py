import asyncio
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import json

sys.path.insert(0, os.path.abspath("."))
from telethon import TelegramClient
from config.config import load_config

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

config = load_config("config.yaml")
allowed_chats = config.telegram.allowed_chat_ids or []
sources_cfg = config.sources or {}

channel_names = {}
for cid in allowed_chats:
    s = sources_cfg.get(cid) or sources_cfg.get(str(cid))
    channel_names[cid] = s.name if s else f"Channel {cid}"

# Also include THE CRYPTO TRADER (-1001590450482) if tracked
if -1001590450482 not in channel_names:
    channel_names[-1001590450482] = "THE CRYPTO TRADER"

# 3 months cutoff: 90 days from now
now_utc = datetime.now(timezone.utc)
cutoff_3m = now_utc - timedelta(days=90)
print(f"Scanning 3 months from {cutoff_3m.strftime('%Y-%m-%d')} to {now_utc.strftime('%Y-%m-%d')}...")

async def main():
    client = TelegramClient("data/telegram_user", 28680296, "927e2da6e7d0ec3d97a79d11cc794e46")
    await client.connect()
    if not await client.is_user_authorized():
        print("Telegram not authorized!")
        return

    os.makedirs("data/photos_sample", exist_ok=True)

    channel_findings = {}

    for cid, name in channel_names.items():
        print(f"\n================ Scanning [{name}] (ID: {cid}) ================")
        safe_name = re.sub(r'[\\/*?:"<>|]', "", name).replace(" ", "_")
        ch_photo_dir = os.path.join("data/photos_sample", safe_name)
        os.makedirs(ch_photo_dir, exist_ok=True)

        total_msgs = 0
        photo_msgs = 0
        text_msgs = 0
        signals_found = 0
        downloaded_photos = []
        exchange_mentions = defaultdict(int)
        sample_signal_texts = []
        pnl_captions = []

        try:
            # Iterate messages over last 3 months (limit to 1000 per channel to be fast and respectful)
            count = 0
            async for msg in client.iter_messages(cid, offset_date=cutoff_3m, reverse=True):
                count += 1
                total_msgs += 1
                text = msg.text or ""

                # Check exchange text mentions
                t_lower = text.lower()
                for ex in ["binance", "bitunix", "bitget", "bybit", "kucoin", "bingx", "mexc", "okx", "gate.io"]:
                    if ex in t_lower:
                        exchange_mentions[ex] += 1

                has_photo = bool(msg.photo or msg.media)
                if has_photo:
                    photo_msgs += 1
                    # If this message is a PnL or trade result or signal card, save sample photo
                    is_pnl_or_trade = bool(re.search(r"(?:profit|target|hit|win|pnl|roi|leverage|\b[A-Z0-9]+USDT\b|\b[A-Z0-9]+\/USDT\b|entry|signal)", text, re.IGNORECASE))
                    if is_pnl_or_trade and len(downloaded_photos) < 4:
                        photo_filename = f"msg_{msg.id}.jpg"
                        photo_path = os.path.join(ch_photo_dir, photo_filename)
                        if not os.path.exists(photo_path):
                            try:
                                await msg.download_media(file=photo_path)
                                downloaded_photos.append({
                                    "mid": msg.id,
                                    "path": photo_path,
                                    "caption": text[:200]
                                })
                            except Exception as e_dl:
                                pass
                        else:
                            downloaded_photos.append({
                                "mid": msg.id,
                                "path": photo_path,
                                "caption": text[:200]
                            })

                if text:
                    text_msgs += 1
                    if any(w in text.upper() for w in ["LONG", "SHORT", "BUY", "SELL"]) and "USDT" in text.upper():
                        signals_found += 1
                        if len(sample_signal_texts) < 3:
                            sample_signal_texts.append({
                                "mid": msg.id,
                                "text": text
                            })
                    if any(w in text.upper() for w in ["PROFIT", "TARGET HIT", "ACHIEVED", "ROI"]):
                        if len(pnl_captions) < 3:
                            pnl_captions.append(text[:200])

                if count >= 800:
                    break

        except Exception as e:
            print(f"Error accessing {name}: {e}")

        print(f"  Total Msgs (3m): {total_msgs} | Photos: {photo_msgs} | Signals: {signals_found}")
        print(f"  Exchange Mentions in Text: {dict(exchange_mentions)}")
        print(f"  Photos downloaded: {len(downloaded_photos)}")

        channel_findings[cid] = {
            "name": name,
            "cid": cid,
            "total_msgs_3m": total_msgs,
            "photo_msgs": photo_msgs,
            "signals_found": signals_found,
            "exchange_mentions": dict(exchange_mentions),
            "downloaded_photos": downloaded_photos,
            "sample_signals": sample_signal_texts,
            "pnl_captions": pnl_captions
        }

    with open("data/3_months_elite_channels_scan.json", "w", encoding="utf-8") as f:
        json.dump(channel_findings, f, ensure_ascii=False, indent=2)

    print("\nSaved full scan results to data/3_months_elite_channels_scan.json")
    await client.disconnect()

asyncio.run(main())

