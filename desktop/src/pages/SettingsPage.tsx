import React, { useState, useEffect, useRef } from "react";
import { Save, ShieldCheck, Percent } from "lucide-react";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";
import { ConfirmModal } from "../components/ConfirmModal";
import { CapitalRiskSimulator } from "../components/CapitalRiskSimulator";
import type { AppSettings } from "../types/api";

const DEFAULT_SETTINGS: AppSettings = {
  mode: "READ_ONLY",
  live_trading_enabled: false,
  ferrari_mode_enabled: false,
  max_total_open_risk_pct: 15.0,
  risk_per_signal_pct: 2.5,
  max_daily_loss_pct: 10.0,
  max_leverage: 25,
  margin_mode: "CROSSED",
  entry_range_policy: "SPLIT_2_LIMITS",
  multi_tp_default_weight_mode: "FIXED_35_35_30",
  tp1_target_weight_pct: 35,
  breakeven_after_tp1: true,
  sl_buffer_pct: 0.3,
  max_active_signals: 20,
  daily_profit_target_enabled: true,
  daily_profit_target_usdt: 8.0,
  basket_trailing_enabled: true,
  basket_trailing_trigger_usdt: 8.0,
  basket_trailing_pullback_pct: 25.0,
};

const finiteOr = (value: number | undefined, fallback: number | undefined): number =>
  typeof value === "number" && Number.isFinite(value) ? value : (fallback ?? 0);

const normalizeSettings = (data: Partial<AppSettings>): AppSettings => ({
  ...DEFAULT_SETTINGS,
  ...data,
  ferrari_mode_enabled: Boolean(data.ferrari_mode_enabled),
  max_total_open_risk_pct: finiteOr(data.max_total_open_risk_pct, DEFAULT_SETTINGS.max_total_open_risk_pct),
  risk_per_signal_pct: finiteOr(data.risk_per_signal_pct, DEFAULT_SETTINGS.risk_per_signal_pct),
  max_daily_loss_pct: finiteOr(data.max_daily_loss_pct, DEFAULT_SETTINGS.max_daily_loss_pct),
  max_leverage: finiteOr(data.max_leverage, DEFAULT_SETTINGS.max_leverage),
  tp1_target_weight_pct: finiteOr(data.tp1_target_weight_pct, DEFAULT_SETTINGS.tp1_target_weight_pct),
  sl_buffer_pct: finiteOr(data.sl_buffer_pct, DEFAULT_SETTINGS.sl_buffer_pct),
  max_active_signals: finiteOr(data.max_active_signals, DEFAULT_SETTINGS.max_active_signals),
  daily_profit_target_enabled: data.daily_profit_target_enabled !== undefined ? Boolean(data.daily_profit_target_enabled) : DEFAULT_SETTINGS.daily_profit_target_enabled,
  daily_profit_target_usdt: finiteOr(data.daily_profit_target_usdt, DEFAULT_SETTINGS.daily_profit_target_usdt),
  basket_trailing_enabled: data.basket_trailing_enabled !== undefined ? Boolean(data.basket_trailing_enabled) : DEFAULT_SETTINGS.basket_trailing_enabled,
  basket_trailing_trigger_usdt: finiteOr(data.basket_trailing_trigger_usdt, DEFAULT_SETTINGS.basket_trailing_trigger_usdt),
  basket_trailing_pullback_pct: finiteOr(data.basket_trailing_pullback_pct, DEFAULT_SETTINGS.basket_trailing_pullback_pct),
});

