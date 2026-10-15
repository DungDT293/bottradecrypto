import re
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple
from core.enums import UpdateType


class ChannelUpdateParser:
    """
    Parses administrative messages and updates:
    - SL modifications
    - Breakeven instructions
    - Entry cancellations
    - Manual closes
    - Brag/result reports (TP hit, SL hit)
    - Corrections
    Enforces that 'TP1 hit' is never confused with an actual exchange fill.
    """

    def parse_update(self, text: str) -> Tuple[UpdateType, Optional[Decimal], Optional[str]]:
        """
        Returns: (UpdateType, new_price_if_applicable, detail_text)
        """
        cleaned = text.strip()

        # 1. Breakeven commands
        if re.search(r"\b(?:move\s+sl\s+to\s+be|sl\s+to\s+breakeven|breakeven|dời\s*sl\s*về\s*hòa\s*vốn|doi\s*sl\s*ve\s*hoa\s*von|sl\s*=\s*entry)\b", cleaned, re.IGNORECASE):
            return UpdateType.MOVE_SL_TO_BREAKEVEN, None, "Yeu cau doi SL ve hoa von"

        # 2. Cancel pending entry
        if re.search(r"\b(?:cancel\s+(?:entry|limit|pending|order)|hủy\s*(?:lệnh|entry|pending)|huy\s*(?:lenh|entry|pending))\b", cleaned, re.IGNORECASE):
            return UpdateType.CANCEL_PENDING_ENTRY, None, "Yeu cau huy pending entry"

        # 3. Close All
        if re.search(r"\b(?:close\s+(?:now|all|position)|exit\s+(?:now|all)|đóng\s*(?:hết|vị\s*thế)|dong\s*(?:het|vi\s*the)|cat\s*lenh)\b", cleaned, re.IGNORECASE):
            return UpdateType.CLOSE_ALL, None, "Yeu cau dong toan bo vi the"

        # 4. Close Partial
        m_partial = re.search(r"\b(?:close|take\s+profit|chốt|chot)\s+(\d+)%", cleaned, re.IGNORECASE)
        if m_partial:
            pct = Decimal(m_partial.group(1))
            return UpdateType.CLOSE_PARTIAL, pct, f"Yeu cau dong mot phan {pct}%"

        # 5. Result reports (Admin boasting or reporting)
        if re.search(r"\b(?:tp\d*\s*hit|target\s*\d*\s*(?:hit|achieved|done)|take\s+profit\s*hit)\b", cleaned, re.IGNORECASE):
            return UpdateType.RESULT_TP_REPORTED, None, "Admin bao TP da cham (KHONG coi day la fill thuc te tai khoan)"

        if re.search(r"\b(?:sl\s*hit|stop\s*loss\s*hit|dính\s*sl|dinh\s*sl)\b", cleaned, re.IGNORECASE):
            return UpdateType.RESULT_SL_REPORTED, None, "Admin bao SL da cham"

        # 6. Signal corrections
        if re.search(r"\b(?:wrong\s*signal|correction|đính\s*chính|dinh\s*chinh|sorry\s*mistyped|nhầm\s*hướng|nham\s*huong)\b", cleaned, re.IGNORECASE):
            return UpdateType.CORRECT_SIGNAL, None, "Admin bao tin nhan bi nham (KHONG coi day la dao chieu vi the)"

        # 7. SL change with new price
        m_sl = re.search(r"(?:new\s*sl|sl\s*(?:to|updated\s*to|\=|\:)|dời\s*sl\s*về|doi\s*sl\s*ve)\s*[:\-\>\s]*\$?([\d\.]+)", cleaned, re.IGNORECASE)
        if m_sl:
            try:
                new_sl = Decimal(m_sl.group(1))
                return UpdateType.SL_CHANGE, new_sl, f"Doi SL sang muc moi: {new_sl}"
            except InvalidOperation:
                pass

        # 8. Commentary or unknown
        if re.search(r"\b(?:hold|wait|stay\s*disciplined|kiên\s*nhẫn|kien\s*nhan)\b", cleaned, re.IGNORECASE):
            return UpdateType.COMMENTARY, None, "Binh luan / nhan dinh thi truong"

        return UpdateType.UNKNOWN, None, "Tin nhan cap nhat khong ro loai"

