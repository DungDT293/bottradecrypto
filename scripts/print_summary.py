import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

with open('data/all_11_channels_3_months_classified.json', 'r', encoding='utf-8') as f:
    channels = json.load(f)

print(f"{'Kênh':<28} | {'Tổng':<6} | {'Kèo Hợp lệ':<12} | {'Kèo Lỗi/Lọc':<12} | {'TP/SL Update':<13} | {'Dụ VIP':<8} | {'QC Sàn':<8} | {'Tin/Bình luận':<13}")
print("-" * 115)

for c in channels:
    total = c['total_messages']
    valid_sig = c['valid_signals_count']
    invalid_sig = c['signals_count'] - valid_sig
    upd = c['categories']['TRADE_UPDATE']
    vip = c['categories']['VIP_BAIT']
    promo = c['categories']['EXCHANGE_PROMO']
    news = c['categories']['COMMENTARY_NEWS']
    print(f"{c['name'][:28]:<28} | {total:<6} | {valid_sig:<12} | {invalid_sig:<12} | {upd:<13} | {vip:<8} | {promo:<8} | {news:<13}")

print("\n" + "="*80)
print("CHI TIẾT MẪU TIN NHẮN TỪNG KÊNH:")
print("="*80)
for c in channels:
    print(f"\n👉 KÊNH: {c['name']} (ID: {c['id']})")
    print(f"   - Tỷ lệ kèo: {c['categories_pct']['SIGNAL']}% | Tỷ lệ cập nhật: {c['categories_pct']['TRADE_UPDATE']}% | Dụ VIP: {c['categories_pct']['VIP_BAIT']}% | QC Sàn: {c['categories_pct']['EXCHANGE_PROMO']}%")
    if c['signals_sample']:
        s = c['signals_sample'][-1]
        print(f"   - Mẫu kèo gần nhất: {s.get('side')} #{s.get('symbol')} | Entries: {s.get('entries')} | SL: {s.get('stop_loss')} | Status: {s.get('status')}")
    if c['vip_bait_sample']:
        v = c['vip_bait_sample'][-1]
        print(f"   - Mẫu Dụ VIP: {v['text'].strip()[:100]}...")
    if c['exchange_promo_sample']:
        p = c['exchange_promo_sample'][-1]
        print(f"   - Mẫu QC Sàn: {p['text'].strip()[:100]}...")
