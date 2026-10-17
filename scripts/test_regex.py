import re

text = """Stop-Loss (SL):
1) 0.018100"""

pattern = r"\b(?:Stop-Loss|STOP LOSS|STOPLOSS|STOPP LOSS|Stop Loss|Stop Target|Stoploss|Stop|SL)\b(?:\s*\([A-Za-z]+\))?[_\*]*\s*[:\-\>\s]*\n*\s*(?:\d+[\)\.]\s+)?(?:[^\w\s\$\.]*)\s*\$?([0-9\.]+)"
m = re.search(pattern, text, re.IGNORECASE)
print('Matched SL:', m.group(1) if m else None)

