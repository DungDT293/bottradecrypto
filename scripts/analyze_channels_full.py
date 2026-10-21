import json
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')

with open('data/3_months_elite_channels_scan.json', encoding='utf-8') as f:
    data = json.load(f)

print(f"{'CHANNEL NAME':<32} | {'CHANNEL ID':<15} | {'MSGS':<5} | {'PHOTOS':<6} | {'SIGS':<5} | {'EXCHANGE MENTIONS'}")
print("-" * 95)
for cid, v in data.items():
    name = v.get('name', '').encode('ascii', 'ignore').decode('ascii').strip()
    msgs = v.get('total_msgs_3m', 0)
    photos = v.get('photo_msgs', 0)
    sigs = v.get('signals_found', 0)
    ex = str(v.get('exchange_mentions', {}))
    print(f"{name:<32} | {cid:<15} | {msgs:<5} | {photos:<6} | {sigs:<5} | {ex}")
