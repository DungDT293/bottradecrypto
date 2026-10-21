import sys
import os
sys.path.insert(0, os.path.abspath("."))
import sqlite3
import json
import re
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from config.config import load_config
from core.enums import EntryMode, MarginMode, PositionSide, SignalState, FieldSource
from core.models import ParsedSignal, SourceMetadata
from parser.normalizer import normalize_text
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

db_p = r"C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\data\trading_state.db"
conn = sqlite3.connect(db_p)
conn.row_factory = sqlite3.Row

config = load_config("config.yaml")
allowed_chats = config.telegram.allowed_chat_ids or []
sources_cfg = config.sources or {}

channel_names = {}
for cid in allowed_chats:
    s = sources_cfg.get(cid) or sources_cfg.get(str(cid))
    channel_names[cid] = s.name if s else f"Channel {cid}"

class EnhancedSignalParser:
    def normalize(self, text: str) -> str:
        t = normalize_text(text)
        # Remove thousand separator in numbers like 63,100 -> 63100, 2,440 -> 2440
        while re.search(r"\b(\d{1,3}),(\d{3})\b", t):
            t = re.sub(r"\b(\d{1,3}),(\d{3})\b", r"\1\2", t)
        return t

    def parse_symbol(self, text: str):
        # Trade: #ASTER/USDT
        m_trade = re.search(r"Trade\s*[:\-]?\s*#?([A-Za-z0-9]{2,12})\s*\/\s*([A-Za-z0-9]+)", text, re.IGNORECASE)
        if m_trade:
            b, q = m_trade.group(1).upper(), m_trade.group(2).upper()
            if q == "USDT": return f"{b}/USDT", f"{b}USDT", None
            
        m_slash = re.search(r"[$#]?([A-Za-z0-9]+)\s*\/\s*([A-Za-z0-9]+)", text)
        if m_slash:
            base, quote = m_slash.group(1).upper(), m_slash.group(2).upper()
            if quote == "USDT": return f"{base}/USDT", f"{base}USDT", None
            else: return f"{base}/{quote}", None, f"Quote asset '{quote}' khong phai USDT."

        m_usdt = re.search(r"(?:^|[\s\$#])([A-Za-z0-9]{1,12})USDT\b", text, re.IGNORECASE)
        if m_usdt:
            base = m_usdt.group(1).upper()
            return f"{base}USDT", f"{base}USDT", None

        m_coin = re.search(r"(?:COIN|Coin|PAIR|Pair)\s*[:#-]?\s*[$#]?([A-Za-z0-9]{2,10})\b", text)
        if m_coin:
            base = m_coin.group(1).upper()
            if base not in ["FREE", "VIP", "LONG", "SHORT", "BUY", "SELL", "USDT"]:
                return f"{base}/USDT", f"{base}USDT", None

        m_hash = re.search(r"#([A-Za-z0-9]{2,12})\s*(?:\|\s*)?(?:SHORT|LONG|BUY|SELL|\bSETUP\b)", text, re.IGNORECASE)
        if m_hash:
            base = m_hash.group(1).upper()
            if base not in ["FREE", "VIP", "LONG", "SHORT", "BUY", "SELL", "USDT", "SETUP", "TARGET", "STOP"]:
                return f"{base}/USDT", f"{base}USDT", None

        return "UNKNOWN", None, "Khong tim thay symbol hop le"

    def parse_side(self, text: str):
        has_short_header = bool(re.search(r"(?:#SHORT|\bSHORT\b|Position:\s*SHORT|Direction\s*:\s*SHORT|\(SHORT\)|SHORT\s*ZONE|SHORT\s*ENTRY)", text, re.IGNORECASE))
        has_long_header = bool(re.search(r"(?:#LONG|\bLONG\b|Position:\s*LONG|Direction\s*:\s*LONG|\(LONG\)|LONG\s*ZONE|LONG\s*ENTRY)", text, re.IGNORECASE))
        has_buy_entry = bool(re.search(r"\bBUY\s*:\s*\n?\s*\d+\)", text, re.IGNORECASE))
        has_sell_entry = bool(re.search(r"\bSELL\s*:\s*\n?\s*\d+\)", text, re.IGNORECASE))

        if (has_short_header and has_buy_entry) or (has_long_header and has_sell_entry):
            return PositionSide.SHORT if has_short_header else PositionSide.LONG, "Mau thuan huong lenh"
        if has_short_header: return PositionSide.SHORT, None
        if has_long_header: return PositionSide.LONG, None
        if has_buy_entry: return PositionSide.LONG, None
        if has_sell_entry: return PositionSide.SHORT, None
        return None, None

    def parse_entries(self, text: str):
        # 1. Range pattern
        m_range = re.search(
            r"(?:Entries|Entry|ENTERY|Take Entries|LONG\s*ZONE|SHORT\s*ZONE|BUY\s*ZONE|SELL\s*ZONE|ZONE|LONG\s*ENTRY|SHORT\s*ENTRY|BUY\s*ENTRY|SELL\s*ENTRY)[\s\w]*[:\=]\s*\[?\s*-?\s*\$?([\d\.]+)\s*(?:-|–|TO|to|:)\s*\$?([\d\.]+)\s*\]?",
            text,
            re.IGNORECASE
        )
        if m_range:
            try:
                p1, p2 = Decimal(m_range.group(1)), Decimal(m_range.group(2))
                return [p1, p2], EntryMode.RANGE, None, False
            except InvalidOperation:
                pass

        # 2. Dual Entry
        m_dual = re.search(r"ENTRY\s*(?:PRICE|TARGET)?\s*:\s*\$?([\d\.]+).*?(?:2nd|second)\s*ENTRY\s*:\s*\$?([\d\.]+)", text, re.IGNORECASE | re.DOTALL)
        if m_dual:
            try:
                return [Decimal(m_dual.group(1)), Decimal(m_dual.group(2))], EntryMode.MULTIPLE, None, False
            except InvalidOperation:
                pass

        # 3. Explicit numbered entries
        m_num = re.findall(r"(?:Entry\s*\d+|\d+(?:st|nd|rd|th)\s*ENTRY)\s*[:\-\>\s\u27a1\ufe0f]*\$?([\d\.]+)", text, re.IGNORECASE)
        if len(m_num) >= 2:
            try:
                return [Decimal(p) for p in m_num], EntryMode.MULTIPLE, None, False
            except InvalidOperation:
                pass
        elif len(m_num) == 1:
            try:
                return [Decimal(m_num[0])], EntryMode.SINGLE, None, False
            except InvalidOperation:
                pass

        # 4. Entry Targets section
        m_sec = re.search(r"Entry\s*Targets?\s*:\s*\n*(.*?)(?=\n\s*(?:Take-Profit|Targets?|Stop)\b|\Z)", text, re.IGNORECASE | re.DOTALL)
        if m_sec:
            sec_nums = re.findall(r"^\s*\d+[\)\.]\s*(?:[^\d\$\.]*)\s*\$?([\d\.]+)", m_sec.group(1), re.MULTILINE)
            if len(sec_nums) >= 2:
                try:
                    return [Decimal(p) for p in sec_nums], EntryMode.MULTIPLE, None, False
                except InvalidOperation:
                    pass
            elif len(sec_nums) == 1:
                try:
                    return [Decimal(sec_nums[0])], EntryMode.SINGLE, None, False
                except InvalidOperation:
                    pass

        # 5. Single entry
        m_single = re.search(
            r"(?:Entrys|Entry\s*Targets?|ENTRY\s*PRICE|ENTERY\s*PRICE|Entry\s*Price|ENTERY|Entry\s*Zone|Entry|Take Entries|BUY)\s*[:\=\-\>\u279c\u2794\s]*\n?\s*(?:\d+[\)\.]\s*|\-\s*)?(?:[^\d\$\.]*)\s*\$?([\d\.]+)",
            text,
            re.IGNORECASE
        )
        if m_single:
            try:
                return [Decimal(m_single.group(1))], EntryMode.SINGLE, None, False
            except InvalidOperation:
                pass

        return [], EntryMode.SINGLE, "Khong tim thay muc entry hop le", False

    def parse_stop_loss(self, text: str):
        # 1. Bullet on newline like '1) 0.018100' or '1) ⛔️ 0.3920' or '1. 0.018100'
        m_bullet = re.search(
            r"\b(?:Stop-Loss|STOP LOSS|STOPLOSS|STOPP LOSS|Stop Loss|Stop Target|Stoploss|Stop|SL)\b[^\n]*\n+\s*(?:\d+[\)\:]|\d+\.(?!\d))\s*[^\d\$\n]*\$?([0-9\.]+)",
            text,
            re.IGNORECASE,
        )
        if m_bullet:
            v_str = m_bullet.group(1).strip()
            v_str = re.split(r"[\s\-]", v_str)[0]
            try:
                return Decimal(v_str), None, False
            except InvalidOperation:
                pass

        # 2. Standard inline SL
        m = re.search(
            r"\b(?:Stop-Loss|STOP LOSS|STOPLOSS|STOPP LOSS|Stop Loss|Stop Target|Stoploss|Stop|SL)\b[^\d\$\n]*\$?([0-9\.]+[kK]?)",
            text,
            re.IGNORECASE,
        )
        if not m:
            return None, "Khong tim thay Stop Loss", False

        val_str = m.group(1).strip()
        val_str = re.split(r"[\s\-]", val_str)[0]
        if val_str.startswith("0") and "." not in val_str and len(val_str) > 2:
            return None, f"Stop Loss '{val_str}' la so mo ho", True

        try:
            if val_str.lower().endswith("k"):
                val = Decimal(val_str[:-1]) * Decimal("1000")
            else:
                val = Decimal(val_str)
            return val, None, False
        except InvalidOperation:
            return None, f"Stop Loss '{val_str}' khong hop le", False

    def parse_take_profits(self, text: str):
        tps = []
        # Slash separated: Targets: $0.144/$0.156/$0.174
        m_slash = re.search(r"(?:Targets?|Take[\s\-]*Profits?|Profit\s*Targets?)\s*[:\-\>\s]*((?:\$?[\d\.]+\s*\/\s*)+\$?[\d\.]+)", text, re.IGNORECASE)
        if m_slash:
            parts = re.split(r"\s*\/\s*", m_slash.group(1).strip())
            for p in parts:
                clean_p = p.replace("$", "").strip()
                try: tps.append(Decimal(clean_p))
                except InvalidOperation: pass
            if tps: return tps, None

        # Bracket separated: Take profit = [ 0.1313, 0.1296, 0.1280 ]
        m_bracket = re.search(r"(?:Take[\s\-]*Profits?|Profit\s*Targets?|Targets?)\s*[:\=\-\>\s]*\[\s*([\d\.,\s]+)\s*\]", text, re.IGNORECASE)
        if m_bracket:
            for p in re.split(r"[, \t]+", m_bracket.group(1).strip()):
                try:
                    cp = p.replace("$", "").strip()
                    if cp: tps.append(Decimal(cp))
                except InvalidOperation: pass
            if tps: return tps, None

        # Direct target bullets anywhere: "1.🎯 0.08250" or "• Target 1: 0.02375"
        direct_bullets = re.findall(r"(?:^\s*\d+[\.\)]\s*[🎯]\s*|•\s*Target\s*\d+\s*:\s*)\$?([\d\.]+)", text, re.MULTILINE | re.IGNORECASE)
        if len(direct_bullets) >= 2:
            for p in direct_bullets:
                try:
                    v = Decimal(p.strip())
                    if v not in tps: tps.append(v)
                except InvalidOperation: pass
            if tps: return tps, None

        # Arrow / comma separated single line
        m_arrow = re.search(r"(?:Targets?|Take[\s\-]*Profits?|Profit\s*Targets?)\s*[:\-\>\s]*((?:\$?[\d\.]+\s*(?:→|->|,)\s*)+\$?[\d\.]+)", text, re.IGNORECASE)
        if m_arrow:
            for p in re.split(r"\s*(?:→|->|,)\s*", m_arrow.group(1).strip()):
                clean_p = p.replace("$", "").strip()
                try: tps.append(Decimal(clean_p))
                except InvalidOperation: pass
            if tps: return tps, None

        # Hyphen separated
        m_hyphen = re.search(r"(?:TAKE-?\s*PROFITS?|Profit\s*Targets?|Targets?)\s*[:\-\>\s]*\n*\s*([\d\.]+(?:\s*-\s*[\d\.]+)+)", text, re.IGNORECASE)
        if m_hyphen:
            for p in re.split(r"\s*-\s*", m_hyphen.group(1).strip()):
                try: tps.append(Decimal(p.strip()))
                except InvalidOperation: pass
            if tps: return tps, None

        # Comma / space separated
        m_comma = re.search(r"(?:Targets|TAKE PROFIT LEVELS|Take Profit Targets|Take-Profit Targets|TAKE PROFITS|Targets?)\s*:\s*[🎯\s]*((?:[\d\.]+\s*[, \t]+)+[\d\.]+)", text, re.IGNORECASE)
        if m_comma:
            for p in re.split(r"[, \t]+", m_comma.group(1).strip()):
                try: tps.append(Decimal(p.strip()))
                except InvalidOperation: pass
            if tps: return tps, None

        # Line by line
        lines = text.split("\n")
        in_target_section = False
        for line in lines:
            line_str = line.strip()
            if not line_str: continue

            if re.search(r"(?:TAKE-?\s*PROFITS?|PROFIT\s*TARGETS?|\bTARGETS?\b|\bTP\b)", line_str, re.IGNORECASE) and not re.search(r"(?:Entr|Buy|Sell|Achieved)", line_str, re.IGNORECASE):
                in_target_section = True
                m_inline = re.search(r"(?:TP\d*|Target\s*\d*)\s*[:\-\>\s]*\$?([\d\.]+)", line_str, re.IGNORECASE)
                if m_inline:
                    try:
                        v = Decimal(m_inline.group(1))
                        if v not in tps: tps.append(v)
                    except InvalidOperation: pass
                continue

            if re.search(r"(?:Stop|Stoploss|Stopp|SL|Leverage|LEV|Entry|Entries|ENTERY|BUY|SELL|Account|Published|Trailing|RISK|Admin|Contact)", line_str, re.IGNORECASE):
                in_target_section = False
                continue

            m_explicit = re.search(r"(?:TP\d*|Target\s*\d*)\s*[\.\:\-\>\u279c\u2794\s]*\$?([\d\.]+)", line_str, re.IGNORECASE)
            if m_explicit:
                try:
                    v = Decimal(m_explicit.group(1))
                    if v not in tps: tps.append(v)
                    continue
                except InvalidOperation: pass

            if in_target_section:
                if re.search(r"^[\d\.]+(?:\s*-\s*[\d\.]+)+$", line_str):
                    for p in re.split(r"\s*-\s*", line_str):
                        try:
                            v = Decimal(p.strip())
                            if v not in tps: tps.append(v)
                        except InvalidOperation: pass
                    continue

                m_bullet = re.search(
                    r"(?:(?:\b\d+[\)\:\.](?!\d)|[0-9]+(?:[\uFE0F]?\u20E3)|[①-⑩]|[➊-➓]|[🥇🥈🥉]|[\-\•\➤\➔\➜\🎯\🧿])\s*)?\$?\s*(\d+(?:\.\d+)?k?)\s*$",
                    line_str,
                    re.IGNORECASE,
                )
                if m_bullet:
                    v_str = m_bullet.group(1).lower().strip()
                    try:
                        val = Decimal(v_str[:-1]) * Decimal("1000") if v_str.endswith("k") else Decimal(v_str)
                        if val not in tps: tps.append(val)
                    except InvalidOperation: pass

        if not tps: return [], "Khong tim thay Take Profit hop le"
        return tps, None

    def parse(self, raw_text: str):
        normalized = self.normalize(raw_text)
        sym_raw, sym, sym_warn = self.parse_symbol(normalized)
        side, side_warn = self.parse_side(normalized)
        entries, entry_mode, entry_warn, _ = self.parse_entries(normalized)
        sl, sl_warn, is_sl_ambiguous = self.parse_stop_loss(normalized)
        tps, tp_warn = self.parse_take_profits(normalized)

        # Check anti-vip bait
        is_vip_bait = bool(re.search(r"\b(?:dm\s*for\s*(?:entry|targets?|sl|signal|access)|sl\s*in\s*vip|tp\s*in\s*vip|only\s*in\s*vip|100%\s*guaranteed|insider\s*pump|pay\s*for\s*signal|inbox\s*for\s*calls)\b", normalized, re.IGNORECASE))
        is_target_achieved = bool(re.search(r"\b(?:Target Achieved|targets achieved|all targets achieved|all entries achieved)\b", normalized, re.IGNORECASE))

        if is_vip_bait or is_target_achieved:
            status = "REJECTED_BAIT"
            reason = "Bait / Result Announcement"
        elif not sym:
            status = "REJECTED"
            reason = "No Symbol"
        elif not side:
            status = "REJECTED"
            reason = "No Side"
        elif not entries:
            status = "REJECTED"
            reason = "No Entry"
        elif not sl:
            status = "REJECTED"
            reason = "No SL"
        elif not tps:
            status = "REJECTED"
            reason = "No TP"
        else:
            status = "SUCCESS"
            reason = None

        return {
            "status": status,
            "reason": reason,
            "symbol": sym,
            "side": side,
            "entries": entries,
            "sl": sl,
            "tps": tps
        }

