import sqlite3
import difflib
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

conn = sqlite3.connect('data/trading_state.db')
c = conn.cursor()

def inspect_edits_for_channel(cid, channel_name):
    print(f"\n{'='*70}\nINSPECTING EDITED MESSAGES FOR: {channel_name} ({cid})\n{'='*70}")
    
    # Find message_ids with multiple versions
    c.execute("""
        SELECT message_id, COUNT(*) as vcnt
        FROM message_versions
        WHERE chat_id = ?
        GROUP BY message_id
        HAVING vcnt > 1
        LIMIT 10
    """, (cid,))
    mids = c.fetchall()
    
    if not mids:
        print("  No multiple versions found in message_versions for this chat.")
        return
        
    for mid, vcnt in mids[:4]:
        c.execute("""
            SELECT version, is_edit, event_date, raw_text
            FROM message_versions
            WHERE chat_id = ? AND message_id = ?
            ORDER BY version ASC
        """, (cid, mid))
        versions = c.fetchall()
        print(f"\n--- Message ID #{mid} ({vcnt} versions) ---")
        for v, is_ed, ev_dt, text in versions:
            t_brief = (text or '').replace('\n', ' ')[:150]
            print(f"  [v{v} | edit={is_ed} | {ev_dt}]: {t_brief}...")

inspect_edits_for_channel(-1002052872813, "CRYPTO LEOPARD'S")
inspect_edits_for_channel(-1002007658025, "THE WOLF (CRYPTO)®")
inspect_edits_for_channel(-1001652601224, "Crypto World Updates")
inspect_edits_for_channel(-1001756316676, "Boom_Boom_Billionaires")
