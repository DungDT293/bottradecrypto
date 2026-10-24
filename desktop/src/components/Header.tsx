import React, { useState, useEffect } from "react";
import { RefreshCw, Shield, AlertTriangle, Flame, PauseCircle, PlayCircle } from "lucide-react";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";
import { ConfirmModal } from "./ConfirmModal";

export const Header: React.FC = () => {
  const {
    snapshot,
    refreshSnapshot,
    loading,
    connected,
    httpConnected,
    wsConnected,
    isStale,
    lastSyncTime,
    addToast,
  } = useApp();
  const [showExitModal, setShowExitModal] = useState(false);
  const [togglingEntry, setTogglingEntry] = useState(false);
  const [togglingFerrari, setTogglingFerrari] = useState(false);
  const [regime, setRegime] = useState<{
    status: string;
    btc_price: number;
    btc_4h_ema20: number;
    btc_4h_ema50: number;
    btc_1h_rsi: number;
    reason: string;
  } | null>(null);
  const [queueCount, setQueueCount] = useState<number>(0);

  const mode = snapshot?.mode || "READ_ONLY";
  const isLiveTrading = snapshot?.live_trading_enabled ?? false;
  const isEntryEnabled = snapshot?.entry_enabled ?? true;
  const isFerrariMode = snapshot?.ferrari_mode_enabled ?? false;
  const positionsCount = snapshot?.positions?.length || 0;

  useEffect(() => {
    let mounted = true;
    const fetchRegimeAndQueue = async () => {
      try {
        const [regimeRes, queueRes] = await Promise.allSettled([
          api.getMarketRegime(),
          api.getSmartQueue(),
        ]);
        if (!mounted) return;
        if (regimeRes.status === "fulfilled") {
          setRegime(regimeRes.value);
        }
        if (queueRes.status === "fulfilled") {
          setQueueCount(queueRes.value.count || 0);
        }
      } catch {}
    };

    fetchRegimeAndQueue();
    const timer = setInterval(fetchRegimeAndQueue, 15000);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    // Listen for Tauri tray events if in desktop environment
    let unlistenExit: (() => void) | undefined;
    let unlistenToggle: (() => void) | undefined;

    const setupTauriListeners = async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        unlistenExit = await listen("request_exit_confirmation", () => {
          setShowExitModal(true);
        });
        unlistenToggle = await listen("tray_toggle_entry", async () => {
          try {
            await api.toggleEntry(!isEntryEnabled);
            await refreshSnapshot();
          } catch {
            // Ignored
          }
        });
      } catch {
        // Not in Tauri or event not supported
      }
    };

    setupTauriListeners();

    return () => {
      if (unlistenExit) unlistenExit();
      if (unlistenToggle) unlistenToggle();
    };
  }, [isEntryEnabled, refreshSnapshot]);

  const handleToggleEntry = async () => {
    if (!connected) return;
    setTogglingEntry(true);
    try {
      const res = await api.toggleEntry(!isEntryEnabled);
      addToast(
        res.entry_enabled ? "Đã bật tiếp nhận tín hiệu." : "Đã tạm dừng nhận lệnh mới.",
        res.entry_enabled ? "success" : "warning"
      );
      await refreshSnapshot();
    } catch (err: any) {
      addToast("Lỗi cập nhật trạng thái nhận lệnh.", "error");
    } finally {
      setTogglingEntry(false);
    }
  };

  const handleToggleFerrari = async () => {
    if (!connected) return;
    setTogglingFerrari(true);
    try {
      const res = await api.toggleFerrariMode(!isFerrariMode);
      addToast(
        res.ferrari_mode_enabled
          ? "🏎️ ĐÃ BẬT FERRARI MODE (Đòn bẩy x35-40, Khớp mọi kèo không chặn)!"
          : "🏎️ Đã tắt Ferrari Mode (Trở về mức đòn bẩy tiêu chuẩn).",
        res.ferrari_mode_enabled ? "success" : "info"
      );
      await refreshSnapshot();
    } catch (err: any) {
      addToast("Lỗi cập nhật Ferrari Mode.", "error");
    } finally {
      setTogglingFerrari(false);
    }
  };

  const handleConfirmExit = async () => {
    setShowExitModal(false);
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("exit_application");
    } catch {
      await api.exitApplication();
    }
  };

  const handleHideToTray = async () => {
    setShowExitModal(false);
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("hide_window");
    } catch {}
  };

  const renderModeBadge = () => {
    return (
      <span className="badge badge-live">
        <Flame size={14} /> LIVE (TIỀN THẬT)
      </span>
    );
  };

  return (
    <header className="top-header">
      <div className="header-left">
        {renderModeBadge()}
        <span className={`badge ${isLiveTrading ? "badge-live-on" : "badge-live-off"}`}>
          Giao dịch Live: {isLiveTrading ? "ĐANG BẬT" : "ĐÃ TẮT"}
        </span>

        {/* Entry Enabled / Paused Toggle Pill */}
        <button
          className="btn btn-secondary btn-sm"
          onClick={handleToggleEntry}
          disabled={togglingEntry || !connected}
          title={
            !connected
              ? "Backend mất kết nối - Trạng thái nhận lệnh chưa sẵn sàng"
              : mode === "READ_ONLY"
              ? "Chế độ READ_ONLY: Chỉ quan sát và phân tích tín hiệu, không đặt lệnh thật lên sàn"
              : isEntryEnabled
              ? "Bấm để tạm dừng tiếp nhận tín hiệu vào lệnh mới"
              : "Bấm để tiếp tục nhận tín hiệu vào lệnh mới"
          }
          style={{
            borderColor: !connected
              ? "rgba(148, 163, 184, 0.4)"
              : isEntryEnabled
              ? "rgba(16, 185, 129, 0.4)"
              : "rgba(245, 158, 11, 0.4)",
            backgroundColor: !connected
              ? "rgba(148, 163, 184, 0.1)"
              : isEntryEnabled
              ? "rgba(16, 185, 129, 0.1)"
              : "rgba(245, 158, 11, 0.1)",
          }}
        >
          {!connected ? (
            <>
              <AlertTriangle size={14} className="text-muted" />
              <span className="text-muted">Entry: CHƯA SẴN SÀNG</span>
            </>
          ) : mode === "READ_ONLY" ? (
            <>
              <Shield size={14} className="text-success" />
              <span className="text-success">
                Quan sát tín hiệu: {isEntryEnabled ? "BẬT" : "TẮT"} (READ_ONLY)
              </span>
            </>
          ) : isEntryEnabled ? (
            <>
              <PlayCircle size={14} className="text-success" />
              <span className="text-success">Entry: ĐANG NHẬN</span>
            </>
          ) : (
            <>
              <PauseCircle size={14} className="text-warning" />
              <span className="text-warning">Entry: TẠM DỪNG</span>
            </>
          )}
        </button>

        {/* Ferrari Mode (No Risk, No Ferrari) Quick Toggle Pill */}
        <button
          className="btn btn-secondary btn-sm"
          onClick={handleToggleFerrari}
          disabled={togglingFerrari || !connected}
          title={
            isFerrariMode
              ? "FERRARI MODE ĐANG BẬT: Đòn bẩy x35-40, mở khóa 100% kèo không chặn, TP1 35% + Breakeven tức thì."
              : "Bấm để kích hoạt FERRARI MODE: Đòn bẩy x35-40, tối đa hóa lợi nhuận, vào mọi kèo Telegram."
          }
          style={{
            borderColor: isFerrariMode ? "#ef4444" : "rgba(239, 68, 68, 0.4)",
            backgroundColor: isFerrariMode ? "rgba(239, 68, 68, 0.25)" : "rgba(239, 68, 68, 0.08)",
            boxShadow: isFerrariMode ? "0 0 12px rgba(239, 68, 68, 0.45)" : "none",
            color: isFerrariMode ? "#ff4d4d" : "var(--text-secondary)",
            fontWeight: 700,
            display: "flex",
            alignItems: "center",
            gap: "5px",
            transition: "all 0.3s ease",
          }}
        >
          <span style={{ fontSize: "14px" }}>🏎️</span>
          <span>{isFerrariMode ? "FERRARI: ON (x35-40)" : "FERRARI: OFF"}</span>
        </button>

        {/* BTC Market Regime Shield Pill (Trụ Cột 1) */}
        {regime && (
          <div
            className="badge"
            title={`${regime.reason}\nBTC: $${regime.btc_price?.toLocaleString()} | 4H EMA20: $${regime.btc_4h_ema20?.toLocaleString()} | 4H EMA50: $${regime.btc_4h_ema50?.toLocaleString()} | 1H RSI: ${regime.btc_1h_rsi}`}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "5px",
              cursor: "help",
              borderColor:
                regime.status.includes("BULLISH")
                  ? "rgba(16, 185, 129, 0.5)"
                  : regime.status === "BEARISH_PANIC"
                  ? "rgba(239, 68, 68, 0.5)"
                  : "rgba(245, 158, 11, 0.5)",
              backgroundColor:
                regime.status.includes("BULLISH")
                  ? "rgba(16, 185, 129, 0.12)"
                  : regime.status === "BEARISH_PANIC"
                  ? "rgba(239, 68, 68, 0.15)"
                  : "rgba(245, 158, 11, 0.12)",
              color:
                regime.status.includes("BULLISH")
                  ? "#10b981"
                  : regime.status === "BEARISH_PANIC"
                  ? "#ff4d4d"
                  : "#f59e0b",
              fontWeight: 600,
              fontSize: "12px",
            }}
          >
            <span>{regime.status.includes("BULLISH") ? "🟢" : regime.status === "BEARISH_PANIC" ? "🔴" : "🟡"}</span>
            <span>
              BTC: {regime.status} {regime.btc_price ? `($${Math.round(regime.btc_price).toLocaleString()})` : ""}
            </span>
          </div>
        )}

        {/* Smart Queue Priority Pill (Trụ Cột 6) */}
        <div
          className="badge"
          title={
            queueCount > 0
              ? `Hàng Đợi Thông Minh: Có ${queueCount} tín hiệu Tier 1 đang chờ giải phóng slot rủi ro để tự động khớp lệnh.`
              : "Hàng Đợi Thông Minh: 0 tín hiệu chờ (Sẵn sàng nhận kèo mới)"
          }
          style={{
            display: "flex",
            alignItems: "center",
            gap: "5px",
            cursor: "help",
            borderColor: queueCount > 0 ? "rgba(168, 85, 247, 0.6)" : "rgba(255, 255, 255, 0.1)",
            backgroundColor: queueCount > 0 ? "rgba(168, 85, 247, 0.2)" : "rgba(255, 255, 255, 0.04)",
            color: queueCount > 0 ? "#c084fc" : "var(--text-muted)",
            fontWeight: 600,
            fontSize: "12px",
          }}
        >
          <span>⏳</span>
          <span>Queue: {queueCount} {queueCount > 0 ? "chờ slot" : ""}</span>
        </div>
      </div>

      <div className="header-right">
        {/* Backend health pill with fine-grained HTTP/WS separation */}
        <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "var(--text-secondary)" }}>
          <span
            style={{
              width: "8px",
              height: "8px",
              borderRadius: "50%",
              backgroundColor: !httpConnected
                ? "var(--color-danger)"
                : wsConnected
                ? "var(--color-success)"
                : "var(--color-warning)",
            }}
          />
          <span>
            {!httpConnected
              ? "Mất kết nối Backend"
              : wsConnected
              ? "Backend Online (Realtime)"
              : "Backend Online (Đang nối lại realtime)"}
          </span>
          {isStale && (
            <span
              style={{
                fontSize: "10px",
                color: "var(--color-warning)",
                background: "rgba(245, 158, 11, 0.15)",
                padding: "2px 5px",
                borderRadius: "3px",
              }}
              title="Dữ liệu từ lần đồng bộ trước"
            >
              (STALE lúc {lastSyncTime})
            </span>
          )}
        </div>

        {/* Telegram pill */}
        <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
          TG: <strong style={{ color: snapshot?.telemetry ? "var(--color-success)" : "var(--text-muted)" }}>
            {snapshot?.telemetry ? "Đang nhận" : "Chưa kết nối"}
          </strong>
        </div>

        {/* Binance pill */}
        <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
          Binance: <strong style={{ color: (snapshot?.account?.connected || snapshot?.account?.is_connected) ? "var(--color-success)" : "var(--text-muted)" }}>
            {(snapshot?.account?.connected || snapshot?.account?.is_connected) ? "Đã liên kết" : "Chưa kết nối"}
          </strong>
        </div>

        {/* Refresh button */}
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => refreshSnapshot()}
          disabled={loading}
          title="Làm mới dữ liệu từ backend"
        >
          <RefreshCw size={13} className={loading ? "spin" : ""} />
          <span>Làm mới</span>
        </button>
      </div>

      {/* Exit Confirmation Modal */}
      <ConfirmModal
        isOpen={showExitModal}
        title="XÁC NHẬN THOÁT HOÀN TOÀN ỨNG DỤNG"
        message={
          positionsCount > 0
            ? `CẢNH BÁO NGUY HIỂM: Hiện đang có ${positionsCount} vị thế bot đang mở trên sàn!

Hệ thống TUYỆT ĐỐI KHÔNG tự động đóng vị thế khi thoát. Bạn sẽ phải tự quản lý hoặc cài SL/TP trực tiếp trên sàn Binance sau khi tắt bot.

Bạn có chắc chắn muốn tắt hoàn toàn ứng dụng và tiến trình backend?`
            : "Hệ thống không có vị thế nào đang mở. Bạn có chắc chắn muốn thoát ứng dụng và dừng tiến trình backend?"
        }
        confirmText="Thoát Ứng Dụng"
        cancelText="Ở lại (Ẩn vào Tray)"
        isDanger={positionsCount > 0}
        onConfirm={handleConfirmExit}
        onCancel={handleHideToTray}
      />
    </header>
  );
};
