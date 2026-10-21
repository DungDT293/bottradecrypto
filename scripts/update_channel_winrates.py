import json
import os

scores_path = 'audit_output/channel_detailed_scores.json'
with open(scores_path, 'r', encoding='utf-8') as f:
    scores = json.load(f)

winrates_path = 'data/channel_winrates_6_months.json'
with open(winrates_path, 'r', encoding='utf-8') as f:
    orig = json.load(f)

orig_by_id = {item.get('id'): item for item in orig}

# Top 5 channels
top5_ids = [-1002007658025, -1001756316676, -1002052872813, -1001552004524, -1001370457350]

new_list = []
rank = 1

for sc in scores:
    cid = sc['cid']
    item = dict(orig_by_id.get(cid, {}))
    item['id'] = cid
    item['name'] = sc['name']
    item['winrate'] = sc['winrate']
    item['avg_sl_pct'] = sc['avg_sl']
    item['avg_tp1_pct'] = sc['avg_tp1']
    item['score'] = sc['total_score']
    item['rr'] = sc['rr']
    item['rank'] = rank
    
    if cid in top5_ids:
        item['tier'] = 'S'
        wr = sc['winrate']
        rr = sc['rr']
        tot = sc['total_score']
        item['verdict'] = f"Top 5 Tinh hoa: Thẩm định Binance M1 {wr}% Winrate, R:R 1:{rr}. Điểm chất lượng {tot}/100."
    elif cid in [-1001212188460, -1001519589508]:
        item['tier'] = 'D'
        item['verdict'] = "LOẠI BỎ: Hội nhóm bơm xả (Pump & Dump Syndicate) lừa đảo cộng đồng."
    elif cid in [-1001656921849]:
        item['tier'] = 'D'
        item['verdict'] = "LOẠI BỎ: Tỷ lệ Ghost Results 77.4% & Clickbait lùa nhóm VIP."
    elif cid in [-1001754095061, -1001553551852, -1001781413045]:
        item['tier'] = 'D'
        item['verdict'] = "LOẠI BỎ: Spam ảnh khoe lãi ảo 1 giây sau kèo, không an toàn."
    else:
        item['tier'] = 'C'
        wr = sc.get('winrate', 0)
        gap = sc.get('fake_gap', 0)
        item['verdict'] = f"Chưa đạt chuẩn Top 5 (Winrate {wr}%, Fake Gap {gap}%)."
    
    new_list.append(item)
    rank += 1

with open(winrates_path, 'w', encoding='utf-8') as f:
    json.dump(new_list, f, ensure_ascii=False, indent=2)

# Copy to AppData if exists
import shutil
appdata_path = os.path.expandvars(r"%APPDATA%\telegram_binance_signal_executor\data\channel_winrates_6_months.json")
if os.path.exists(os.path.dirname(appdata_path)):
    shutil.copyfile(winrates_path, appdata_path)

print(f"Successfully updated {len(new_list)} channels in {winrates_path}")

