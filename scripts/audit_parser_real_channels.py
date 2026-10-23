import json
import sys
from decimal import Decimal
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding='utf-8')
from config.config import load_config
from core.models import SourceMetadata
from parser.signal_parser import SignalParser
from parser.validator import SignalValidator

def main():
    cfg = load_config()
    parser = SignalParser()
    validator = SignalValidator(cfg)
    meta = SourceMetadata(chat_id=1, message_id=1, telegram_timestamp=datetime.now(timezone.utc), received_at=datetime.now(timezone.utc))

    data18 = json.load(open('data/18_channels_admin_syntax_samples.json', encoding='utf-8'))
    print("=== AUDIT: data/18_channels_admin_syntax_samples.json ===")
    
    for cid, info in data18.items():
        name = info.get('channel_name')
        samples = info.get('samples', [])
        sig_count = 0
        parsed_ok = 0
        val_ok = 0
        issues = []

        for s in samples:
            txt = s.get('text', '')
            mid = s.get('mid')
            # Check if text is likely intended as a signal
            is_likely_signal = any(k in txt.upper() for k in ['ENTRY', 'ENTRIES', 'LONG', 'SHORT', 'BUY', 'SELL']) and \
                               any(k in txt.upper() for k in ['TARGET', 'TP', 'TAKE', 'PROFIT']) and \
                               any(k in txt.upper() for k in ['STOP', 'SL'])

            p = parser.parse(txt, meta)
            p_val, val = validator.validate_and_resolve(p)

            if is_likely_signal:
                sig_count += 1
                if val is not None:
                    parsed_ok += 1
                    val_ok += 1
                elif p.validation_status.value in ['PARSED', 'NEEDS_POLICY']:
                    parsed_ok += 1
                    issues.append((mid, p.validation_status.value, p_val.blocking_reason, txt[:80].replace('\n', ' ')))
                else:
                    issues.append((mid, p.validation_status.value, p.blocking_reason, txt[:80].replace('\n', ' ')))

        print(f"[{name}] Signals: {sig_count}/{len(samples)} | Parsed: {parsed_ok} | Validated: {val_ok}")
        for mid, st, r, sample in issues:
            print(f"   -> mid={mid} [{st}] {r} | sample: {sample}")

    print("\n=== AUDIT: data/extracted_channel_messages.json ===")
    data_ext = json.load(open('data/extracted_channel_messages.json', encoding='utf-8'))
    by_channel = {}
    for item in data_ext:
        title = item.get('channel_title', 'Unknown')
        by_channel.setdefault(title, []).append(item)

    for title, items in by_channel.items():
        sig_count = 0
        parsed_ok = 0
        val_ok = 0
        issues = []
        for item in items:
            txt = item.get('raw_text', '')
            mid = item.get('message_id')
            if 'RESULT' in txt.upper() or 'ACHIEVED' in txt.upper() or ('PROFIT' in txt.upper() and 'TARGET 1' in txt.upper()):
                continue
            is_likely_signal = any(k in txt.upper() for k in ['ENTRY', 'ENTRIES', 'BUY :', 'LONG', 'SHORT']) and \
                               any(k in txt.upper() for k in ['TARGET', 'TP', 'TAKE PROFIT']) and \
                               any(k in txt.upper() for k in ['STOP', 'SL', 'STOPLOSS'])

            if not is_likely_signal:
                continue

            sig_count += 1
            p = parser.parse(txt, meta)
            p_val, val = validator.validate_and_resolve(p)

            if val is not None:
                parsed_ok += 1
                val_ok += 1
            elif p.validation_status.value in ['PARSED', 'NEEDS_POLICY']:
                parsed_ok += 1
                issues.append((mid, p.validation_status.value, p_val.blocking_reason, txt[:80].replace('\n', ' ')))
            else:
                issues.append((mid, p.validation_status.value, p.blocking_reason, txt[:80].replace('\n', ' ')))

        print(f"[{title}] Signals: {sig_count}/{len(items)} | Parsed: {parsed_ok} | Validated: {val_ok}")
        for mid, st, r, sample in issues:
            print(f"   -> mid={mid} [{st}] {r} | sample: {sample}")

if __name__ == "__main__":
    main()
