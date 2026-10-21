import json
import sys
import os
sys.path.insert(0, os.path.abspath('.'))
from datetime import datetime, timezone
from parser.signal_parser import SignalParser
from core.models import SourceMetadata

sys.stdout.reconfigure(encoding='utf-8')

with open('data/3_months_elite_channels_scan.json', encoding='utf-8') as f:
    data = json.load(f)

parser = SignalParser()

total_samples = 0
parsed_ok = 0
failed_samples = []

print(f"{'CHANNEL NAME':<30} | {'CHANNEL ID':<15} | {'TESTED':<7} | {'SUCCESS':<7} | {'RATE'}")
print("-" * 75)

for cid, v in data.items():
    name = v.get('name', '').encode('ascii', 'ignore').decode('ascii').strip()
    samples = v.get('sample_signals', [])
    if not samples:
        print(f"{name:<30} | {cid:<15} | 0       | 0       | N/A")
        continue
    
    ch_total = len(samples)
    ch_ok = 0
    for s in samples:
        txt = s.get('text', '')
        meta = SourceMetadata(
            chat_id=int(cid),
            message_id=int(s.get('mid', 1)),
            source_name=name,
            telegram_timestamp=datetime.now(timezone.utc)
        )
        res = parser.parse(txt, meta)
        if res.is_valid:
            ch_ok += 1
        else:
            failed_samples.append({
                'channel': name,
                'cid': cid,
                'mid': s.get('mid'),
                'text': txt,
                'errors': res.errors
            })
    total_samples += ch_total
    parsed_ok += ch_ok
    rate = f"{(ch_ok/ch_total)*100:.1f}%"
    print(f"{name:<30} | {cid:<15} | {ch_total:<7} | {ch_ok:<7} | {rate}")

print("-" * 75)
print(f"TOTAL: {parsed_ok}/{total_samples} ({(parsed_ok/total_samples)*100:.1f}%)")
print(f"FAILED COUNT: {len(failed_samples)}")

if failed_samples:
    print("\nSAMPLE FAILURES (first 5):")
    for f in failed_samples[:5]:
        print(f"--- Channel: {f['channel']} (mid: {f['mid']}) ---")
        print(f"Errors: {f['errors']}")
        lines = f['text'].strip().split('\n')
        print('\n'.join(lines[:10]))
        print("...")
