import re
from decimal import Decimal, InvalidOperation

def parse_tps(text):
    tps = []
    lines = text.split("\n")
    in_target_section = False

    # Check comma / arrow / space separated single line e.g. "Targets: $0.0985 → $0.0950 → $0.0910"
    m_arrow = re.search(r"(?:Targets?|Take[\s\-]*Profits?)\s*[:\-\>\s]*((?:\$?[\d\.]+\s*(?:→|->|,)\s*)+\$?[\d\.]+)", text, re.IGNORECASE)
    if m_arrow:
        parts = re.split(r"\s*(?:→|->|,)\s*", m_arrow.group(1).strip())
        for p in parts:
            clean_p = p.replace("$", "").strip()
            try:
                tps.append(Decimal(clean_p))
            except InvalidOperation:
                pass
        if tps:
            return tps

    # Hyphen-separated targets e.g. "0.04160-0.04000-0.03650"
    m_hyphen = re.search(
        r"(?:TAKE-?\s*PROFITS?|Targets?)\s*[:\-\>\s]*\n*\s*([\d\.]+(?:\s*-\s*[\d\.]+)+)",
        text,
        re.IGNORECASE,
    )
    if m_hyphen:
        parts = re.split(r"\s*-\s*", m_hyphen.group(1).strip())
        for p in parts:
            try:
                tps.append(Decimal(p.strip()))
            except InvalidOperation:
                pass
        if tps:
            return tps

    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue

        # Check if line marks start of target section
        if re.search(r"(?:TAKE-?\s*PROFITS?|PROFIT\s*TARGETS?|TARGETS?|\bTP\b)", line_str, re.IGNORECASE) and not re.search(r"(?:Entr|Buy|Sell)", line_str, re.IGNORECASE):
            in_target_section = True
            # Inline explicit TP e.g. "Target: $830", "TP1: 0.5230"
            m_inline = re.search(r"(?:TP\d*|Target\s*\d*)\s*[:\-\>\s]*\$?([\d\.]+)", line_str, re.IGNORECASE)
            if m_inline:
                try:
                    val = Decimal(m_inline.group(1))
                    if val not in tps:
                        tps.append(val)
                except InvalidOperation:
                    pass
            continue

        # Section exit
        if re.search(r"(?:Stop|Stoploss|Stopp|SL|Leverage|LEV|Entry|Entries|ENTERY|BUY|SELL|Account|Published|Trailing|RISK|Admin|Contact)", line_str, re.IGNORECASE):
            in_target_section = False
            continue

        # Explicit TP line anywhere
        m_explicit = re.search(
            r"(?:TP\d*|Target\s*\d*)\s*[\.\:\-\>\u279c\u2794\s]*\$?([\d\.]+)",
            line_str,
            re.IGNORECASE,
        )
        if m_explicit:
            try:
                val = Decimal(m_explicit.group(1))
                if val not in tps:
                    tps.append(val)
                continue
            except InvalidOperation:
                pass

        if in_target_section:
            # Check hyphen-separated line inside section: "0.04160-0.04000-0.03650"
            if re.search(r"^[\d\.]+(?:\s*-\s*[\d\.]+)+$", line_str):
                for p in re.split(r"\s*-\s*", line_str):
                    try:
                        v = Decimal(p.strip())
                        if v not in tps:
                            tps.append(v)
                    except InvalidOperation:
                        pass
                continue

            # Check numbered or bulleted line: 1) 0.0457, 1: 2410, ➊ 0.08300, 1. 0.0457
            m_bullet = re.search(
                r"(?:(?:\b\d+[\)\:\.](?!\d)|[0-9]+(?:[\uFE0F]?\u20E3)|[①-⑩]|[➊-➓]|[🥇🥈🥉]|[\-\•\➤\➔\➜\🎯\🧿])\s*)?\$?\s*(\d+(?:\.\d+)?k?)\s*$",
                line_str,
                re.IGNORECASE,
            )
            if m_bullet:
                v_str = m_bullet.group(1).lower().strip()
                try:
                    if v_str.endswith("k"):
                        val = Decimal(v_str[:-1]) * Decimal("1000")
                    else:
                        val = Decimal(v_str)
                    if val not in tps:
                        tps.append(val)
                    continue
                except InvalidOperation:
                    pass

    return tps

# Test all 5 problematic samples
sample1 = """🔥 RFD Indicator 🔥

 15 Minutes Timeframe

✅ LONG

#CTR/USDT

Entry zone : 0.0147711 - 0.0152280

Take Profits : 

0.0153033
0.0157579
0.0162124
0.0166670
0.0171216

Stop loss :0.01416204

Leverage: 10x"""

sample2 = """👍THE WOLF SCALPER👍

🚀 SHORT: $ZEREBRO/USDT
LEVERAGE: 50x

✔️ENTRY PRICE: 0.04250
✔️ 2nd ENTRY: 0.04340
——————
☄️TAKE- PROFIT

0.04160-0.04000-0.03650

STOP LOSS:  0.04500"""

sample3 = """💎🔥PAIR: COLLECT/USDT
📈🚀TRADE TYPE: LONG 

🎯🏹ENTRY:
➤0.07830

💰🎯TAKE PROFIT:
➊ 0.08300

❌❌STOP LOSS:
➤ 0.07570"""

sample4 = """🔱 Trade: #ETH/USDT 🔱

🟢 LONG ENTRY: 2390 : 2365

🀄️ LEVERAGE: 25x

🎯 Targets

1: 2410
2: 2430
3: 2450
4: 2475

🔴 STOP LOSS: 2335"""

sample5 = """📊 Let’s SHORT #ARIA/USDT

💥 Leverage:  Cross 20×  

✔️ Take Entries:  0.04685 - 0.0484

📈 Profit TARGET: 

1) 0.0457
2) 0.0433
3) 0.0402

🔖 Stop Loss: 0.049"""

sample6 = """💹#MELANIA/USDT - SHORT SETUP

Entry: $0.1048 - $0.1060
Targets: $0.0985 → $0.0950 → $0.0910
Stop Loss: $0.1115 (30m close)"""

sample7 = """⚡️ #4/usdt
🔵#long  [future]

💠 levarage  :  10x-20x
💰[margin 1%]

🔅 entry : -0.02087

🧿 target-0.022
🧿 target-0.023
🧿 target-0.025

⭕️ STOP :0.019"""

samples = [sample1, sample2, sample3, sample4, sample5, sample6, sample7]
for i, s in enumerate(samples, 1):
    res = parse_tps(s)
    print(f"Sample {i}: Extracted {len(res)} TPs -> {res}")
    assert len(res) > 0, f"Sample {i} failed!"
print("\nALL SAMPLES PASSED 100%!")