enhanced_parser = EnhancedSignalParser()

# Test across all candidate messages
stats = defaultdict(lambda: {"candidates": 0, "success": 0, "rejected": 0, "bait": 0, "reasons": defaultdict(int)})

rows = conn.execute(f"""
    SELECT chat_id, message_id, raw_text
    FROM messages
    WHERE chat_id IN ({','.join('?' for _ in allowed_chats)})
    ORDER BY telegram_timestamp DESC
""", allowed_chats).fetchall()

for r in rows:
    cid = r["chat_id"]
    text = r["raw_text"] or ""
    has_dir = bool(re.search(r"\b(LONG|SHORT|BUY|SELL)\b", text, re.IGNORECASE))
    has_usdt = bool(re.search(r"(?:[A-Za-z0-9]{2,10}\/USDT|[A-Za-z0-9]{2,10}USDT)", text, re.IGNORECASE))
    if not (has_dir and has_usdt):
        continue

    st = stats[cid]
    st["candidates"] += 1
    res = enhanced_parser.parse(text)
    if res["status"] == "SUCCESS":
        st["success"] += 1
    elif res["status"] == "REJECTED_BAIT":
        st["bait"] += 1
    else:
        st["rejected"] += 1
        st["reasons"][res["reason"]] += 1

print("\n================ ENHANCED PARSER BENCHMARK ================")
total_candidates = sum(s["candidates"] for s in stats.values())
total_success = sum(s["success"] for s in stats.values())
total_bait = sum(s["bait"] for s in stats.values())
total_pure_signals = total_candidates - total_bait
print(f"Total Trade Signal Candidates: {total_candidates}")
print(f"Filtered Bait / Result Announcements: {total_bait}")
print(f"Actionable Trade Signals: {total_pure_signals}")
print(f"Successfully Parsed: {total_success} ({(total_success/total_pure_signals*100) if total_pure_signals else 0:.1f}% of actionable signals)")

for cid in allowed_chats:
    name = channel_names.get(cid, str(cid))
    s = stats[cid]
    print(f"\n[{name}] (ID: {cid})")
    print(f"   Candidates: {s['candidates']} | Success: {s['success']} | Bait/Results: {s['bait']} | Other Rej: {s['rejected']}")
    if s["reasons"]:
        for r_name, cnt in sorted(s["reasons"].items(), key=lambda x: x[1], reverse=True):
            print(f"      - {r_name}: {cnt}")

conn.close()
