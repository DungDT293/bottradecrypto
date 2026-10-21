import re
from decimal import Decimal, InvalidOperation

def test_sl_regex(text):
    # 1. Check if line has a bullet number like '1) 0.018100' or '1) ⛔️ 0.3920' or '1. 0.018100'
    m_bullet = re.search(
        r"\b(?:Stop-Loss|STOP LOSS|STOPLOSS|STOPP LOSS|Stop Loss|Stop Target|Stoploss|Stop|SL)\b[^\n]*\n+\s*(?:\d+[\)\:]|\d+\.(?!\d))\s*[^\d\$\n]*\$?([0-9\.]+)",
        text,
        re.IGNORECASE,
    )
    if m_bullet:
        val_str = m_bullet.group(1).strip()
        val_str = re.split(r"[\s\-]", val_str)[0]
        try:
            return Decimal(val_str)
        except InvalidOperation:
            pass

    # 2. Standard inline SL e.g. 'Stoploss 🔴Loss :- 0.1384', 'Stop loss :0.01814613', 'SL under 62k'
    m = re.search(
        r"\b(?:Stop-Loss|STOP LOSS|STOPLOSS|STOPP LOSS|Stop Loss|Stop Target|Stoploss|Stop|SL)\b[^\d\$\n]*\$?([0-9\.]+[kK]?)",
        text,
        re.IGNORECASE,
    )
    if m:
        val_str = m.group(1).lower().strip()
        val_str = re.split(r"[\s\-]", val_str)[0]
        if val_str.endswith("k"):
            return Decimal(val_str[:-1]) * Decimal("1000")
        try:
            return Decimal(val_str)
        except InvalidOperation:
            pass
    return None

def test_entry_regex(text):
    # Clean leading dash/bracket after Entry:
    # e.g. "Entries:  - 0.118 - 0.114" or "Entry = [ 0.1336 TO 0.1333 ]" or "LONG ENTRY: 2440 : 2422"
    m_range = re.search(
        r"(?:Entries|Entry|ENTERY|Take Entries)[\s\w]*[:\=]\s*\[?\s*-?\s*\$?([\d\.]+)\s*(?:-|–|TO|to|:)\s*\$?([\d\.]+)\s*\]?",
        text,
        re.IGNORECASE
    )
    if m_range:
        return [Decimal(m_range.group(1)), Decimal(m_range.group(2))]
    return None

def test_tp_regex(text):
    tps = []
    # Slash separated: Targets: $0.144/$0.156/$0.174
    m_slash = re.search(r"(?:Targets?|Take[\s\-]*Profits?|Profit\s*Targets?)\s*[:\-\>\s]*((?:\$?[\d\.]+\s*\/\s*)+\$?[\d\.]+)", text, re.IGNORECASE)
    if m_slash:
        for p in m_slash.group(1).split("/"):
            clean_p = p.replace("$", "").strip()
            try:
                tps.append(Decimal(clean_p))
            except InvalidOperation:
                pass
        if tps:
            return tps

    # Bracket separated: Take profit = [ 0.1313, 0.1296, 0.1280 ]
    m_bracket = re.search(r"(?:Take\s*Profit|Targets?)\s*[:\=]\s*\[\s*([\d\.,\s]+)\s*\]", text, re.IGNORECASE)
    if m_bracket:
        for p in m_bracket.group(1).split(","):
            try:
                tps.append(Decimal(p.strip()))
            except InvalidOperation:
                pass
        if tps:
            return tps

    # Direct target bullet lines like "1.🎯 0.08250" or "1. 🎯 6907.18" anywhere in message
    direct_bullets = re.findall(r"^\s*\d+[\.\)]\s*[🎯]\s*\$?([\d\.]+)", text, re.MULTILINE)
    if direct_bullets:
        for p in direct_bullets:
            try:
                val = Decimal(p.strip())
                if val not in tps:
                    tps.append(val)
            except InvalidOperation:
                pass
        if tps:
            return tps
            
    return None

# Test samples
sample_estr = """
PAIR: HEMI/USDT
DIRECTION: LONG

Entry Price
1) 0.018700

Take Profit (TP):
1) 0.019500

Stop-Loss (SL):
1) 0.018100
"""
print("ESTR SL test:", test_sl_regex(sample_estr))

sample_jhonny = """
🟢 LONG ENTRY: 2440 : 2422

1.🎯 0.08250
2.🎯 0.08360
3.🎯 0.08480

⛔️ STOP LOSS: 0.07878
"""
print("Jhonny Entry:", test_entry_regex(sample_jhonny))
print("Jhonny TP:", test_tp_regex(sample_jhonny))
print("Jhonny SL:", test_sl_regex(sample_jhonny))

sample_green = """
⚡ Entry = [ 0.1336 TO 0.1333 ]
❌ Stoploss 🔴Loss :- 0.1384
✅ Take profit = [ 0.1313, 0.1296, 0.1280, 0.1261, 0.1244, 0.1220 ]
"""
print("Green Entry:", test_entry_regex(sample_green))
print("Green TP:", test_tp_regex(sample_green))
print("Green SL:", test_sl_regex(sample_green))

sample_global = "Entries:  - 0.118 - 0.114"
print("Global Entry:", test_entry_regex(sample_global))

sample_slash = "Targets: $0.144/$0.156/$0.174"
print("Slash TP:", test_tp_regex(sample_slash))

sample_ctrusdt = """🔥 MTC Indicator 🔥

 15 Minutes Timeframe

🔴 SHORT

#CTR/USDT

Entry zone : 0.0174677 - 0.0169590

Take Profits : 

0.0168733
0.0163620
0.0158507
0.0153394
0.0148281

Stop loss :0.01814613

Leverage: 10x"""

print("CTRUSDT Entry:", test_entry_regex(sample_ctrusdt))
print("CTRUSDT SL:", test_sl_regex(sample_ctrusdt))

sample_cwu = """
⚡️⚡️ #CT/USDT ️️️️⚡️️⚡️
SIGNAL Type: Regular (SHORT) 🔽
Leverage: Cross (25X) 
Amount: 2% ⚠️

Entry Targets:

1) ➡️ 0.3650

2) ➡️ 0.3775

Take-Profit Targets:

1) 🔽 0.3500

2) ⬇️ 0.3300

3) 📉 0.3000

Stop Target:

1) ⛔️ 0.3920

Trailing Configuration:
Stop: Breakeven -
  Trigger: Target (1)
"""
print("CWU SL test:", test_sl_regex(sample_cwu))
