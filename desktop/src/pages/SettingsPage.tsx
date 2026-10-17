import React, { useState, useEffect } from "react";
import { Save, ShieldCheck, Percent } from "lucide-react";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";
import { ConfirmModal } from "../components/ConfirmModal";
import type { AppSettings } from "../types/api";

export const SettingsPage: React.FC = () => {
  const { addToast, refreshSnapshot } = useApp();
  const [settings, setSettings] = useState<AppSettings>({
    mode: "TESTNET",
    live_trading_enabled: false,
    risk_per_signal_pct: 1.5,
    max_daily_loss_pct: 5.0,
    max_leverage: 50,
    margin_mode: "ISOLATED",
    entry_range_policy: "BEST_PRICE",
    multi_tp_default_weight_mode: "CUSTOM_TP1_RATIO",
    tp1_target_weight_pct: 60,
    breakeven_after_tp1: true,
    sl_buffer_pct: 1.0,
  });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showLiveConfirmModal, setShowLiveConfirmModal] = useState(false);
  const [autostartEnabled, setAutostartEnabled] = useState(false);

  const fetchSettings = async () => {
    setLoading(true);
    try {
      const data = await api.getSettings();
      setSettings(data);
    } catch (err: any) {
      addToast("Lỗi tải thông tin cài đặt.", "error");
    } finally {
      setLoading(false);
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
  const tp1 = Math.min(90, Math.max(10, settings.tp1_target_weight_pct ?? 60));
  const remainder = Math.max(0, 100 - tp1);
  const tp2 = Math.round(remainder * 0.65 * 10) / 10;
  const tp3 = Math.round((remainder - tp2) * 10) / 10;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
        <div>
          <h2 style={{ fontSize: "20px", fontWeight: 700, color: "#fff" }}>Cài Đặt Hệ Thống</h2>
          <p style={{ color: "var(--text-secondary)", fontSize: "13px" }}>
            Quản trị rủi ro, chính sách đòn bẩy, chế độ thực thi lệnh và kiểm soát an toàn.
          </p>
        </div>

        <button className="btn btn-primary" onClick={handleSave} disabled={saving || loading}>
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
                🛡️ Tự động nới khoảng cách SL ra thêm 1% so với giá Admin đưa để tránh bị râu nến Binance liếm cắn SL (Khối lượng vào lệnh sẽ được tự động co lại để giữ nguyên mức rủi ro tiền tệ).
              </div>
            </div>
          </div>
        </div>

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
              <label className="form-label">Quy tắc chọn Entry khi gặp vùng giá (Range Entry)</label>
              <select
                className="form-input"
                value={settings.entry_range_policy}
                onChange={(e) => setSettings({ ...settings, entry_range_policy: e.target.value })}
              >
                <option value="BEST_PRICE">BEST_PRICE (Ưu tiên giá khớp tối ưu nhất cho vị thế)</option>
                <option value="MID">MID (Giá trung bình giữa Entry 1 và Entry 2)</option>
                <option value="MIN">MIN (Ưu tiên giá thấp nhất)</option>
                <option value="MAX">MAX (Ưu tiên giá cao nhất)</option>
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">Phân bổ tỷ trọng chốt lời nhiều TP (Multi-TP Distribution)</label>
              <select
                className="form-input"
                value={settings.multi_tp_default_weight_mode}
                onChange={(e) => setSettings({ ...settings, multi_tp_default_weight_mode: e.target.value })}
              >
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
                  Kéo chỉnh tỷ lệ chốt lời tại TP1. Hệ thống tự động phân bổ thông minh phần còn lại cho TP2 & TP3.
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
                  value={settings.tp1_target_weight_pct ?? 60}
                  onChange={(e) => setSettings({ ...settings, tp1_target_weight_pct: parseFloat(e.target.value) || 60 })}
                />
                <span style={{ fontWeight: 700, color: "#10b981" }}>%</span>
              </div>
            </div>

            <input
              type="range"
              min="10"
              max="90"
              step="5"
              value={settings.tp1_target_weight_pct ?? 60}
              onChange={(e) => setSettings({ ...settings, tp1_target_weight_pct: parseInt(e.target.value) || 60 })}
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
