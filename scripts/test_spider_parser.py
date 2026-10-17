import re
import sys
from decimal import Decimal

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

text = """#INJUSDT LONG SIGNAL

⚡ LEVERAGE 50X-75X
📌 ENTRY ➔ 8.660
🎯 TAKE PROFIT LEVELS

① 🟢 TP1 ➔ 8.860
② 🟢 TP2 ➔ 9.130
③ 🟢 TP3 ➔ 9.600
④ 🟢 TP4 ➔ 10.250

🛑 STOP LOSS 8.070"""

# 1. Normalize arrows in normalizer
norm = re.sub(r"[\u2190-\u21ff\u2790-\u27bf\u25b6\u25b7]", "->", text)
print("Normalized text:\n", norm)

# 2. Test entry regex
m_single = re.search(r"(?:Entrys|ENTRY|ENTERY PRICE|ENTERY|Entry|BUY)\s*[:\-\>\s]*\n?\s*(?:\d+\)\s*)?\$?([\d\.]+)", norm, re.IGNORECASE)
print("\nEntry matched:", m_single.group(1) if m_single else None)

# 3. Test TP regex
tps = []
for line in norm.split("\n"):
    m_exp = re.search(r"(?:TP\d*|Target\s*\d+)\s*[\.\:\-\>\s]*\$?([\d\.]+)", line, re.IGNORECASE)
    if m_exp:
        tps.append(Decimal(m_exp.group(1)))
print("TPs matched:", tps)

# 4. Test SL regex
m_sl = re.search(r"\b(?:Stop-Loss|STOP LOSS|STOPLOSS|STOPP LOSS|Stop Loss|Stop Target|Stoploss|Stop|SL)\b\s*[:\-\>\s]*\n*\s*(?:\b\d+[\)\.]\s+)?(?:[^\w\s\$\.]*)\s*\$?([0-9\.]+)", norm, re.IGNORECASE)
print("SL matched:", m_sl.group(1) if m_sl else None)

