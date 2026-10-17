import re

pattern = r"(?:^|[\s\$#])([A-Za-z0-9]{1,12})USDT\b"
for s in ["$FETUSDT", "#RSRUSDT", "BTRUSDT", "QUSDT", "Coin: WIF"]:
    m = re.search(pattern, s, re.IGNORECASE)
    res = m.group(1).upper() + "USDT" if m else None
    if not res:
        m2 = re.search(r"(?:COIN|Coin|PAIR|Pair)\s*[:#-]?\s*[$#]?([A-Za-z0-9]{2,10})\b", s)
        if m2 and m2.group(1).upper() not in ["FREE", "VIP", "LONG", "SHORT"]:
            res = m2.group(1).upper() + "USDT"
    print(f"{s} -> {res}")
