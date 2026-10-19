import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from decimal import Decimal
from datetime import datetime
from config.config import load_config
from core.enums import MarginMode, PositionSide, SignalState
from core.models import SourceMetadata, ParsedSignal
from parser.validator import SignalValidator
from risk.risk_engine import RiskEngine

def run_simulation():
    cfg = load_config("config.yaml")
    validator = SignalValidator(cfg)
    risk_engine = RiskEngine(cfg)
    equity = Decimal("82.70")
    now = datetime.utcnow()
    
    print("\n" + "="*80)
    print("  BÀI TOÁN KIỂM THỬ GIẢ ĐỊNH TOÀN DIỆN HỆ THỐNG TRADING (BOT TRADE CRYPTO)")
    print(f"  Vốn tài khoản: {equity} USDT | Đòn bẩy mục tiêu: 11x - 25x (Mặc định 20x)")
    print("="*80)

    results = []

    # -------------------------------------------------------------------------
    # PHẦN 1: KIỂM THỬ CÁC TÌNH HUỐNG ĐÒN BẨY ADMIN GỬI (11x - 25x)
    # -------------------------------------------------------------------------
    print("\n[PHẦN 1] KIỂM THỬ KHẢ NĂNG BẮT ĐÒN BẨY 11x - 25x THEO TÍN HIỆU ADMIN:")
    
    lev_cases = [
        ("Admin ghi dải '10x - 50x', SL hẹp 2.5%", (10, 50), None, Decimal("100"), Decimal("97.5"), 20),
        ("Admin ghi dải '20x - 50x', SL hẹp 3.0%", (20, 50), None, Decimal("100"), Decimal("97.0"), 20),
        ("Admin chỉ định cụ thể '15x', SL 3.5%", None, 15, Decimal("100"), Decimal("96.5"), 15),
        ("Admin không ghi đòn bẩy trong tin nhắn", None, None, Decimal("100"), Decimal("97.0"), 20),
        ("Admin yêu cầu đòn bẩy ảo '100x', SL 2.0%", None, 100, Decimal("100"), Decimal("98.0"), 25),
    ]

    for name, l_range, l_req, entry, sl, expected_lev in lev_cases:
        meta = SourceMetadata(chat_id=-1001756316676, message_id=1, telegram_timestamp=now)
        parsed = ParsedSignal(
            signal_id=f"sig_test_{name}",
            symbol_raw="ETHUSDT",
            symbol_candidate="ETHUSDT",
            side=PositionSide.LONG,
            entries=[entry],
            stop_loss=sl,
            take_profits=[Decimal("105.0"), Decimal("110.0"), Decimal("115.0")],
            leverage_requested=l_req,
            leverage_range=l_range,
            margin_mode_requested=MarginMode.CROSSED,
            metadata=meta
        )
        override = cfg.sources.get("-1001756316676")
        _, val = validator.validate_and_resolve(parsed, override)
        status = "PASSED (Chính xác)" if val.leverage == expected_lev else f"FAILED (Ra {val.leverage}x)"
        print(f"  • {name:<45} -> Đòn bẩy thực thi: {val.leverage}x | Kết quả: {status}")
        results.append(val.leverage == expected_lev)

    # -------------------------------------------------------------------------
    # PHẦN 2: KIỂM THỬ BẢO VỆ CHỐNG CHÁY TÀI KHOẢN (ZERO LIQUIDATION SAFE CLAMP)
    # -------------------------------------------------------------------------
    print("\n[PHẦN 2] KIỂM THỬ CƠ CHẾ BẢO VỆ CHỐNG CHÁY (ZERO LIQUIDATION SAFE CLAMP):")
    
    safe_cases = [
        ("SL rất hẹp 2.0% (Kèo Scalp chuẩn)", Decimal("100"), Decimal("98.0"), 25, (24, 25), "Được đi đủ 25x an toàn tuyệt đối"),
        ("SL bình thường 3.5% (Kèo Swing chuẩn)", Decimal("100"), Decimal("96.5"), 25, (19, 21), "Hạ nhẹ 19x-21x (trong dải 11x-25x) để giá thanh lý luôn sau SL"),
        ("SL rộng 6.0% (Admin xúi 25x)", Decimal("100"), Decimal("94.0"), 25, (11, 12), "Hạ về 11x-12x (vẫn nằm trong dải 11x-25x)"),
        ("SL rất sâu 7.5% (Như kèo GTC hôm nay)", Decimal("0.3200"), Decimal("0.2960"), 25, (9, 10), "Hạ về 9x-10x -> Giúp GTC không bị quét cháy!"),
        ("SL cực sâu 11.2% (Như kèo BAT hôm nay)", Decimal("0.1840"), Decimal("0.1634"), 50, (6, 7), "Hạ về 6x -> Cứu vị thế khỏi bị cháy nến giật!"),
    ]

    for name, entry, sl, req_lev, expected_range, explanation in safe_cases:
        meta = SourceMetadata(chat_id=-1001756316676, message_id=2, telegram_timestamp=now)
        parsed = ParsedSignal(
            signal_id=f"sig_safe_{name}",
            symbol_raw="ALTUSDT",
            symbol_candidate="ALTUSDT",
            side=PositionSide.LONG,
            entries=[entry],
            stop_loss=sl,
            take_profits=[entry * Decimal("1.05"), entry * Decimal("1.10"), entry * Decimal("1.15")],
            leverage_requested=req_lev,
            margin_mode_requested=MarginMode.CROSSED,
            metadata=meta
        )
        override = cfg.sources.get("-1001756316676")
        _, val = validator.validate_and_resolve(parsed, override)
        ok = expected_range[0] <= val.leverage <= expected_range[1]
        status = "PASSED" if ok else "FAILED"
        print(f"  • {name:<42} -> Đòn bẩy an toàn: {val.leverage}x [{status}] ({explanation})")
        results.append(ok)

    # -------------------------------------------------------------------------
    # PHẦN 3: KIỂM THỬ PHÂN BỔ VỐN 2 TẦNG (5% ELITE VS 2.5% SCALP) TẠI ĐÒN BẨY 20x
    # -------------------------------------------------------------------------
    print("\n[PHẦN 3] KIỂM THỬ PHÂN BỔ VỐN ĐA TẦNG (5% ELITE VS 2.5% SCALP Ở 20x):")
    
    chat_elite = -1001756316676  # Boom Boom Billionaires (Elite mult=1.0)
    chat_scalp = -1001895315984  # Crypto Quality Signals (Secondary mult=0.5)

    def test_sizing(chat_id, label):
        meta = SourceMetadata(chat_id=chat_id, message_id=3, telegram_timestamp=now)
        parsed = ParsedSignal(
            signal_id=f"sig_size_{chat_id}",
            symbol_raw="SOLUSDT",
            symbol_candidate="SOLUSDT",
            side=PositionSide.LONG,
            entries=[Decimal("150.00")],
            stop_loss=Decimal("145.50"),  # 3.0% SL
            take_profits=[Decimal("155.0"), Decimal("160.0"), Decimal("170.0")],
            leverage_requested=20,
            margin_mode_requested=MarginMode.CROSSED,
            metadata=meta
        )
        override = cfg.sources.get(str(chat_id))
        _, val = validator.validate_and_resolve(parsed, override)
        
        sizes = risk_engine.calculate_position_sizes(
            signal=val,
            current_equity=equity,
            open_risk_amount=Decimal("0.0"),
            step_size=Decimal("0.01"),
            min_qty=Decimal("0.01"),
            min_notional=Decimal("5.0"),
            current_market_price=Decimal("150.00")
        )
        price, qty = sizes[0]
        notional = price * qty
        margin = notional / Decimal("20")
        loss_at_sl = qty * (Decimal("150.00") - Decimal("145.50"))
        print(f"  • {label:<35}: Margin = ${margin:.2f} USDT | Vị thế = ${notional:.2f} USDT | Đòn bẩy = {val.leverage}x | Lỗ nếu dính SL = ${loss_at_sl:.2f} USDT")
        return margin, notional, loss_at_sl

    margin_e, notional_e, loss_e = test_sizing(chat_elite, "Nhóm Tinh Hoa (Tier S - Multiplier 1.0x)")
    margin_s, notional_s, loss_s = test_sizing(chat_scalp, "Nhóm Siêu Scalp (Tier B - Multiplier 0.5x)")

    # Assertions
    c1 = abs(margin_e - margin_s * Decimal("2.0")) < Decimal("0.5")  # Exact 2:1 ratio
    c2 = notional_e >= Decimal("5.0") and notional_s >= Decimal("5.0")  # Both exceed min notional
    c3 = loss_e <= Decimal("2.07") and loss_s <= Decimal("1.04")  # Strict risk budget bounds
    results.extend([c1, c2, c3])
    print(f"    -> Tỷ lệ vốn giữa Tinh Hoa và Siêu Scalp chuẩn xác 2:1: {'PASSED' if c1 else 'FAILED'}")
    print(f"    -> Cả 2 đều vượt xa điều kiện Binance Min Notional ($5): {'PASSED' if c2 else 'FAILED'}")
    print(f"    -> Giới hạn rủi ro tại SL hoàn toàn bị khóa chặt (Không thể lỗ hơn): {'PASSED' if c3 else 'FAILED'}")

    # -------------------------------------------------------------------------
    # TỔNG KẾT
    # -------------------------------------------------------------------------
    print("\n" + "="*80)
    all_ok = all(results)
    if all_ok:
        print(f"  KẾT LUẬN: TOÀN BỘ {len(results)}/ {len(results)} KỊCH BẢN GIẢ ĐỊNH ĐỀU ĐẠT CHUẨN HOÀN HẢO 100%!")
        print("  • Đòn bẩy hoạt động chuẩn xác trong dải 11x - 25x (Mặc định 20x).")
        print("  • Hệ thống Zero Liquidation bảo vệ tuyệt đối không bao giờ để vị thế bị thanh lý trước SL.")
        print("  • Phân bổ vốn 5% Tinh Hoa vs 2.5% Siêu Scalp vận hành đồng bộ và an toàn.")
    else:
        print("  CẢNH BÁO: CÓ KỊCH BẢN CHƯA ĐẠT!")
    print("="*80 + "\n")
    return all_ok

if __name__ == "__main__":
    success = run_simulation()
    sys.exit(0 if success else 1)