export const SettingsPage: React.FC = () => {
  const { addToast, refreshSnapshot, snapshot } = useApp();
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);
  const [loading, setLoading] = useState(true);
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showLiveConfirmModal, setShowLiveConfirmModal] = useState(false);
  const settingsRequestId = useRef(0);
  const [autostartEnabled, setAutostartEnabled] = useState(false);

  const fetchSettings = async () => {
    const requestId = ++settingsRequestId.current;
    setLoading(true);
    try {
      const data = await api.getSettings();
      if (requestId !== settingsRequestId.current) return;
      setSettings(normalizeSettings(data));
      setSettingsLoaded(true);
    } catch (err: any) {
      if (requestId === settingsRequestId.current) addToast("Lỗi tải thông tin cài đặt.", "error");
    } finally {
      if (requestId === settingsRequestId.current) setLoading(false);
    }
  };

  useEffect(() => {
    fetchSettings();
    const checkAutostart = async () => {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        const enabled = await invoke<boolean>("is_autostart_enabled");
        setAutostartEnabled(enabled);
      } catch {
        // Not in Tauri
      }
    };
    checkAutostart();
  }, []);

  const handleToggleAutostart = async (enabled: boolean) => {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      if (enabled) {
        await invoke("enable_autostart");
        setAutostartEnabled(true);
        addToast("Đã kích hoạt tự động khởi động cùng Windows khi mở máy!", "success");
      } else {
        await invoke("disable_autostart");
        setAutostartEnabled(false);
        addToast("Đã tắt tự động khởi động cùng Windows.", "info");
      }
    } catch (err: any) {
      addToast(err?.message || "Lỗi cấu hình khởi động cùng Windows.", "error");
    }
  };


  const handleToggleLive = (enabled: boolean) => {
    if (enabled) {
      setShowLiveConfirmModal(true);
    } else {
      setSettings((prev) => ({ ...prev, live_trading_enabled: false }));
    }
  };

  const handleConfirmLive = () => {
    setSettings((prev) => ({ ...prev, mode: "LIVE", live_trading_enabled: true }));
    setShowLiveConfirmModal(false);
    addToast("Đã bật chế độ Giao dịch Tiền Thật (LIVE TRADING). Vui lòng nhấn 'Lưu Cài Đặt' ở góc trên để kích hoạt.", "warning");
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const isLive = settings.mode === "LIVE" || settings.live_trading_enabled;
      await api.updateSettings(settings, isLive ? "ENABLE_LIVE_TRADING" : undefined);
      addToast("Đã lưu thành công cấu hình hệ thống và rủi ro.", "success");
      await refreshSnapshot();
    } catch (err: any) {
      addToast(err?.user_message || err?.message || "Lỗi lưu cài đặt.", "error");
    } finally {
      setSaving(false);
    }
  };

  // Dynamic TP calculation
  let tp1 = 20;
  let tp2 = 40;
  let tp3 = 40;

  if (settings.multi_tp_default_weight_mode === "FIXED_20_40_40") {
    tp1 = 20;
    tp2 = 40;
    tp3 = 40;
  } else if (settings.multi_tp_default_weight_mode === "FIXED_35_35_30") {
    tp1 = 35;
    tp2 = 35;
    tp3 = 30;
  } else if (settings.multi_tp_default_weight_mode === "FRONT_LOADED_50_30_20") {
    tp1 = 50;
    tp2 = 30;
    tp3 = 20;
  } else if (settings.multi_tp_default_weight_mode === "EQUAL_SPLIT") {
    tp1 = 33.3;
    tp2 = 33.3;
    tp3 = 33.4;
  } else {
    tp1 = Math.min(90, Math.max(10, settings.tp1_target_weight_pct ?? 20));
    const rem = Math.max(0, 100 - tp1);
    tp2 = Math.round(rem * 0.65 * 10) / 10;
    tp3 = Math.round((rem - tp2) * 10) / 10;
  }
  const remainder = Math.max(0, Math.round((100 - tp1) * 10) / 10);

  const liveEquityValue = snapshot?.account?.equity ?? snapshot?.account?.wallet_balance;
  const liveEquity = liveEquityValue == null ? 0 : Number(liveEquityValue);
  const safeLiveEquity = Number.isFinite(liveEquity) && liveEquity > 0 ? liveEquity : 0;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
        <div>
          <h2 style={{ fontSize: "20px", fontWeight: 700, color: "#fff" }}>Cài Đặt Hệ Thống</h2>
          <p style={{ color: "var(--text-secondary)", fontSize: "13px" }}>
            Quản trị rủi ro, chính sách đòn bẩy, chế độ thực thi lệnh và kiểm soát an toàn.
          </p>
        </div>

        <button className="btn btn-primary" onClick={handleSave} disabled={saving || loading || !settingsLoaded}>
          <Save size={14} />
          <span>{saving ? "Đang lưu..." : loading ? "Đang tải..." : "Lưu Cài Đặt"}</span>
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px" }}>
        {/* Execution Mode Card */}
        <div className="card">
          <div className="card-title">
            <span style={{ fontSize: "16px", fontWeight: 600, color: "#fff" }}>Chế Độ Thực Thi</span>
          </div>

          <div style={{ marginTop: "16px" }}>
            <div className="form-group">
              <label className="form-label">Chọn Chế độ Vận hành</label>
              <select
                className="form-input"
                value={settings.mode}
                onChange={(e) => {
                  const targetMode = e.target.value as any;
                  if (targetMode === "LIVE") {
                    setShowLiveConfirmModal(true);
                  } else {
                    setSettings((prev) => ({ ...prev, mode: targetMode, live_trading_enabled: false }));
                  }
                }}
              >
                <option value="READ_ONLY">READ_ONLY (Khuyến nghị: Chỉ đọc, khóa mọi lệnh sàn Binance)</option>
                <option value="SHADOW">SHADOW (Mô phỏng khớp lệnh theo giá thị trường thời gian thực)</option>
                <option value="PAPER">PAPER (Giả lập giao dịch có tính trượt giá & phí sàn)</option>
                <option value="TESTNET">TESTNET (Giao dịch thật trên môi trường Binance Futures Testnet)</option>
                <option value="LIVE">LIVE (Giao dịch TIỀN THẬT trên Binance USD-M Futures)</option>
              </select>
            </div>

            <div style={{ padding: "14px", background: "var(--bg-input)", borderRadius: "8px", border: settings.live_trading_enabled ? "1px solid #22c55e" : "1px solid var(--border-color)", marginTop: "14px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <div style={{ fontWeight: 600, color: settings.live_trading_enabled ? "#22c55e" : "#fff" }}>
                    Kích Hoạt Giao Dịch Live (Tiền Thật)
                  </div>
                  <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "2px" }}>
                    {settings.live_trading_enabled
                      ? "ĐANG BẬT: Bot sẽ đặt lệnh thật trực tiếp trên Binance Futures bằng số dư ví Live."
                      : "ĐÃ TẮT: Khóa mọi lệnh thật ra sàn Binance (bảo vệ tài khoản an toàn)."}
                  </div>
                </div>
                <input
                  type="checkbox"
                  checked={settings.live_trading_enabled}
                  onChange={(e) => handleToggleLive(e.target.checked)}
                  style={{ width: "20px", height: "20px", cursor: "pointer" }}
                />
              </div>
            </div>

            <div style={{ padding: "14px", background: "var(--bg-input)", borderRadius: "8px", border: "1px solid var(--border-color)", marginTop: "14px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <div style={{ fontWeight: 600, color: "#fff" }}>Khởi Động Cùng Windows (Autostart)</div>
                  <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "2px" }}>
                    Tự động khởi chạy bot ngầm khi bạn mở máy tính
                  </div>
                </div>
                <input
                  type="checkbox"
                  checked={autostartEnabled}
                  onChange={(e) => handleToggleAutostart(e.target.checked)}
                  style={{ width: "20px", height: "20px", cursor: "pointer" }}
                />
              </div>
            </div>

            {/* Ferrari Mode (No Risk No Ferrari) Toggle Box */}
            <div
              style={{
                padding: "16px",
                background: settings.ferrari_mode_enabled
                  ? "linear-gradient(135deg, rgba(239, 68, 68, 0.18), rgba(185, 28, 28, 0.08))"
                  : "var(--bg-input)",
                borderRadius: "8px",
                border: settings.ferrari_mode_enabled ? "1px solid #ef4444" : "1px solid var(--border-color)",
                marginTop: "14px",
                boxShadow: settings.ferrari_mode_enabled ? "0 0 15px rgba(239, 68, 68, 0.25)" : "none",
                transition: "all 0.3s ease",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <div style={{ fontWeight: 700, color: settings.ferrari_mode_enabled ? "#ff4d4d" : "#fff", display: "flex", alignItems: "center", gap: "8px" }}>
                    <span style={{ fontSize: "16px" }}>🏎️</span>
                    <span>FERRARI MODE (x35 - x40 & Khớp Mọi Kèo)</span>
                    {settings.ferrari_mode_enabled && (
                      <span style={{ fontSize: "10px", background: "#ef4444", color: "#fff", padding: "1px 6px", borderRadius: "10px", fontWeight: 700 }}>
                        ACTIVE
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px" }}>
                    {settings.ferrari_mode_enabled
                      ? "ĐANG BẬT: Xác nhận chấp nhận rủi ro lớn để săn lợi nhuận lớn: Đòn bẩy x35-40, Rủi ro 5.0%, Bỏ van chờ 15 phút, Khớp mọi kèo đạt chuẩn."
                      : "ĐÃ TẮT: Tự động kích hoạt CHẾ ĐỘ AN TOÀN (Bảo toàn vốn: Đòn bẩy 15x-20x, Giãn cách 15p, Rủi ro 1.5%, Zero-Liquidation)."}
                  </div>
                </div>
                <input
                  type="checkbox"
                  checked={settings.ferrari_mode_enabled ?? false}
                  onChange={(e) => {
                    const enabled = e.target.checked;
                    setSettings((prev) => ({
                      ...prev,
                      ferrari_mode_enabled: enabled,
                      max_leverage: enabled ? 40 : 20,
                      risk_per_signal_pct: enabled ? 5.0 : 1.5,
                      max_active_signals: enabled ? 20 : 3,
                      multi_tp_default_weight_mode: "FIXED_35_35_30",
                      tp1_target_weight_pct: 35,
                      max_total_open_risk_pct: enabled ? 150 : 20,
                    }));
                  }}
                  style={{ width: "22px", height: "22px", cursor: "pointer", accentColor: "#ef4444" }}
                />
              </div>
            </div>
          </div>
        </div>


        {/* Risk Management Card */}
        <div className="card">
          <div className="card-title">
            <span style={{ fontSize: "16px", fontWeight: 600, color: "#fff" }}>Quản Trị Rủi Ro & Vốn</span>
          </div>

          <div style={{ marginTop: "16px" }}>
            <div className="form-group">
              <label className="form-label">% Rủi ro tối đa mỗi tín hiệu (Risk per signal %)</label>
              <input
                type="number"
                step="0.1"
                min="0.1"
                max="10.0"
                className="form-input mono"
                value={settings.risk_per_signal_pct}
                onChange={(e) => setSettings({ ...settings, risk_per_signal_pct: parseFloat(e.target.value) || 0 })}
              />
            </div>

            <div className="form-group">
              <label className="form-label">% Giới hạn lỗ tối đa trong ngày (Max Daily Loss %)</label>
              <input
                type="number"
                step="0.5"
                min="1.0"
                max="20.0"
                className="form-input mono"
                value={settings.max_daily_loss_pct}
                onChange={(e) => setSettings({ ...settings, max_daily_loss_pct: parseFloat(e.target.value) || 0 })}
              />
            </div>

            <div className="form-group">
              <label className="form-label">Đòn bẩy trần tối đa cho phép (Max Leverage)</label>
              <input
                type="number"
                min="1"
                max="125"
                className="form-input mono"
                value={settings.max_leverage}
                onChange={(e) => setSettings({ ...settings, max_leverage: parseInt(e.target.value) || 1 })}
              />
            </div>

            <div className="form-group">
              <label className="form-label" style={{ display: "flex", justifyContent: "space-between" }}>
                <span>Số lệnh / vị thế tối đa cùng lúc (Max Active Signals)</span>
                <span style={{ color: "#10b981", fontWeight: 700 }}>{settings.max_active_signals ?? 20} lệnh</span>
              </label>
              <input
                type="number"
                min="1"
                max="30"
                className="form-input mono"
                value={settings.max_active_signals ?? 20}
                onChange={(e) => setSettings({ ...settings, max_active_signals: parseInt(e.target.value) || 20 })}
              />
              <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                Cho phép bot mở tối đa tới 20 vị thế đồng thời khi thị trường có nhiều kèo tiềm năng.
              </div>
            </div>

            <div className="form-group">
              <label className="form-label" style={{ display: "flex", justifyContent: "space-between" }}>
                <span>Trần tổng rủi ro mở cùng lúc (Max Open Risk %)</span>
                <span style={{ color: settings.ferrari_mode_enabled ? "#ef4444" : "#10b981", fontWeight: 700 }}>
                  {settings.max_total_open_risk_pct ?? 15}%
                </span>
              </label>
              <input
                type="number"
                step="5.0"
                min="5.0"
                max="200.0"
                className="form-input mono"
                value={settings.max_total_open_risk_pct ?? 15}
                onChange={(e) => setSettings({ ...settings, max_total_open_risk_pct: parseFloat(e.target.value) || 15 })}
              />
              <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                {settings.ferrari_mode_enabled
                  ? "🏎️ FERRARI MODE: Đã mở trần 150% để vào mọi kèo Telegram liên tục mà không bao giờ bị nghẽn lệnh."
                  : "Mức trần mở lệnh đồng thời. Đặt >= 100% để tắt hoàn toàn cơ chế chặn lệnh mở."}
              </div>
            </div>

            <div className="form-group" style={{ marginTop: "14px", padding: "12px", background: "rgba(56, 189, 248, 0.05)", borderRadius: "8px", border: "1px solid rgba(56, 189, 248, 0.2)" }}>
              <label className="form-label" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontWeight: 600, color: "#38bdf8" }}>Đệm chống quét râu SL sàn Binance (%)</span>
                <span style={{ color: "#38bdf8", fontWeight: 700, fontSize: "14px" }}>{settings.sl_buffer_pct ?? 1.0}%</span>
              </label>
              <input
                type="number"
                step="0.1"
                min="0.0"
                max="5.0"
                className="form-input mono"
                value={settings.sl_buffer_pct ?? 1.0}
                onChange={(e) => setSettings({ ...settings, sl_buffer_pct: parseFloat(e.target.value) || 0 })}
              />
              <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "4px" }}>
                Tự động nới khoảng cách SL ra thêm 1% so với giá Admin đưa để tránh bị râu nến Binance chạm SL (Khối lượng vào lệnh sẽ được tự động co lại để giữ nguyên mức rủi ro tiền tệ).
              </div>
            </div>
          </div>
        </div>

        {/* Real-time Capital & Risk Projection Simulator */}
        <CapitalRiskSimulator
          riskPerSignalPct={settings.risk_per_signal_pct ?? 2.5}
          maxDailyLossPct={settings.max_daily_loss_pct ?? 15.0}
          tp1WeightPct={tp1}
          tp2WeightPct={tp2}
          tp3WeightPct={tp3}
          liveEquity={safeLiveEquity}
          onApplyRisk={(newRisk) => setSettings((prev) => ({ ...prev, risk_per_signal_pct: newRisk }))}
        />

        {/* Execution Policy Card */}
        <div className="card" style={{ gridColumn: "span 2" }}>
          <div className="card-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: "16px", fontWeight: 600, color: "#fff" }}>Chính Sách Khớp Lệnh & Chốt Lời Đa Tầng</span>
            <span style={{ fontSize: "12px", background: "rgba(16, 185, 129, 0.15)", color: "#10b981", padding: "4px 10px", borderRadius: "12px", fontWeight: 600 }}>
              Kèo Bất Tử (Risk-Free Trade)
            </span>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px", marginTop: "16px" }}>
            <div className="form-group">
              <label className="form-label">Margin Mode</label>
              <select
                className="form-input"
                value={settings.margin_mode}
                onChange={(e) => setSettings({ ...settings, margin_mode: e.target.value as AppSettings["margin_mode"] })}
              >
                <option value="CROSSED">CROSSED</option>
                <option value="ISOLATED">ISOLATED</option>
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">Quy tắc chọn Entry khi gặp vùng giá (Range Entry)</label>
              <select
                className="form-input"
                value={settings.entry_range_policy}
                onChange={(e) => setSettings({ ...settings, entry_range_policy: e.target.value as AppSettings["entry_range_policy"] })}
              >
                <option value="SPLIT_2_LIMITS">SPLIT_2_LIMITS (Chia 50/50 hai đầu vùng giá - Chống lỡ tàu & Triệt tiêu Adverse Selection)</option>
                <option value="BEST_PRICE">BEST_PRICE (Ưu tiên giá khớp tối ưu nhất cho vị thế)</option>
                <option value="MID_POINT">MID_POINT (Giá trung bình giữa Entry 1 và Entry 2)</option>
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">Phân bổ tỷ trọng chốt lời nhiều TP (Multi-TP Distribution)</label>
              <select
                className="form-input"
                value={settings.multi_tp_default_weight_mode}
                onChange={(e) => {
                  const val = e.target.value as AppSettings["multi_tp_default_weight_mode"];
                  if (val === "FIXED_20_40_40") {
                    setSettings({ ...settings, multi_tp_default_weight_mode: val, tp1_target_weight_pct: 20 });
                  } else if (val === "FIXED_35_35_30") {
                    setSettings({ ...settings, multi_tp_default_weight_mode: val, tp1_target_weight_pct: 35 });
                  } else if (val === "FRONT_LOADED_50_30_20") {
                    setSettings({ ...settings, multi_tp_default_weight_mode: val, tp1_target_weight_pct: 50 });
                  } else if (val === "EQUAL_SPLIT") {
                    setSettings({ ...settings, multi_tp_default_weight_mode: val, tp1_target_weight_pct: 33.3 });
                  } else {
                    setSettings({ ...settings, multi_tp_default_weight_mode: val });
                  }
                }}
              >
                <option value="FIXED_20_40_40">CHUẨN TỐI ƯU LỢI NHUẬN: TP1 20% - TP2 40% - TP3 40% (Mới - Khuyến nghị)</option>
                <option value="FIXED_35_35_30">BẢO VỆ VỐN CAO: TP1 35% - TP2 35% - TP3 30%</option>
                <option value="CUSTOM_TP1_RATIO">CUSTOM_TP1 (Tùy chỉnh TP1 - Tự động tính TP2 & TP3 thông minh)</option>
                <option value="EQUAL_SPLIT">EQUAL_SPLIT (Chia đều khối lượng cho tất cả các TP)</option>
                <option value="FRONT_LOADED_50_30_20">FRONT_LOADED_50_30_20 (Cố định: TP1 50%, TP2 30%, TP3 20%)</option>
              </select>
            </div>
          </div>

          {/* Dynamic TP1 Slider & Auto Recalibration Box */}
          <div style={{ marginTop: "20px", padding: "18px", background: "var(--bg-input)", borderRadius: "8px", border: "1px solid var(--border-color)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
              <div>
                <span style={{ fontWeight: 600, color: "#fff", display: "flex", alignItems: "center", gap: "6px" }}>
                  <Percent size={15} style={{ color: "var(--accent-color)" }} />
                  Tỷ lệ chốt lời TP1 mục tiêu (Target TP1 Allocation):
                </span>
                <span style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "2px", display: "block" }}>
                  Kéo chỉnh tỷ lệ chốt lời tại TP1. Hệ thống tự động chuyển sang chế độ Tùy chỉnh (CUSTOM_TP1) và phân bổ thông minh cho TP2 & TP3.
                </span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <input
                  type="number"
                  min="10"
                  max="90"
                  step="5"
                  className="form-input mono"
                  style={{ width: "80px", textAlign: "center", fontSize: "15px", fontWeight: 700, color: "#10b981" }}
                  value={tp1}
                  onChange={(e) => {
                    const val = parseFloat(e.target.value) || 20;
                    setSettings({
                      ...settings,
                      multi_tp_default_weight_mode: "CUSTOM_TP1_RATIO",
                      tp1_target_weight_pct: val,
                    });
                  }}
                />
                <span style={{ fontWeight: 700, color: "#10b981" }}>%</span>
              </div>
            </div>

            <input
              type="range"
              min="10"
              max="90"
              step="5"
              value={tp1}
              onChange={(e) => {
                const val = parseInt(e.target.value) || 20;
                setSettings({
                  ...settings,
                  multi_tp_default_weight_mode: "CUSTOM_TP1_RATIO",
                  tp1_target_weight_pct: val,
                });
              }}
              style={{ width: "100%", cursor: "pointer", accentColor: "#10b981" }}
            />

            {/* Visual Color Segmented Bar */}
            <div style={{ marginTop: "16px", height: "14px", borderRadius: "7px", overflow: "hidden", display: "flex", background: "#1a1f2c" }}>
              <div style={{ width: `${tp1}%`, background: "#10b981", transition: "width 0.2s" }} title={`TP1: ${tp1}%`} />
              <div style={{ width: `${tp2}%`, background: "#3b82f6", transition: "width 0.2s" }} title={`TP2: ${tp2}%`} />
              <div style={{ width: `${tp3}%`, background: "#8b5cf6", transition: "width 0.2s" }} title={`TP3: ${tp3}%`} />
            </div>

            {/* Live Breakdown Cards */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "12px", marginTop: "14px" }}>
              <div style={{ padding: "10px", background: "rgba(16, 185, 129, 0.1)", borderRadius: "6px", border: "1px solid rgba(16, 185, 129, 0.3)" }}>
                <div style={{ fontSize: "11px", color: "var(--text-secondary)", fontWeight: 600 }}>MỨC TP 1 (Chủ lực)</div>
                <div style={{ fontSize: "18px", fontWeight: 700, color: "#10b981", marginTop: "2px" }}>{tp1}%</div>
                <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>Chốt ngay phần lớn & đút túi tiền lời</div>
              </div>

              <div style={{ padding: "10px", background: "rgba(59, 130, 246, 0.1)", borderRadius: "6px", border: "1px solid rgba(59, 130, 246, 0.3)" }}>
                <div style={{ fontSize: "11px", color: "var(--text-secondary)", fontWeight: 600 }}>MỨC TP 2 (Tự động 65% dư)</div>
                <div style={{ fontSize: "18px", fontWeight: 700, color: "#3b82f6", marginTop: "2px" }}>{tp2}%</div>
                <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>Ăn tiếp con sóng trung bình</div>
              </div>

              <div style={{ padding: "10px", background: "rgba(139, 92, 246, 0.1)", borderRadius: "6px", border: "1px solid rgba(139, 92, 246, 0.3)" }}>
                <div style={{ fontSize: "11px", color: "var(--text-secondary)", fontWeight: 600 }}>MỨC TP 3 (Tự động 35% dư)</div>
                <div style={{ fontSize: "18px", fontWeight: 700, color: "#8b5cf6", marginTop: "2px" }}>{tp3}%</div>
                <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>Giữ tỷ trọng nhỏ săn sóng lớn</div>
              </div>
            </div>

            <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "12px", fontStyle: "italic" }}>
              💡 <strong>Lý do tối ưu:</strong> Trên thị trường Crypto, TP3 có xác suất chạm thấp hơn rất nhiều so với TP1 và TP2. 
              Do đó, phần khối lượng còn lại ({remainder}%) sẽ được tự động dồn ưu tiên 65% cho TP2 ({tp2}%) và chỉ 35% cho TP3 ({tp3}%) nhằm tối đa hóa dòng tiền thực nhận.
            </div>
          </div>

          {/* Breakeven Risk-Free Checkbox */}
          <div style={{ marginTop: "16px", padding: "16px", background: "rgba(16, 185, 129, 0.08)", borderRadius: "8px", border: "1px solid rgba(16, 185, 129, 0.25)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <ShieldCheck size={18} style={{ color: "#10b981" }} />
                  <span style={{ fontWeight: 600, color: "#fff" }}>Tự Động Dời Stop Loss Về Entry Sau Khi Cắn TP1 (Kèo Bất Tử)</span>
                </div>
                <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px" }}>
                  Khi nến chạm TP1 và chốt {tp1}% khối lượng, Bot lập tức dời Stop Loss về mức giá hòa vốn Entry (kèm 0.1% bù phí sàn Binance). 
                  Kể từ giây phút này, vị thế trở thành "kèo không thể thua" – bảo toàn trọn vẹn tiền lãi đã đút túi.
                </div>
              </div>
              <input
                type="checkbox"
                checked={settings.breakeven_after_tp1 ?? true}
                onChange={(e) => setSettings({ ...settings, breakeven_after_tp1: e.target.checked })}
                style={{ width: "22px", height: "22px", cursor: "pointer", accentColor: "#10b981" }}
              />
            </div>
          </div>

          {/* Portfolio Basket Trailing & Daily Target Guard */}
          <div style={{ marginTop: "20px", padding: "20px", background: "linear-gradient(135deg, rgba(16, 185, 129, 0.05) 0%, rgba(59, 130, 246, 0.05) 100%)", borderRadius: "10px", border: "1px solid rgba(16, 185, 129, 0.25)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "16px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <div style={{ width: "36px", height: "36px", borderRadius: "8px", background: "rgba(16, 185, 129, 0.15)", display: "flex", alignItems: "center", justifyContent: "center", border: "1px solid rgba(16, 185, 129, 0.3)" }}>
                  <ShieldCheck size={20} style={{ color: "#10b981" }} />
                </div>
                <div>
                  <h4 style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "#fff", display: "flex", alignItems: "center", gap: "8px" }}>
                    Giáp Khóa Lãi Danh Mục & Chỉ Tiêu Lãi Ngày
                    <span style={{ fontSize: "10px", padding: "2px 8px", background: "rgba(16, 185, 129, 0.2)", color: "#10b981", borderRadius: "12px", border: "1px solid rgba(16, 185, 129, 0.4)", fontWeight: 600 }}>
                      TỰ ĐỘNG BẢO TOÀN LỢI NHUẬN
                    </span>
                  </h4>
                  <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "2px" }}>
                    Tự động chốt lời bảo vệ toàn bộ danh mục khi đạt chỉ tiêu ngày hoặc khi lãi rổ chạm đỉnh rồi hồi lui. Tuyệt đối không để vị thế từ lãi hóa lỗ!
                  </div>
                </div>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
              {/* Daily Target Section */}
              <div style={{ padding: "16px", background: "rgba(0,0,0,0.25)", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.08)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                  <div>
                    <div style={{ fontWeight: 600, color: "#fff", fontSize: "13px" }}>🎯 Khóa Lãi Theo Chỉ Tiêu Ngày</div>
                    <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Đạt tổng lãi trong ngày là tự động chốt két</div>
                  </div>
                  <input
                    type="checkbox"
                    checked={settings.daily_profit_target_enabled ?? true}
                    onChange={(e) => setSettings({ ...settings, daily_profit_target_enabled: e.target.checked })}
                    style={{ width: "20px", height: "20px", cursor: "pointer", accentColor: "#10b981" }}
                  />
                </div>

                <div style={{ opacity: (settings.daily_profit_target_enabled ?? true) ? 1 : 0.4, transition: "opacity 0.2s" }}>
                  <label style={{ fontSize: "12px", color: "var(--text-secondary)", display: "block", marginBottom: "6px" }}>
                    Chỉ tiêu lãi ròng mục tiêu mỗi ngày (USDT):
                  </label>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <input
                      type="number"
                      step="0.5"
                      min="1"
                      max="1000"
                      className="form-input"
                      style={{ width: "120px", fontWeight: 700, color: "#10b981" }}
                      value={settings.daily_profit_target_usdt ?? 8.0}
                      disabled={!(settings.daily_profit_target_enabled ?? true)}
                      onChange={(e) => setSettings({ ...settings, daily_profit_target_usdt: parseFloat(e.target.value) || 8.0 })}
                    />
                    <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>USDT / ngày (Khuyên dùng: 8 - 15 USDT với vốn $300)</span>
                  </div>
                </div>
              </div>

              {/* Basket Trailing Profit Section */}
              <div style={{ padding: "16px", background: "rgba(0,0,0,0.25)", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.08)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                  <div>
                    <div style={{ fontWeight: 600, color: "#fff", fontSize: "13px" }}>🛡️ Trailing Stop Khóa Lãi Rổ Vị Thế</div>
                    <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Bám đuôi đỉnh lãi danh mục thả nổi</div>
                  </div>
                  <input
                    type="checkbox"
                    checked={settings.basket_trailing_enabled ?? true}
                    onChange={(e) => setSettings({ ...settings, basket_trailing_enabled: e.target.checked })}
                    style={{ width: "20px", height: "20px", cursor: "pointer", accentColor: "#10b981" }}
                  />
                </div>

                <div style={{ opacity: (settings.basket_trailing_enabled ?? true) ? 1 : 0.4, transition: "opacity 0.2s", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                  <div>
                    <label style={{ fontSize: "11px", color: "var(--text-secondary)", display: "block", marginBottom: "4px" }}>
                      Ngưỡng kích hoạt (USDT):
                    </label>
                    <input
                      type="number"
                      step="0.5"
                      min="1"
                      className="form-input"
                      style={{ width: "100%", fontWeight: 700, color: "#3b82f6" }}
                      value={settings.basket_trailing_trigger_usdt ?? 8.0}
                      disabled={!(settings.basket_trailing_enabled ?? true)}
                      onChange={(e) => setSettings({ ...settings, basket_trailing_trigger_usdt: parseFloat(e.target.value) || 8.0 })}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: "11px", color: "var(--text-secondary)", display: "block", marginBottom: "4px" }}>
                      % Hồi lui từ đỉnh chốt:
                    </label>
                    <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                      <input
                        type="number"
                        step="1"
                        min="5"
                        max="90"
                        className="form-input"
                        style={{ width: "100%", fontWeight: 700, color: "#f59e0b" }}
                        value={settings.basket_trailing_pullback_pct ?? 25.0}
                        disabled={!(settings.basket_trailing_enabled ?? true)}
                        onChange={(e) => setSettings({ ...settings, basket_trailing_pullback_pct: parseFloat(e.target.value) || 25.0 })}
                      />
                      <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>%</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Presets and Realtime Simulation */}
            {(() => {
              const trigVal = Number(settings.basket_trailing_trigger_usdt) || 8.0;
              const pbVal = Number(settings.basket_trailing_pullback_pct) || 25.0;
              const dailyVal = Number(settings.daily_profit_target_usdt) || 8.0;
              const minLock = (trigVal * (1 - pbVal / 100)).toFixed(2);
              const pumpPeak = Math.max(20.0, Math.round(trigVal * 1.6 * 2) / 2);
              const pumpLock = (pumpPeak * (1 - pbVal / 100)).toFixed(2);
              const isTrailingOn = settings.basket_trailing_enabled ?? true;
              const isDailyOn = settings.daily_profit_target_enabled ?? true;

              return (
                <div style={{ marginTop: "16px" }}>
                  {/* Presets buttons */}
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", marginBottom: "12px" }}>
                    <span style={{ fontSize: "11px", color: "var(--text-muted)", fontWeight: 600 }}>Chọn nhanh mẫu chuẩn:</span>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      style={{ fontSize: "11px", padding: "4px 10px", borderColor: "rgba(16, 185, 129, 0.4)", color: "#10b981" }}
                      onClick={() => setSettings({
                        ...settings,
                        daily_profit_target_enabled: true,
                        daily_profit_target_usdt: 10.0,
                        basket_trailing_enabled: true,
                        basket_trailing_trigger_usdt: 10.0,
                        basket_trailing_pullback_pct: 15.0,
                      })}
                    >
                      🛡️ Mẫu An Toàn (10$ Trailing / 15% Hồi lui / 10$ Ngày)
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      style={{ fontSize: "11px", padding: "4px 10px", borderColor: "rgba(59, 130, 246, 0.4)", color: "#38bdf8" }}
                      onClick={() => setSettings({
                        ...settings,
                        daily_profit_target_enabled: true,
                        daily_profit_target_usdt: 15.0,
                        basket_trailing_enabled: true,
                        basket_trailing_trigger_usdt: 13.0,
                        basket_trailing_pullback_pct: 15.0,
                      })}
                    >
                      ⚖️ Mẫu Cân Bằng (13$ Trailing / 15% Hồi lui / 15$ Ngày)
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      style={{ fontSize: "11px", padding: "4px 10px", borderColor: "rgba(245, 158, 11, 0.4)", color: "#f59e0b" }}
                      onClick={() => setSettings({
                        ...settings,
                        daily_profit_target_enabled: true,
                        daily_profit_target_usdt: 25.0,
                        basket_trailing_enabled: true,
                        basket_trailing_trigger_usdt: 20.0,
                        basket_trailing_pullback_pct: 20.0,
                      })}
                    >
                      🚀 Mẫu Sóng Lớn (20$ Trailing / 20% Hồi lui / 25$ Ngày)
                    </button>
                  </div>

                  {/* Visual Simulation Card */}
                  <div style={{ background: "rgba(0,0,0,0.35)", borderRadius: "8px", padding: "14px 16px", border: "1px solid rgba(16, 185, 129, 0.2)" }}>
                    <div style={{ fontSize: "12px", fontWeight: 700, color: "#fff", marginBottom: "8px", display: "flex", alignItems: "center", gap: "6px" }}>
                      <span>📊 BẢNG DIỄN GIẢI THỰC TẾ THEO THIẾT LẬP CỦA BẠN:</span>
                      <span style={{ fontSize: "11px", fontWeight: 600, color: "#10b981" }}>(Tự động tính theo con số bạn vừa điền)</span>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", fontSize: "12px" }}>
                      {/* Left: Daily Target Explanation */}
                      <div style={{ background: "rgba(255,255,255,0.02)", borderRadius: "6px", padding: "10px 12px", border: "1px solid rgba(255,255,255,0.06)" }}>
                        <div style={{ fontWeight: 600, color: isDailyOn ? "#10b981" : "#94a3b8", display: "flex", justifyContent: "space-between" }}>
                          <span>🎯 Khóa Lãi Theo Ngày:</span>
                          <span>{isDailyOn ? `🟢 BẬT (${dailyVal.toFixed(1)}$ / ngày)` : "⚪ ĐANG TẮT"}</span>
                        </div>
                        <div style={{ color: "var(--text-secondary)", marginTop: "6px", lineHeight: "1.5" }}>
                          {isDailyOn ? (
                            <>
                              Khi tổng tiền lãi hôm nay <em>(Lãi đã chốt + Lãi các lệnh đang gồng)</em> đạt mốc <strong style={{ color: "#10b981" }}>+{dailyVal.toFixed(2)} USDT</strong>:
                              <br />
                              ➔ Bot lập tức <strong>gửi lệnh Market đóng sạch mọi vị thế</strong>, khóa chặt két sắt và hoàn thành xuất sắc chỉ tiêu ngày!
                            </>
                          ) : (
                            <>Chế độ này đang tắt. Bot sẽ để các lệnh chạy theo TP/SL cá nhân mà không tự đóng toàn bộ danh mục theo ngày.</>
                          )}
                        </div>
                      </div>

                      {/* Right: Trailing Stop Explanation */}
                      <div style={{ background: "rgba(255,255,255,0.02)", borderRadius: "6px", padding: "10px 12px", border: "1px solid rgba(255,255,255,0.06)" }}>
                        <div style={{ fontWeight: 600, color: isTrailingOn ? "#38bdf8" : "#94a3b8", display: "flex", justifyContent: "space-between" }}>
                          <span>🛡️ Trailing Stop Khóa Lãi Rổ:</span>
                          <span>{isTrailingOn ? `🟢 BẬT (≥ ${trigVal.toFixed(1)}$ | Hồi ${pbVal}%)` : "⚪ ĐANG TẮT"}</span>
                        </div>
                        <div style={{ color: "var(--text-secondary)", marginTop: "6px", lineHeight: "1.5" }}>
                          {isTrailingOn ? (
                            <>
                              • <strong>Mốc 1 (Bật Giáp):</strong> Khi rổ lệnh lãi chạm <strong style={{ color: "#38bdf8" }}>+{trigVal.toFixed(2)}$</strong> ➔ Kích hoạt radar bám đỉnh. Mức bảo vệ tối thiểu: <strong style={{ color: "#10b981" }}>+{minLock}$</strong> <em>(giữ lại {(100 - pbVal).toFixed(0)}% lãi)</em>.
                              <br />
                              • <strong>Mốc 2 (Lãi bay tiếp):</strong> Nếu lãi vọt lên <strong style={{ color: "#38bdf8" }}>+{pumpPeak.toFixed(2)}$</strong> ➔ Mốc tự chốt nâng theo lên <strong style={{ color: "#10b981" }}>+{pumpLock}$</strong>!
                              <br />
                              • <strong>Mốc 3 (Tự chốt khi đảo chiều):</strong> Khi lãi từ đỉnh tụt <strong style={{ color: "#ef4444" }}>{pbVal}%</strong> ➔ Bot <strong>đóng toàn bộ vị thế ngay lập tức</strong>, không để bị âm vốn ngược!
                            </>
                          ) : (
                            <>Chế độ này đang tắt. Vị thế sẽ chỉ phụ thuộc vào TP/SL cá nhân từng lệnh.</>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })()}
          </div>
        </div>
      </div>

      {/* Confirmation Modal for Enabling Live Trading */}
      <ConfirmModal
        isOpen={showLiveConfirmModal}
        title="CẢNH BÁO NGUY HIỂM: KÍCH HOẠT GIAO DỊCH LIVE"
        message="BẬT TÍNH NĂNG NÀY SẼ CHO PHÉP HỆ THỐNG GỬI LỆNH MUA/BÁN VỚI TIỀN THẬT LÊN SÀN BINANCE FUTURES KHI NHẬN TÍN HIỆU TỪ TELEGRAM.

Bạn phải hoàn toàn chịu trách nhiệm về rủi ro tài chính, biến động thị trường và các lỗi phát sinh từ bên thứ ba."
        confirmText="TÔI ĐỒNG Ý BẬT LIVE"
        requiredKeyword="LIVE TRADING"
        isDanger={true}
        onConfirm={handleConfirmLive}
        onCancel={() => setShowLiveConfirmModal(false)}
      />
    </div>
  );
};
