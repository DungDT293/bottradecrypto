import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from core.enums import EntryMode, FieldSource, MarginMode, PositionSide, SignalState
from core.models import ParsedSignal, SourceMetadata
from parser.normalizer import normalize_text


class SignalParser:
    """
    Deterministic, rule-based signal parser.
    Strictly follows source tracing (EXPLICIT_SIGNAL, SOURCE_POLICY, GLOBAL_POLICY, UNRESOLVED)
    and does not guess or auto-fix ambiguous data.
    """

    def parse(self, raw_text: str, metadata: SourceMetadata) -> ParsedSignal:
        normalized = normalize_text(raw_text)
        warnings: List[str] = []
        field_sources: Dict[str, FieldSource] = {}

        # 1. Parse Symbol
        symbol_raw, symbol_candidate, sym_warning = self._parse_symbol(normalized)
        if sym_warning:
            warnings.append(sym_warning)
        field_sources["symbol"] = FieldSource.EXPLICIT_SIGNAL if symbol_candidate else FieldSource.UNRESOLVED

        # 2. Parse Direction / Side & Check Conflict
        side, dir_conflict_warning = self._parse_side_with_conflict_check(normalized)
        if dir_conflict_warning:
            warnings.append(dir_conflict_warning)
        field_sources["side"] = FieldSource.EXPLICIT_SIGNAL if side else FieldSource.UNRESOLVED

        # 3. Parse Leverage
        leverage_requested, leverage_range = self._parse_leverage(normalized)
        if leverage_requested is not None or leverage_range is not None:
            field_sources["leverage"] = FieldSource.EXPLICIT_SIGNAL
        else:
            field_sources["leverage"] = FieldSource.UNRESOLVED

        # 4. Parse Margin Mode
        margin_mode = self._parse_margin_mode(normalized)
        if margin_mode:
            field_sources["margin_mode"] = FieldSource.EXPLICIT_SIGNAL
        else:
            field_sources["margin_mode"] = FieldSource.UNRESOLVED

        # 5. Parse Entries
        entries, entry_mode, entry_warning, has_ambiguous_entry_semantics = self._parse_entries(normalized)
        if entry_warning:
            warnings.append(entry_warning)
        field_sources["entries"] = FieldSource.EXPLICIT_SIGNAL if entries else FieldSource.UNRESOLVED

        # 6. Parse Stop Loss
        stop_loss, sl_warning, is_sl_ambiguous = self._parse_stop_loss(normalized)
        if sl_warning:
            warnings.append(sl_warning)
        field_sources["stop_loss"] = FieldSource.EXPLICIT_SIGNAL if (stop_loss and not is_sl_ambiguous) else FieldSource.UNRESOLVED

        # 7. Parse Take Profits
        take_profits, tp_warning = self._parse_take_profits(normalized)
        if tp_warning:
            warnings.append(tp_warning)
        field_sources["take_profits"] = FieldSource.EXPLICIT_SIGNAL if take_profits else FieldSource.UNRESOLVED

        # 8. Parse TP Weights & Entry Rules
        tp_weights = self._parse_tp_weights(normalized, len(take_profits))
        if tp_weights:
            field_sources["tp_weights"] = FieldSource.EXPLICIT_SIGNAL
        else:
            field_sources["tp_weights"] = FieldSource.UNRESOLVED

        # Entry chase check (e.g. "don’t chase above ." missing price)
        if re.search(r"don['’]t\s+chase\s+above\s*\.", normalized, re.IGNORECASE):
            warnings.append("CANH BAO: Mau co chu 'don’t chase above .' bi thieu muc gia chan")

        # 9. Parse Breakeven Instruction & Mandatoriness
        breakeven_instruction, is_be_mandatory = self._parse_breakeven(normalized)
        if breakeven_instruction:
            field_sources["breakeven"] = FieldSource.EXPLICIT_SIGNAL

        # 10. Capital Usage / Risk Text
        capital_usage_text = self._parse_capital_usage(normalized)

        # 11. Determine initial validation status
        validation_status = SignalState.PARSED
        blocking_reason = None

        # Anti-VIP bait / scam detector
        is_vip_bait = bool(
            re.search(
                r"\b(?:dm\s*for\s*(?:entry|targets?|sl|signal|access)|sl\s*in\s*vip|tp\s*in\s*vip|only\s*in\s*vip|100%\s*guaranteed|insider\s*pump|pay\s*for\s*signal|inbox\s*for\s*calls)\b",
                normalized,
                re.IGNORECASE,
            )
        )

        if is_vip_bait:
            validation_status = SignalState.REJECTED
            blocking_reason = "Tin nhan cau keo VIP / quang cao lua dao (Tu choi vao lenh)"
        elif dir_conflict_warning:
            validation_status = SignalState.NEEDS_REVIEW
            blocking_reason = "Mau thuan huong lenh giua tieu de va muc entry (vd: SHORT nhung BUY)"
        elif has_ambiguous_entry_semantics:
            validation_status = SignalState.NEEDS_REVIEW
            blocking_reason = "Ngu nghia muc entry khong ro rang (vd: Short BELOW nhieu gia)"
        elif is_sl_ambiguous:
            validation_status = SignalState.REJECTED
            blocking_reason = "Stop Loss mo ho, khong co dau thap phan hop le"
        elif not symbol_candidate:
            validation_status = SignalState.REJECTED
            blocking_reason = f"Symbol khong xac dinh hoac khong ho tro USDT: {symbol_raw}"
        elif not side:
            validation_status = SignalState.REJECTED
            blocking_reason = "Khong xac dinh duoc huong lenh (LONG/SHORT)"
        elif not entries:
            validation_status = SignalState.REJECTED
            blocking_reason = "Khong co muc gia entry"
        elif not stop_loss:
            validation_status = SignalState.REJECTED
            blocking_reason = "Thieu Stop Loss"
        elif not take_profits:
            validation_status = SignalState.REJECTED
            blocking_reason = "Thieu Take Profit"
        elif entry_mode == EntryMode.RANGE:
            validation_status = SignalState.NEEDS_POLICY
            blocking_reason = "Entry la mot vung gia (range), can policy de thuc thi"
        elif len(entries) > 1 and not field_sources.get("entry_weights"):
            validation_status = SignalState.NEEDS_POLICY
            blocking_reason = "Nhieu entry nhung thieu trong so phan bo von (entry weights)"
        elif len(take_profits) > 1 and not tp_weights:
            validation_status = SignalState.NEEDS_POLICY
            blocking_reason = "Nhieu TP nhung thieu ty le chot loi (TP weights)"
        elif not margin_mode:
            validation_status = SignalState.NEEDS_POLICY
            blocking_reason = "Thieu margin mode (can ap dung policy ISOLATED)"

        signal_id = f"sig_{metadata.chat_id}_{metadata.message_id}_{uuid.uuid4().hex[:6]}"

        return ParsedSignal(
            signal_id=signal_id,
            metadata=metadata,
            symbol_raw=symbol_raw,
            symbol_candidate=symbol_candidate,
            side=side,
            entries=entries,
            entry_mode=entry_mode,
            entry_weights=None,
            stop_loss=stop_loss,
            take_profits=take_profits,
            tp_weights=tp_weights,
            margin_mode_requested=margin_mode,
            leverage_requested=leverage_requested,
            leverage_range=leverage_range,
            capital_usage_text=capital_usage_text,
            breakeven_instruction=breakeven_instruction,
            is_breakeven_mandatory=is_be_mandatory,
            warnings=warnings,
            validation_status=validation_status,
            blocking_reason=blocking_reason,
            field_sources=field_sources,
        )

    def _parse_symbol(self, text: str) -> Tuple[str, Optional[str], Optional[str]]:
        """Extract symbol raw and candidate. Strictly checks for USDT perpetual pair."""
        # 1. Check for explicit Trade/Pair/Coin slash (e.g. Trade: #ASTER/USDT, BTC/USDT, $DEEP /USDT, Q/USD)
        m_trade = re.search(r"(?:Trade|PAIR|Coin)[\s\:\-]*#?([A-Za-z0-9]+)\s*\/\s*([A-Za-z0-9]+)", text, re.IGNORECASE)
        if m_trade:
            base = m_trade.group(1).upper()
            quote = m_trade.group(2).upper()
            raw = f"{base}/{quote}"
            if quote == "USDT":
                return raw, f"{base}USDT", None
            else:
                return raw, None, f"Quote asset '{quote}' khong phai USDT. Khong ho tro."

        m_slash = re.search(r"[$#]?([A-Za-z0-9]+)\s*\/\s*([A-Za-z0-9]+)", text)
        if m_slash:
            base = m_slash.group(1).upper()
            quote = m_slash.group(2).upper()
            raw = f"{base}/{quote}"
            if quote == "USDT":
                return raw, f"{base}USDT", None
            else:
                return raw, None, f"Quote asset '{quote}' khong phai USDT. Khong ho tro."

        # 2. Match #SYMBOLUSDT, $SYMBOLUSDT or bare SYMBOLUSDT (e.g. #RSRUSDT, $FETUSDT, BTRUSDT, QUSDT)
        m_usdt = re.search(r"(?:^|[\s\$#])([A-Za-z0-9]{1,12})USDT\b", text, re.IGNORECASE)
        if m_usdt:
            base = m_usdt.group(1).upper()
            return f"{base}USDT", f"{base}USDT", None

        # 3. Match Coin: SYMBOL or PAIR: SYMBOL (e.g. Coin: WIF)
        m_coin = re.search(r"(?:COIN|Coin|PAIR|Pair)\s*[:#-]?\s*[$#]?([A-Za-z0-9]{2,10})\b", text)
        if m_coin:
            base = m_coin.group(1).upper()
            if base not in ["FREE", "VIP", "LONG", "SHORT", "BUY", "SELL", "USDT"]:
                return f"{base}/USDT", f"{base}USDT", None

        # 4. Match #SYMBOL | or #SYMBOL with SETUP/DIRECTION (e.g. #BEL | SHORT SETUP, #CIEN | SHORT SETUP, #CFX | SHORT SETUP)
        m_hash = re.search(r"#([A-Za-z0-9]{2,12})\s*(?:\|\s*)?(?:SHORT|LONG|BUY|SELL|\bSETUP\b)", text, re.IGNORECASE)
        if m_hash:
            base = m_hash.group(1).upper()
            if base.endswith("STOCK") or base in ["CIEN", "NVDA", "TSLA", "AAPL", "MSTR", "CAT", "CVX", "SPY", "QQQ"]:
                return f"{base}", None, f"Ma co phieu My / Stock '{base}' khong ho tro tren Binance Futures"
            if base not in ["FREE", "VIP", "LONG", "SHORT", "BUY", "SELL", "USDT", "SETUP", "TARGET", "STOP"]:
                return f"{base}/USDT", f"{base}USDT", None

        return "UNKNOWN", None, "Khong tim thay symbol hop le"

    def _parse_side_with_conflict_check(self, text: str) -> Tuple[Optional[PositionSide], Optional[str]]:
        """
        Parses direction and checks for contradictions (e.g. #SHORT in header but BUY : in entries).
        """
        has_short_header = bool(re.search(r"(?:#SHORT|\bSHORT\b|Position:\s*SHORT|Direction\s*:\s*SHORT|\(SHORT\)|SHORT\s*ZONE|SHORT\s*ENTRY)", text, re.IGNORECASE))
        has_long_header = bool(re.search(r"(?:#LONG|\bLONG\b|Position:\s*LONG|Direction\s*:\s*LONG|\(LONG\)|LONG\s*ZONE|LONG\s*ENTRY)", text, re.IGNORECASE))

        # Check for explicit BUY/SELL in entry section
        has_buy_entry = bool(re.search(r"\bBUY\s*:\s*\n?\s*\d+\)", text, re.IGNORECASE))
        has_sell_entry = bool(re.search(r"\bSELL\s*:\s*\n?\s*\d+\)", text, re.IGNORECASE))

        # Detect conflict like ATOM sample: SHORT header but BUY entry
        if (has_short_header and has_buy_entry) or (has_long_header and has_sell_entry):
            return PositionSide.SHORT if has_short_header else PositionSide.LONG, "Mau thuan huong lenh giua tieu de va muc entry (vd: SHORT nhung BUY)"

        if has_short_header:
            return PositionSide.SHORT, None
        if has_long_header:
            return PositionSide.LONG, None

        if has_buy_entry:
            return PositionSide.LONG, None
        if has_sell_entry:
            return PositionSide.SHORT, None

        return None, None

    def _parse_leverage(self, text: str) -> Tuple[Optional[int], Optional[Tuple[int, int]]]:
        """Extract leverage single value or range (e.g., 20x to 50x, 50X-75X, 200X)."""
        # Range e.g. 20x to 50x, 25X TO 50X, 50X-75X, 5- 20X
        m_range = re.search(r"(?:LEVERAGE|LEV|Leverage)[^\d\n]*?(\d+)\s*(?:x|X)?\s*(?:to|-|–)\s*(\d+)\s*(?:x|X|×)?", text, re.IGNORECASE)
        if m_range:
            low = int(m_range.group(1))
            high = int(m_range.group(2))
            return low, (low, high)  # Conservative: return low or range

        # Inline range without keyword e.g. 5- 20X, 10-20x
        m_inline_range = re.search(r"\b(\d{1,3})\s*(?:x|X)?\s*(?:to|-|–)\s*(\d{1,3})\s*(?:x|X|×)\b", text)
        if m_inline_range:
            low = int(m_inline_range.group(1))
            high = int(m_inline_range.group(2))
            if 1 <= low <= 125 and 1 <= high <= 125 and low < high:
                return low, (low, high)

        # Single e.g. Leverage: 50X, LEV : 20X, Cross (200X), Cross 25×, Leverage: Cross • 50X
        m_single = re.search(r"(?:LEVERAGE|LEV|Leverage)[^\d\n]*?\(?(\d+)\s*(?:x|X|×)\)?", text, re.IGNORECASE)
        if m_single:
            val = int(m_single.group(1))
            return val, None

        return None, None

    def _parse_margin_mode(self, text: str) -> Optional[MarginMode]:
        """Extract requested margin mode: Cross vs Isolated."""
        if re.search(r"\bCross\b", text, re.IGNORECASE):
            return MarginMode.CROSSED
        if re.search(r"\bIsolated\b", text, re.IGNORECASE):
            return MarginMode.ISOLATED
        return None

    def _parse_entries(self, text: str) -> Tuple[List[Decimal], EntryMode, Optional[str], bool]:
        """
        Extract entry prices. Handles single, multiple, range, and ambiguous cases (TRUTH).
        """
        # Check TRUTH / LEOPARD pattern: "Short BELOW (0.02300)(0.02325)" or "LONG **BELOW (0.04650)(0.04600)"
        m_below = re.search(r"(?:Short|LONG|BUY|SELL)[\s\*]+BELOW\s*\(([\d\.]+k?)\)\s*\(([\d\.]+k?)\)", text, re.IGNORECASE)
        if m_below:
            try:
                def parse_k(v_str: str) -> Decimal:
                    v_str = v_str.lower().strip()
                    if v_str.endswith("k"):
                        return Decimal(v_str[:-1]) * Decimal("1000")
                    return Decimal(v_str)

                p1 = parse_k(m_below.group(1))
                p2 = parse_k(m_below.group(2))
                return [p1, p2], EntryMode.MULTIPLE, "BELOW co 2 muc gia, can policy cho phep", True
            except InvalidOperation:
                pass

        # Check Range pattern:
        # Handles:
        # - "Entries: 0.8960 - 0.9160", "Entry: $0.05030 -0.05134"
        # - "Entries:  - 0.118 - 0.114" (leading dash)
        # - "Entry = [ 0.1336 TO 0.1333 ]" (brackets and TO)
        # - "LONG ENTRY: 2440 : 2422" or "Entry: 63100 : 62700" (colon separator)
        # - "Take Entries: 0.04685 - 0.0484", "LONG ZONE: 0.69 - 0.67"
        m_range = re.search(
            r"(?:Entries|Entry|ENTERY|Take Entries|LONG\s*ZONE|SHORT\s*ZONE|BUY\s*ZONE|SELL\s*ZONE|ZONE|LONG\s*ENTRY|SHORT\s*ENTRY|BUY\s*ENTRY|SELL\s*ENTRY)[\s\w]*[:\=]\s*\[?\s*-?\s*\$?([\d\.]+)\s*(?:-|–|TO|to|:)\s*\$?([\d\.]+)\s*\]?",
            text,
            re.IGNORECASE,
        )
        if m_range:
            try:
                p1 = Decimal(m_range.group(1))
                p2 = Decimal(m_range.group(2))
                return [p1, p2], EntryMode.RANGE, None, False
            except InvalidOperation:
                pass

        # Check Entry Zone with diamond bullet or non-standard separator (Boom_Boom_Billionaires)
        m_zone = re.search(
            r"Entry\s*Zone\s*:[^\d\n]*?\$?([\d\.]+)[^\d\n]+?\$?([\d\.]+)",
            text,
            re.IGNORECASE,
        )
        if m_zone:
            try:
                p1 = Decimal(m_zone.group(1))
                p2 = Decimal(m_zone.group(2))
                return [p1, p2], EntryMode.RANGE, None, False
            except InvalidOperation:
                pass

        # Check Dual Entry with "ENTRY PRICE: ... 2nd ENTRY: ..."
        m_wolf_dual = re.search(
            r"ENTRY\s*(?:PRICE|TARGET)?\s*:\s*\$?([\d\.]+).*?(?:2nd|second)\s*ENTRY\s*:\s*\$?([\d\.]+)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if m_wolf_dual:
            try:
                p1 = Decimal(m_wolf_dual.group(1))
                p2 = Decimal(m_wolf_dual.group(2))
                return [p1, p2], EntryMode.MULTIPLE, None, False
            except InvalidOperation:
                pass

        # Check Multiple numbered entries:
        # Format 1: Explicit "Entry 1: ... \n Entry 2: ..." or "1st ENTRY: ... \n 2nd ENTRY: ..."
        m_explicit_numbered = re.findall(r"(?:Entry\s*\d+|\d+(?:st|nd|rd|th)\s*ENTRY)\s*[:\-\>\s\u27a1\ufe0f]*\$?([\d\.]+)", text, re.IGNORECASE)
        if len(m_explicit_numbered) >= 2:
            try:
                prices = [Decimal(p) for p in m_explicit_numbered]
                return prices, EntryMode.MULTIPLE, None, False
            except InvalidOperation:
                pass
        elif len(m_explicit_numbered) == 1:
            try:
                p = Decimal(m_explicit_numbered[0])
                return [p], EntryMode.SINGLE, None, False
            except InvalidOperation:
                pass

        # Format 2: "Entry Targets:" section with bulleted lines (1) ... 2) ...) before any Take-Profit/Stop
        m_sec = re.search(r"Entry\s*Targets?\s*:\s*\n*(.*?)(?=\n\s*(?:Take-Profit|Targets?|Stop)\b|\Z)", text, re.IGNORECASE | re.DOTALL)
        if m_sec:
            sec_text = m_sec.group(1)
            sec_nums = re.findall(r"^\s*\d+[\)\.]\s*(?:[^\d\$\.]*)\s*\$?([\d\.]+)", sec_text, re.MULTILINE)
            if len(sec_nums) >= 2:
                try:
                    prices = [Decimal(p) for p in sec_nums]
                    return prices, EntryMode.MULTIPLE, None, False
                except InvalidOperation:
                    pass
            elif len(sec_nums) == 1:
                try:
                    p = Decimal(sec_nums[0])
                    return [p], EntryMode.SINGLE, None, False
                except InvalidOperation:
                    pass

        # Check Single entry:
        # "Entry Targets: 0.048", "Entrys : 0.04800", "ENTRY ➜ 0.002075", "ENTERY PRICE: 0.02923", "Entry Price: 9.17", "Entry Zone: 0.1988", "BUY :\n 1) 1.674 - 100%", "Entry: - 0.3299"
        m_single = re.search(
            r"(?:Entrys|Entry\s*Targets?|ENTRY\s*PRICE|ENTERY\s*PRICE|Entry\s*Price|ENTERY|Entry\s*Zone|Entry|Take Entries|BUY)\s*[:\=\-\>\u279c\u2794\s]*\n?\s*(?:\d+[\)\:]\s*|\d+\.(?!\d)\s*|\-\s*)?(?:[^\d\$\.]*)\s*\$?([\d\.]+)",
            text,
            re.IGNORECASE,
        )
        if m_single:
            try:
                p = Decimal(m_single.group(1))
                return [p], EntryMode.SINGLE, None, False
            except InvalidOperation:
                pass

        return [], EntryMode.SINGLE, "Khong tim thay muc entry hop le", False

    def _parse_stop_loss(self, text: str) -> Tuple[Optional[Decimal], Optional[str], bool]:
        """
        Extract Stop Loss. Detects ambiguous representations such as '052506' (missing decimal point).
        """
        # 1. Check if line has a bullet number like '1) 0.018100' or '1) ⛔️ 0.3920' or '1. 0.018100'
        # Crucial: use (?!\d) on dot so decimal prices like 0.018100 are not mistaken for a bullet '0.'
        m_bullet = re.search(
            r"\b(?:Stop-Loss|STOP LOSS|STOPLOSS|STOPP LOSS|Stop Loss|Stop Target|Stoploss|Stop|SL)\b[^\n]*\n+\s*(?:\d+[\)\:]|\d+\.(?!\d))\s*[^\d\$\n]*\$?([0-9\.]+)",
            text,
            re.IGNORECASE,
        )
        if m_bullet:
            val_str = m_bullet.group(1).strip()
            val_str = re.split(r"[\s\-]", val_str)[0]
            try:
                val = Decimal(val_str)
                return val, None, False
            except InvalidOperation:
                return None, f"Stop Loss '{val_str}' khong hop le", False

        # 2. Standard inline SL e.g. 'Stoploss 🔴Loss :- 0.1384', 'Stop loss :0.01814613', 'SL under 62k'
        m = re.search(
            r"\b(?:Stop-Loss|STOP LOSS|STOPLOSS|STOPP LOSS|Stop Loss|Stop Target|Stoploss|Stop|SL)\b[^\d\$\n]*\$?([0-9\.]+[kK]?)",
            text,
            re.IGNORECASE,
        )
        if not m:
            return None, "Khong tim thay Stop Loss", False

        val_str = m.group(1).strip()
        val_str = re.split(r"[\s\-]", val_str)[0]

        # Check for ambiguous integer string without dot (e.g. Q/USD "052506")
        if val_str.startswith("0") and "." not in val_str and len(val_str) > 2:
            return None, f"Stop Loss '{val_str}' la so mo ho, thieu dau thap phan. Khong tu sua thanh 0.{val_str[1:]}", True

        try:
            if val_str.lower().endswith("k"):
                val = Decimal(val_str[:-1]) * Decimal("1000")
            else:
                val = Decimal(val_str)
            return val, None, False
        except InvalidOperation:
            return None, f"Stop Loss '{val_str}' khong hop le", False

    def _parse_take_profits(self, text: str) -> Tuple[List[Decimal], Optional[str]]:
        """
        Extract take profit targets from various formats:
        - Comma-separated or space-separated lists
        - Section-bounded target lines
        - Explicit TP / Target lines
        """
        tps: List[Decimal] = []

        # 1. Slash separated targets e.g. "Targets: $0.144/$0.156/$0.174"
        m_slash = re.search(
            r"(?:Targets?|Take[\s\-]*Profits?|Profit\s*Targets?)\s*[:\-\>\s]*((?:\$?[\d\.]+\s*\/\s*)+\$?[\d\.]+)",
            text,
            re.IGNORECASE,
        )
        if m_slash:
            parts = re.split(r"\s*\/\s*", m_slash.group(1).strip())
            for p in parts:
                clean_p = p.replace("$", "").strip()
                try:
                    tps.append(Decimal(clean_p))
                except InvalidOperation:
                    pass
            if tps:
                return tps, None

        # 2. Bracket separated targets e.g. "Take profit = [ 0.1313, 0.1296, 0.1280 ]"
        m_bracket = re.search(
            r"(?:Take[\s\-]*Profits?|Profit\s*Targets?|Targets?)\s*[:\=\-\>\s]*\[\s*([\d\.,\s]+)\s*\]",
            text,
            re.IGNORECASE,
        )
        if m_bracket:
            for p in re.split(r"[, \t]+", m_bracket.group(1).strip()):
                try:
                    clean_p = p.replace("$", "").strip()
                    if clean_p:
                        tps.append(Decimal(clean_p))
                except InvalidOperation:
                    pass
            if tps:
                return tps, None

        # 3. Comma / Arrow separated single line e.g. "Targets: $0.0985 → $0.0950 → $0.0910" or "Targets: 0.20780, 0.21390"
        m_arrow = re.search(
            r"(?:Targets?|Take[\s\-]*Profits?|Profit\s*Targets?)\s*[:\-\>\s]*((?:\$?[\d\.]+\s*(?:→|->|,)\s*)+\$?[\d\.]+)",
            text,
            re.IGNORECASE,
        )
        if m_arrow:
            parts = re.split(r"\s*(?:→|->|,)\s*", m_arrow.group(1).strip())
            for p in parts:
                clean_p = p.replace("$", "").strip()
                try:
                    tps.append(Decimal(clean_p))
                except InvalidOperation:
                    pass
            if tps:
                return tps, None

        # 4. Hyphen-separated targets e.g. "TAKE- PROFIT\n\n0.002350-0.002250-0.002050" or "0.04160-0.04000-0.03650"
        m_hyphen = re.search(
            r"(?:TAKE-?\s*PROFITS?|Profit\s*Targets?|Targets?)\s*[:\-\>\s]*\n*\s*([\d\.]+(?:\s*-\s*[\d\.]+)+)",
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
                return tps, None

        # 5. Comma or space separated targets e.g. "Targets: 🎯 0.8720, 0.8389, 0.7860" or "Targets: 0.20780 0.21390 0.22920"
        m_comma = re.search(
            r"(?:Targets|TAKE PROFIT LEVELS|Take Profit Targets|Take-Profit Targets|TAKE PROFITS|Targets?)\s*:\s*[🎯\s]*((?:[\d\.]+\s*[, \t]+)+[\d\.]+)",
            text,
            re.IGNORECASE,
        )
        if m_comma:
            parts = re.split(r"[, \t]+", m_comma.group(1).strip())
            for p in parts:
                try:
                    tps.append(Decimal(p.strip()))
                except InvalidOperation:
                    pass
            if tps:
                return tps, None

        # 6. Line by line parsing with target-section tracking
        lines = text.split("\n")
        in_target_section = False

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            # Check if this line marks the start of a target section
            if re.search(r"(?:TAKE-?\s*PROFITS?|PROFIT\s*TARGETS?|\bTARGETS?\b|\bTP\b)", line_str, re.IGNORECASE) and not re.search(r"(?:Stop|Entr|Buy|Sell|Trailing|Trigger|Management|Close)", line_str, re.IGNORECASE):
                in_target_section = True
                # Inline explicit TP e.g. "Target: $830", "TP1: 0.5230", "Target 2. $0.04920"
                m_inline = re.search(r"(?:TP\d*|Target\s*\d*)\s*[\.\:\-\>\s]*\$?([\d\.]+)", line_str, re.IGNORECASE)
                if m_inline:
                    try:
                        val = Decimal(m_inline.group(1))
                        if val not in tps:
                            tps.append(val)
                    except InvalidOperation:
                        pass
                continue

            # Check if line marks the end of a target section
            if re.search(r"(?:Stop|Stoploss|Stopp|SL|Leverage|LEV|Entry|Entries|ENTERY|BUY|SELL|Account|Published|Trailing|RISK|Admin|Contact|Management)", line_str, re.IGNORECASE):
                in_target_section = False
                continue

            # Skip lines with Stop, Entry, Management keywords
            if re.search(r"(?:Stop|Stoploss|Stopp|SL|Leverage|LEV|Entry|Entries|ENTERY|BUY|SELL|Account|Trailing|RISK|Admin|Contact|Management|Close)", line_str, re.IGNORECASE):
                continue

            # Check for explicit TP line anywhere in message
            # Handles:
            # - TP1: 0.5230, TP1 0.02990, TP: 55000
            # - Target 1 $0.04970, Target 2. $0.04920, • Target 1: 0.02375
            # - 1.🎯 0.08250, 1. 🎯 6907.18
            # - ① 🟢 TP1 ➜ 0.002120
            m_explicit = re.search(
                r"(?:(?:TP\s*\d+|Target\s*\d+)\s*[\.\:\-\>\u279c\u2794\s]*|(?:TP|Target)\s*[:\-\>\u279c\u2794]+\s*|(?:•\s*)?Target\s*\d+\s*[:\-\>\s]*|^\s*\d+[\.\)]\s*[🎯]\s*)\$?([\d\.]+)",
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
                # Subcase 6a: Check hyphen-separated line inside section: "0.04160-0.04000-0.03650"
                if re.search(r"^[\d\.]+(?:\s*-\s*[\d\.]+)+$", line_str):
                    for p in re.split(r"\s*-\s*", line_str):
                        try:
                            v = Decimal(p.strip())
                            if v not in tps:
                                tps.append(v)
                        except InvalidOperation:
                            pass
                    continue

                # Subcase 6b: Check numbered, bulleted, or bare decimal line:
                # Handles:
                # - Bare numbers: "0.0153033", "2410"
                # - Bullets: "1: 2410", "1) 0.0457", "➊ 0.08300", "① 0.0457", "1️⃣ 0.0457", "1. 0.0457", "➤ 0.08300", "• 0.08300"
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

        if not tps:
            return [], "Khong tim thay muc Take Profit hop le"

        return tps, None

    def _parse_tp_weights(self, text: str, tp_count: int) -> Optional[List[Decimal]]:
        """
        Parse explicit TP percentages if provided in text.
        e.g., GRASS: "Close 50% at TP1 and 50% at TP2." -> [0.5, 0.5]
        """
        m_grass = re.search(r"Close\s+(\d+)%\s+at\s+TP1\s+and\s+(\d+)%\s+at\s+TP2", text, re.IGNORECASE)
        if m_grass:
            w1 = Decimal(m_grass.group(1)) / Decimal("100")
            w2 = Decimal(m_grass.group(2)) / Decimal("100")
            return [w1, w2]

        return None

    def _parse_breakeven(self, text: str) -> Tuple[Optional[str], bool]:
        """
        Distinguishes between optional suggestions ("Consider moving SL") and mandatory rules ("Stop: Breakeven - Trigger: Target (1)").
        """
        if "consider moving sl to breakeven" in text.lower():
            return "Consider moving SL to breakeven after TP1", False

        m_eth = re.search(r"Trailing Configuration:\s*Stop:\s*Breakeven\s*-\s*Trigger:\s*Target\s*\((\d+)\)", text, re.IGNORECASE)
        if m_eth:
            return f"Stop: Breakeven - Trigger: Target ({m_eth.group(1)})", True

        return None, False

    def _parse_capital_usage(self, text: str) -> Optional[str]:
        """Extract text describing account usage / margin percentage."""
        m = re.search(r"(?:Account Usage|Risk|Amount|margin of your total portfolio)[^\n]*", text, re.IGNORECASE)
        return m.group(0).strip() if m else None
