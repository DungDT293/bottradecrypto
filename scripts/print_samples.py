import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('data/3_months_elite_channels_scan.json', encoding='utf-8') as f:
    data = json.load(f)

for cid, v in data.items():
    name = v.get('name', '').encode('ascii', 'ignore').decode('ascii').strip()
    samples = v.get('sample_signals', [])
    print(f"\n=======================================================")
    print(f"CHANNEL: {name} ({cid})")
    print(f"Total potential signals found: {v.get('signals_found', 0)}")
    print(f"=======================================================")
    if not samples:
        print("  [NO SAMPLES FOUND]")
    for i, s in enumerate(samples[:2], 1):
        print(f"--- Sample {i} (msg_id: {s.get('mid')}) ---")
        text = s.get('text', '')
        lines = text.strip().split('\n')
        print('\n'.join(lines[:18]))
        if len(lines) > 18:
            print("  ... (truncated)")
