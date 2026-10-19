import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import urllib.request
import json
from decimal import Decimal
from datetime import datetime
from config.config import load_config
from core.enums import MarginMode, PositionSide
from core.models import SourceMetadata, ParsedSignal
from parser.validator import SignalValidator
from risk.risk_engine import RiskEngine

def verify_running_backend(session_token: str = None, port: int = None):
    print("\n" + "="*85)
    print("  KIỂM TRA ĐỐI SOÁT TOÀN DIỆN TIẾN TRÌNH BACKEND ĐANG CHẠY")
    print("="*85)

    handshake_file = Path(r"C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\backend_handshake.json")
    if handshake_file.exists():
        try:
            with open(handshake_file, "r", encoding="utf-8") as f:
                hs_data = json.load(f)
                if not port:
                    port = hs_data.get("port")
                if not session_token:
                    session_token = hs_data.get("session_token")
                print(f"   [Handshake] Nạp thông tin kết nối: PID {hs_data.get('pid')}, Port {port}")
        except Exception as e:
            print(f"   [Handshake Warning] Không đọc được handshake file: {e}")

    effective_port = port or 55563
    
    # 1. Health Endpoint
    health_url = f"http://127.0.0.1:{effective_port}/health"
    req_h = urllib.request.urlopen(health_url)
    h_data = json.loads(req_h.read())
    print("\n1. KẾT QUẢ ENDPOINT /health:")
    print(f"   • Status:               {h_data.get('status')}")
    print(f"   • Version:              {h_data.get('version')}")
    print(f"   • Mode:                 {h_data.get('mode')}")
    print(f"   • Live Trading:         {h_data.get('live_trading_enabled')}")
    print(f"   • Engine Status:        {h_data.get('engine_status')}")
    print(f"   • Entry Enabled:        {h_data.get('entry_enabled')}")
    
    assert h_data.get('status') == 'HEALTHY', "Backend status is not HEALTHY!"
    assert h_data.get('version') == '1.3.0', f"Backend version mismatch: {h_data.get('version')}"
    assert h_data.get('mode') == 'LIVE', "Backend is not in LIVE mode!"
    print("   -> [PASS] Health check đạt chuẩn v1.3.0 LIVE.")

    # 2. Settings Endpoint (with token)
    if session_token:
        settings_url = f"http://127.0.0.1:{effective_port}/settings"
        req_s = urllib.request.Request(settings_url, headers={"X-Session-Token": session_token})
        s_data = json.loads(urllib.request.urlopen(req_s).read())
        print("\n2. KẾT QUẢ ENDPOINT /settings:")
        print(f"   • Risk per signal:      {s_data.get('risk_per_signal_pct')}%")
        print(f"   • Max leverage:         {s_data.get('max_leverage')}x")
        print(f"   • Margin mode:          {s_data.get('margin_mode')}")
        print(f"   • TP1 target weight:    {s_data.get('tp1_target_weight_pct')}%")
        print(f"   • Breakeven after TP1:  {s_data.get('breakeven_after_tp1')}")
        
        assert s_data.get('max_leverage') == 25, f"Expected max_leverage 25, got {s_data.get('max_leverage')}"
        assert s_data.get('risk_per_signal_pct') == 2.5, f"Expected risk 2.5, got {s_data.get('risk_per_signal_pct')}"
        assert s_data.get('tp1_target_weight_pct') == 35.0, f"Expected TP1 35.0%, got {s_data.get('tp1_target_weight_pct')}"
        print("   -> [PASS] Settings nạp đúng các tham số mới nhất.")

    # 3. Channel Config Verification (from running backend config)
    cfg_path = r"C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\config.yaml"
    cfg = load_config(cfg_path)
    print("\n3. KIỂM TRA 18 KÊNH THEO DÕI TRONG CONFIG ĐANG CHẠY:")
    elite_ids = [-1001756316676, -1002052872813, -1001754095061, -1002007658025, -1001552004524]
    
    print("   [Nhóm Tinh Hoa - 5 Kênh]:")
    for eid in elite_ids:
        src = cfg.sources.get(eid) or cfg.sources.get(str(eid))
        assert src is not None, f"Missing source {eid}"
        mult = getattr(src, "margin_multiplier", 1.0)
        max_l = getattr(src, "max_leverage_override", 25)
        def_l = getattr(src, "default_leverage_override", 20)
        assert mult == Decimal("1.0") or mult == 1.0, f"Elite channel {eid} mult is {mult} (expected 1.0)"
        assert max_l == 25, f"Elite channel {eid} max_l is {max_l} (expected 25)"
        assert def_l == 20, f"Elite channel {eid} def_l is {def_l} (expected 20)"
        print(f"   • {src.name:<32} (ID: {eid}) | mult = {mult}x (5% Vốn) | Lev = {def_l}x-{max_l}x")
        
    print("\n   [Nhóm Siêu Scalp - 13 Kênh]:")
    for sid, src in cfg.sources.items():
        if int(sid) in elite_ids:
            continue
        mult = getattr(src, "margin_multiplier", 0.5)
        max_l = getattr(src, "max_leverage_override", 25)
        def_l = getattr(src, "default_leverage_override", 20)
        assert mult == Decimal("0.5") or mult == 0.5, f"Scalp channel {sid} mult is {mult} (expected 0.5)"
        assert max_l == 25, f"Scalp channel {sid} max_l is {max_l} (expected 25)"
        assert def_l == 20, f"Scalp channel {sid} def_l is {def_l} (expected 20)"
        print(f"   • {src.name:<32} (ID: {sid}) | mult = {mult}x (2.5% Vốn - đúng 1 nửa) | Lev = {def_l}x-{max_l}x")

    # 4. Calculation Check
    validator = SignalValidator(cfg)
    risk_engine = RiskEngine(cfg)
    equity = Decimal("82.70")
    now = datetime.utcnow()
    
    print("\n4. THỬ NGHIỆM TÍNH TOÁN LỆNH THỰC TẾ QUA RISK ENGINE & VALIDATOR:")
    # Elite Test
    parsed_e = ParsedSignal(
        signal_id="sig_test_elite_run",
        symbol_raw="SOLUSDT",
        symbol_candidate="SOLUSDT",
        side=PositionSide.LONG,
        entries=[Decimal("150.00")],
        stop_loss=Decimal("145.50"), # 3.0%
        take_profits=[Decimal("155.0"), Decimal("160.0"), Decimal("170.0")],
        leverage_range=(10, 50),
        margin_mode_requested=MarginMode.CROSSED,
        metadata=SourceMetadata(chat_id=-1001756316676, message_id=111, telegram_timestamp=now)
    )
    src_e = cfg.sources.get(-1001756316676) or cfg.sources.get("-1001756316676")
    _, val_e = validator.validate_and_resolve(parsed_e, src_e)
    sizes_e = risk_engine.calculate_position_sizes(
        val_e, equity, Decimal("0"), Decimal("0.01"), Decimal("0.01"), Decimal("5.0"), Decimal("150.00")
    )
    p_e, q_e = sizes_e[0]
    notional_e = p_e * q_e
    margin_e = notional_e / Decimal(str(val_e.leverage))
    
    # Scalp Test
    parsed_s = ParsedSignal(
        signal_id="sig_test_scalp_run",
        symbol_raw="SOLUSDT",
        symbol_candidate="SOLUSDT",
        side=PositionSide.LONG,
        entries=[Decimal("150.00")],
        stop_loss=Decimal("145.50"), # 3.0%
        take_profits=[Decimal("155.0"), Decimal("160.0"), Decimal("170.0")],
        leverage_range=(10, 50),
        margin_mode_requested=MarginMode.CROSSED,
        metadata=SourceMetadata(chat_id=-1001895315984, message_id=112, telegram_timestamp=now)
    )
    src_s = cfg.sources.get(-1001895315984) or cfg.sources.get("-1001895315984")
    _, val_s = validator.validate_and_resolve(parsed_s, src_s)
    sizes_s = risk_engine.calculate_position_sizes(
        val_s, equity, Decimal("0"), Decimal("0.01"), Decimal("0.01"), Decimal("5.0"), Decimal("150.00")
    )
    p_s, q_s = sizes_s[0]
    notional_s = p_s * q_s
    margin_s = notional_s / Decimal(str(val_s.leverage))

    print(f"   • Lệnh Tinh Hoa (5% Vốn): Margin = ${margin_e:.2f} USDT | Đòn bẩy = {val_e.leverage}x | Vị thế = ${notional_e:.2f} USDT")
    print(f"   • Lệnh Siêu Scalp (2.5% Vốn): Margin = ${margin_s:.2f} USDT | Đòn bẩy = {val_s.leverage}x | Vị thế = ${notional_s:.2f} USDT")
    
    assert val_e.leverage == 20, f"Elite leverage is {val_e.leverage}"
    assert val_s.leverage == 20, f"Scalp leverage is {val_s.leverage}"
    assert abs(margin_e - margin_s * Decimal("2.0")) < Decimal("0.5"), "Ratio is not 2:1!"
    print("   -> [PASS] Lệnh Tinh Hoa và Siêu Scalp được tính toán chuẩn xác tỷ lệ 2:1 và đòn bẩy 20x.")
    print("="*85 + "\n")

if __name__ == "__main__":
    token = sys.argv[1] if len(sys.argv) > 1 else None
    verify_running_backend(token)

