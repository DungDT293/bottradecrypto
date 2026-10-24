import sys
import json
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')

with open('data/detected_signal_channels_3days.json', 'r', encoding='utf-8') as f:
    channels = json.load(f)

print(f"Total detected signal channels: {len(channels)}")
print("="*80)

for i, c in enumerate(channels, 1):
    signals = c['signals']
    symbols = [s['symbol'] for s in signals]
    sides = [s['side'] for s in signals]
    side_counts = Counter(sides)
    sample_snippet = signals[0]['snippet'] if signals else ''
    sample_signal = signals[0] if signals else {}
    
    print(f"{i}. [{c['id']}] '{c['title']}'")
    print(f"   Signals (3d): {c['signals_count_3d']} | Total recent messages: {c['recent_activity_count']}")
    print(f"   Sides: {dict(side_counts)}")
    print(f"   Distinct Symbols ({len(set(symbols))}): {list(set(symbols))[:8]}")
    print(f"   Sample Snippet: {sample_snippet}")
    print(f"   Sample Parsed: Entry={sample_signal.get('entries')}, SL={sample_signal.get('sl')}, TP={sample_signal.get('tps')}, Lev={sample_signal.get('leverage')}")
    print("-" * 80)
