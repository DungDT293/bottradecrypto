import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

with open('data/all_9_channels_6_months_classified.json', 'r', encoding='utf-8') as f:
    channels = json.load(f)

print(f"{'KÊNH TELEGRAM':<28} | {'TỔNG TIN':<8} | {'KÈO HỢP LỆ':<12} | {'KÈO LỖI':<8} | {'TP/SL UPDATE':<14} | {'DỤ VIP':<9} | {'QC SÀN':<14} | {'TIN TỨC':<12}")
print("-" * 125)

for c in channels:
    total = c['total_messages']
    cats = c['categories']
    valid_sig = c['valid_signals_count']
    inv_sig = c['signals_count'] - valid_sig
    val_str = f"{valid_sig} ({round(valid_sig/total*100, 1)}%)"
    upd_str = f"{cats['TRADE_UPDATE']} ({round(cats['TRADE_UPDATE']/total*100, 1)}%)"
    vip_str = f"{cats['VIP_BAIT']} ({round(cats['VIP_BAIT']/total*100, 1)}%)"
    promo_str = f"{cats['EXCHANGE_PROMO']} ({round(cats['EXCHANGE_PROMO']/total*100, 1)}%)"
    news_str = f"{cats['COMMENTARY_NEWS']} ({round(cats['COMMENTARY_NEWS']/total*100, 1)}%)"
    print(f"{c['name'][:28]:<28} | {total:<8} | {val_str:<12} | {inv_sig:<8} | {upd_str:<14} | {vip_str:<9} | {promo_str:<14} | {news_str:<12}")

print("\n" + "=" * 90)
print("ĐÁNH GIÁ CHI TIẾT TỪNG KÊNH TRONG 6 THÁNG QUA:")
print("=" * 90)
for c in channels:
    print(f"\n👉 {c['name']} (ID: {c['id']})")
    print(f"   • Tổng tin 6 tháng: {c['total_messages']}")
    print(f"   • Tỷ lệ kèo chuẩn: {c['valid_signals_count']} kèo ({c['valid_signals_pct']}% tổng số kèo phát hiện)")
    print(f"   • Tin rác (VIP + Sàn ngoài): {c['categories']['VIP_BAIT'] + c['categories']['EXCHANGE_PROMO']} tin ({round((c['categories']['VIP_BAIT'] + c['categories']['EXCHANGE_PROMO'])/c['total_messages']*100, 1)}%)")
    if c['signals_sample']:
        s = c['signals_sample'][-1]
        print(f"   • Mẫu kèo gần nhất: {s.get('side')} #{s.get('symbol')} | Entries: {s.get('entries')} | SL: {s.get('stop_loss')} | TP: {s.get('targets')[:3]}")

