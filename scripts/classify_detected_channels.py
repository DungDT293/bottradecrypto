import sys
import json
import urllib.request
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

# Fetch Binance Futures symbols
url = 'https://fapi.binance.com/fapi/v1/exchangeInfo'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req, timeout=10) as resp:
    data = json.loads(resp.read().decode('utf-8'))
    binance_symbols = {s['symbol'] for s in data['symbols'] if s['status'] == 'TRADING'}

with open('data/detected_signal_channels_3days.json', 'r', encoding='utf-8') as f:
    channels = json.load(f)

print(f"Total Channels to classify: {len(channels)}")
print("=" * 80)

summary = []

for c in channels:
    cid = c['id']
    title = c['title']
    signals = c['signals']
    
    binance_supported_count = 0
    symbols_list = []
    
    has_valid_sl_count = 0
    has_valid_tp_count = 0
    
    for s in signals:
        sym = s['symbol']
        symbols_list.append(sym)
        # Check normalization
        clean_sym = sym.replace('/', '').upper()
        if not clean_sym.endswith('USDT'):
            clean_sym += 'USDT'
        if clean_sym in binance_symbols or sym in binance_symbols:
            binance_supported_count += 1
        if s.get('sl') and s['sl'] != 'None':
            has_valid_sl_count += 1
        if s.get('tps') and len(s['tps']) > 0 and s['tps'][0] != '0':
            has_valid_tp_count += 1

    total_sig = len(signals)
    binance_ratio = (binance_supported_count / total_sig) if total_sig > 0 else 0
    sl_ratio = (has_valid_sl_count / total_sig) if total_sig > 0 else 0
    tp_ratio = (has_valid_tp_count / total_sig) if total_sig > 0 else 0
    
    unique_symbols = sorted(list(set(symbols_list)))
    
    # Classify
    # Flags:
    # - If SL is missing or vague ("will update"): Low Quality
    # - If symbols are UNKNOWN or DEX coins: Low Quality
    # - If mirror channel: duplicate note
    classification = "UNKNOWN"
    reason = []
    
    if "Honey Crypto" in title or sl_ratio < 0.5:
        classification = "REJECT_SHILL_LOW_QUALITY"
        reason.append("Missing/invalid SL or vague targets (e.g. DCA/SL will update)")
    elif "UNKNOWN" in unique_symbols:
        classification = "NEEDS_PARSER_FIX_OR_REJECT"
        reason.append("Symbol parsing failed or non-standard format")
    elif binance_ratio < 0.5:
        classification = "REJECT_NON_BINANCE"
        reason.append(f"Most symbols not on Binance Futures ({binance_supported_count}/{total_sig})")
    elif total_sig >= 5 and sl_ratio >= 0.8 and binance_ratio >= 0.7:
        classification = "TIER_1_HIGH_POTENTIAL"
        reason.append(f"High activity ({total_sig} sigs/3d), Binance futures coverage ({binance_supported_count}/{total_sig}), full SL/TP")
    else:
        classification = "TIER_2_MODERATE_OR_LOW_FREQ"
        reason.append(f"Valid futures signals but lower frequency ({total_sig} sigs/3d) or moderate Binance match ({binance_supported_count}/{total_sig})")
        
    summary.append({
        "id": cid,
        "title": title,
        "total_signals_3d": total_sig,
        "binance_supported_count": binance_supported_count,
        "binance_ratio": round(binance_ratio, 2),
        "sl_ratio": round(sl_ratio, 2),
        "tp_ratio": round(tp_ratio, 2),
        "unique_symbols": unique_symbols,
        "classification": classification,
        "reason": "; ".join(reason),
        "sample_snippet": signals[0]['snippet'] if signals else ""
    })

# Print report
for item in summary:
    print(f"[{item['classification']}] {item['title']} (ID: {item['id']})")
    print(f"  Signals: {item['total_signals_3d']} | Binance Futures match: {item['binance_supported_count']}/{item['total_signals_3d']} ({item['binance_ratio']*100:.0f}%) | SL rate: {item['sl_ratio']*100:.0f}%")
    print(f"  Symbols: {', '.join(item['unique_symbols'])}")
    print(f"  Evaluation: {item['reason']}")
    print(f"  Sample: {item['sample_snippet'][:90]}...")
    print("-" * 80)

# Save classified output
with open('data/classified_candidate_channels.json', 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print("Saved classification to data/classified_candidate_channels.json")
