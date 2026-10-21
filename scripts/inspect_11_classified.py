import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

with open("data/all_11_channels_3_months_classified.json", "r", encoding="utf-8") as f:
    data = json.load(f)

print(f"Total channels in classified JSON: {len(data)}")
for item in data:
    name = item.get("name", "Unknown")
    cid = item.get("id")
    total_msgs = item.get("total_messages", 0)
    sig_count = len(item.get("signals", []))
    upd_count = len(item.get("updates", []))
    status = item.get("status", "")
    print(f"• {name} (ID: {cid}) -> Msgs: {total_msgs}, Sigs: {sig_count}, Upds: {upd_count}, Status: {status}")

