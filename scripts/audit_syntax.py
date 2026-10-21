import sys
import io
import json
import re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def audit_syntax_samples():
    print("=== AUDITING 18 CHANNELS ADMIN SYNTAX SAMPLES ===")
    with open('data/18_channels_admin_syntax_samples.json', 'r', encoding='utf-8') as f:
        samples = json.load(f)
    
    print(f"Number of channels in samples: {len(samples)}")
    
    exchanges = ['binance', 'bitunix', 'bybit', 'mexc', 'bitget', 'kucoin', 'okx', 'bingx', 'spot', 'futures']
    
    for cid, data in samples.items():
        name = data.get('channel_name', 'Unknown')
        print(f"\n" + "="*80)
        print(f"CHANNEL: {name} (ID: {cid})")
        
        # Look for exchange mentions in raw texts
        exchange_mentions = {ex: 0 for ex in exchanges}
        sample_msgs = data.get('samples', [])
        print(f"Total sample messages collected: {len(sample_msgs)}")
        
        symbols_found = set()
        
        for msg in sample_msgs:
            text = msg.get('text', '') if isinstance(msg, dict) else str(msg)
            text_lower = text.lower()
            for ex in exchanges:
                if ex in text_lower:
                    exchange_mentions[ex] += 1
            
            # Find symbols
            sym_matches = re.findall(r'#?([A-Z0-9]{2,10})[/\s_]?(USDT|USD|BUSD)', text, re.IGNORECASE)
            for m in sym_matches:
                symbols_found.add(f"{m[0].upper()}{m[1].upper()}")
                
        print("Exchange mentions in samples:", {k: v for k, v in exchange_mentions.items() if v > 0})
        print(f"Unique symbols sample (up to 15): {list(symbols_found)[:15]}")
        
        # Print 2-3 sample texts
        for i, msg in enumerate(sample_msgs[:3]):
            t = msg.get('text', '') if isinstance(msg, dict) else str(msg)
            # print first 250 chars of text
            t_clean = t.replace('\n', ' ')[:200]
            print(f"  [Sample {i+1}]: {t_clean}...")

if __name__ == '__main__':
    audit_syntax_samples()
