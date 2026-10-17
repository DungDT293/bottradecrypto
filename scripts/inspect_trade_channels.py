import json
import os
import sys
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

token = "3R1K5oS6cpat6A0u0iqKbJHyJyiB8wN-Eo4R-RIPy0U"
req = urllib.request.Request(
    "http://127.0.0.1:56749/api/telegram/dialogs",
    headers={"X-Session-Token": token}
)
res = urllib.request.urlopen(req)
data = json.loads(res.read().decode("utf-8"))
dialogs = {d["id"]: d for d in data.get("dialogs", [])}
folder = next(f for f in data.get("folders", []) if f["id"] == 107)

print("=== 12 KÊNH ĐƯỢC GHIM TRONG FOLDER 'KÈO TRADE' ===")
for cid in folder["pinned_chat_ids"]:
    d = dialogs.get(cid)
    title = d.get("title") if d else f"Unknown ({cid})"
    print(f"  📌 {title} (ID: {cid})")

print("\n=== 3 NHÓM ĐƯỢC GHIM TRÊN ĐẦU DANH SÁCH CHUNG ===")
for d in data.get("dialogs", []):
    if d.get("pinned"):
        print(f"  📌 {d.get('title')} (ID: {d.get('id')})")

