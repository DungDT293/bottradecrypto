import json
import os
import sys
import time
import urllib.request
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SESSION_TOKEN = "3R1K5oS6cpat6A0u0iqKbJHyJyiB8wN-Eo4R-RIPy0U"
API_BASE = "http://127.0.0.1:56749/api"

def make_req(endpoint: str, payload: dict = None, method: str = "GET"):
    url = f"{API_BASE}{endpoint}"
    data = json.dumps(payload).encode("utf-8") if payload else None
    headers = {"X-Session-Token": SESSION_TOKEN}
    if payload:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    print("=" * 70)
    print("🚀 BẮT ĐẦU QUÉT TIN NHẮN 3 THÁNG GẦN NHẤT CỦA CÁC NHÓM ĐƯỢC GHIM")
    print("=" * 70)

    # 1. Fetch all dialogs and folders to find pinned channels
    print("[1] Lấy danh sách các nhóm và thư mục từ Telegram...")
    dialogs_resp = make_req("/telegram/dialogs")
    dialogs = {d["id"]: d for d in dialogs_resp.get("dialogs", [])}
    folders = dialogs_resp.get("folders", [])

    pinned_targets = {}

    # Pinned channels in folder 'Kèo trade'
    trade_folder = next((f for f in folders if "kèo" in f.get("title", "").lower() or "trade" in f.get("title", "").lower()), None)
    if trade_folder:
        for cid in trade_folder.get("pinned_chat_ids", []):
            d = dialogs.get(cid)
            title = d.get("title") if d else f"Channel_{cid}"
            pinned_targets[cid] = f"[Kèo Trade] {title}"

    # Global pinned dialogs
    for d in dialogs_resp.get("dialogs", []):
        if d.get("pinned"):
            cid = d["id"]
            if cid not in pinned_targets:
                pinned_targets[cid] = f"[Ghim Chung] {d.get('title')}"

    print(f"\n[2] Đã xác định được {len(pinned_targets)} kênh/nhóm được ghim:")
    for cid, name in pinned_targets.items():
        print(f"    📌 {name} (ID: {cid})")

    # 2. Iterate and collect 90 days of messages
    print(f"\n[3] Bắt đầu thu thập dữ liệu 3 tháng (90 ngày) cho từng nhóm...")
    total_messages_collected = 0
    total_signals_detected = 0
    total_updates_recorded = 0
    channel_results = []

    for idx, (cid, name) in enumerate(pinned_targets.items(), 1):
        print(f"\n--> [{idx}/{len(pinned_targets)}] Đang quét: {name} (ID: {cid})...")
        try:
            start_t = time.time()
            res = make_req(
                "/telegram/collect-history",
                payload={"chat_id": cid, "days": 90, "limit": 1500},
                method="POST"
            )
            elapsed = time.time() - start_t

            count = res.get("count", 0)
            sig_count = res.get("signals_detected", 0)
            upd_count = res.get("updates_recorded", 0)

            total_messages_collected += count
            total_signals_detected += sig_count
            total_updates_recorded += upd_count

            channel_results.append({
                "chat_id": cid,
                "name": name,
                "messages": count,
                "signals": sig_count,
                "updates": upd_count,
                "status": "SUCCESS"
            })
            print(f"    ✅ Thu thập {count} tin | {sig_count} tín hiệu | {upd_count} cập nhật | {elapsed:.1f}s")
        except Exception as e:
            print(f"    ⚠️ Lỗi khi quét {name}: {e}")
            channel_results.append({
                "chat_id": cid,
                "name": name,
                "messages": 0,
                "signals": 0,
                "updates": 0,
                "status": f"FAILED: {e}"
            })
        
        # Brief pause to respect Telegram flood rate limit
        time.sleep(1.5)

    print("\n" + "=" * 70)
    print("🎉 HOÀN TẤT THU THẬP DỮ LIỆU 3 THÁNG TOÀN BỘ CÁC NHÓM GHIM!")
    print("=" * 70)
    print(f"   • Tổng tin nhắn đã nạp thêm: {total_messages_collected}")
    print(f"   • Tổng tín hiệu phát hiện:   {total_signals_detected}")
    print(f"   • Tổng cập nhật admin:       {total_updates_recorded}")
    print("\nBảng chi tiết từng nhóm:")
    for r in channel_results:
        print(f"   - {r['name']}: {r['messages']} tin | {r['signals']} tín hiệu | {r['updates']} updates [{r['status']}]")

if __name__ == "__main__":
    main()

