import sqlite3
import os
from datetime import datetime

sig_id = "sig_reentry_stx_cryptomonk_cb8ea8"
now_iso = datetime.utcnow().isoformat()

db_paths = [
    "data/trading_state.db",
    os.path.expandvars(r"%LOCALAPPDATA%\telegram-binance-signal-executor\data\trading_state.db"),
]

for db in db_paths:
    if not os.path.exists(db):
        continue
    conn = sqlite3.connect(db)
    c = conn.cursor()
    
    # 1. Update signal state to CLOSED
    c.execute(
        "UPDATE signals SET state = 'CLOSED', updated_at = ? WHERE signal_id = ?",
        (now_iso, sig_id)
    )
    
    # 2. Update SL order to FILLED
    c.execute(
        """
        UPDATE orders SET status = 'FILLED', filled_quantity = 182.0, avg_fill_price = 0.3404, updated_at = ?
        WHERE signal_id = ? AND is_algo = 1
        """,
        (now_iso, sig_id)
    )
    
    # 3. Update TP orders to CANCELED
    c.execute(
        """
        UPDATE orders SET status = 'CANCELED', updated_at = ?
        WHERE signal_id = ? AND is_reduce_only = 1 AND is_algo = 0
        """,
        (now_iso, sig_id)
    )
    
    # 4. Insert timeline event
    try:
        c.execute(
            """
            INSERT INTO signal_timeline (signal_id, event_type, details, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                sig_id,
                "STOP_LOSS_FILLED",
                "STXUSDT đã chạm SL trên sàn Binance tại 0.3404. Lỗ thực tế: -2.31 USDT (-2.00% vốn, tuân thủ kỷ luật rủi ro <= 2.5%). Vốn ký quỹ còn lại đã tự động hồi về ví khả dụng.",
                now_iso
            )
        )
    except Exception:
        pass
        
    conn.commit()
    conn.close()
    print(f"Synced DB: {db}")

