import React, { useState, useEffect } from "react";
import { RefreshCw } from "lucide-react";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";

export const StatsPage: React.FC = () => {
  const { addToast, snapshot } = useApp();
  const [telemetry, setTelemetry] = useState<any | null>(null);
  const [daysBack, setDaysBack] = useState<number>(0);
  const [pnlSummary, setPnlSummary] = useState<any | null>(null);
  const [syncing, setSyncing] = useState(false);

  const fetchStats = async () => {
    try {
      const data = await api.getTelemetry();
      setTelemetry(data);
      const pnl = await api.getPnL(daysBack);
      setPnlSummary(pnl);
    } catch {
      // Ignored
    }
  };

  const handleSyncFromBinance = async () => {
    setSyncing(true);
    try {
      const res = await api.syncPnL();
      if (res.success) {
        addToast(res.message || "Đã đồng bộ PnL từ Binance thành công!", "success");
        await fetchStats();
      } else {
        addToast(res.message || "Đồng bộ thất bại.", "error");
      }
    } catch (err: any) {
      addToast(err?.message || "Lỗi khi gọi đồng bộ Binance.", "error");
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    fetchStats();
  }, [daysBack]);

  const currentTelemetry = telemetry || snapshot?.telemetry;
  const currentPnl = pnlSummary;
  const benchmark = currentTelemetry?.benchmark_accuracy;

  return (
    <div>
      <div style={{ marginBottom: "20px" }}>
        <h2 style={{ fontSize: "20px", fontWeight: 700, color: "#fff" }}>Thống Kê & Phân Tích Hiệu Suất</h2>
        <p style={{ color: "var(--text-secondary)", fontSize: "13px" }}>
          Báo cáo minh bạch thông lượng tin nhắn Telegram, kiểm nghiệm benchmark và phân tích chi tiết PnL theo chuẩn kế toán sàn.
        </p>
      </div>

      {/* 1. Ingestion Telemetry Breakdown */}
      <h3 style={{ fontSize: "15px", color: "var(--text-secondary)", marginBottom: "12px" }}>
        1. Thông Lượng Xử Lý Tin Nhắn Telegram (Ingestion Telemetry)
      </h3>
      <div className="card-grid">
        <div className="card">
          <div className="card-title">Tin Đã Nhận (Received)</div>
          <div className="card-value">{currentTelemetry?.messages_received || 0}</div>
          <div className="card-subtitle">Từ các kênh trong Allowlist</div>
        </div>

        <div className="card">
          <div className="card-title">Tin Đã Xử Lý (Processed)</div>
          <div className="card-value">{currentTelemetry?.messages_processed || 0}</div>
          <div className="card-subtitle">Đã qua bộ chuẩn hóa Unicode NFKC</div>
        </div>

        <div className="card">
          <div className="card-title">Tín Hiệu Nhận Diện (Detected)</div>
          <div className="card-value" style={{ color: "var(--color-accent)" }}>
            {currentTelemetry?.signals_detected || 0}
          </div>
          <div className="card-subtitle">Có định dạng lệnh LONG / SHORT</div>
        </div>

        <div className="card">
          <div className="card-title">Tín Hiệu Hợp Lệ (Validated)</div>
          <div className="card-value text-success">{currentTelemetry?.signals_validated || 0}</div>
          <div className="card-subtitle">Vượt qua kiểm tra cú pháp & logic SL/TP</div>
        </div>

        <div className="card">
          <div className="card-title">Chờ Xem Xét (Needs Review)</div>
          <div className="card-value text-warning">{currentTelemetry?.signals_needs_review || 0}</div>
          <div className="card-subtitle">Trùng coin, nới SL hoặc cú pháp dị biệt</div>
        </div>

        <div className="card">
          <div className="card-title">Từ Chối / Lỗi Xử Lý</div>
          <div className="card-value text-muted">{currentTelemetry?.rejected_signals || 0}</div>
          <div className="card-subtitle">Thiếu SL, vi phạm rủi ro hoặc spam</div>
        </div>
      </div>

      {/* 2. Benchmark Accuracy Panel */}
      <div
        className="card"
        style={{
          marginBottom: "24px",
          background: "rgba(59, 130, 246, 0.08)",
          borderColor: "rgba(59, 130, 246, 0.3)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ fontWeight: 700, color: "#fff", fontSize: "15px" }}>
              Độ Chính Xác Đối Chiếu Benchmark (Ground-Truth Validated)
            </div>
            <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px" }}>
              {benchmark?.description || "Kiểm nghiệm trên tập dữ liệu chuẩn 9 kịch bản tín hiệu nguyên văn (Fixtures)"}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <span style={{ fontSize: "24px", fontWeight: 700, color: "var(--color-success)" }} className="mono">
              {benchmark ? `${benchmark.accuracy_pct}%` : "Chưa có dữ liệu"}
            </span>
            <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>
              {benchmark ? `${benchmark.passed_cases}/${benchmark.test_cases} tests PASS` : "Chưa chạy benchmark"}
            </div>
          </div>
        </div>
      </div>

      {/* 3. PnL Breakdown Section */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px", marginTop: "16px", flexWrap: "wrap", gap: "8px" }}>
        <h3 style={{ fontSize: "15px", color: "var(--text-secondary)" }}>
          2. Báo Cáo Chi Tiết Lãi/Lỗ (PnL Breakdown)
        </h3>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <select
            className="form-input"
            style={{ width: "auto" }}
            value={daysBack}
            onChange={(e) => setDaysBack(parseInt(e.target.value))}
          >
            <option value={0}>Hôm nay (00:00 - Hiện tại)</option>
            <option value={6}>7 ngày qua</option>
            <option value={29}>30 ngày qua</option>
          </select>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={handleSyncFromBinance}
            disabled={syncing}
            title="Đồng bộ dữ liệu Realized PnL và phí trực tiếp từ Binance"
          >
            <RefreshCw size={13} className={syncing ? "spin" : ""} />
            <span>{syncing ? "Đang đồng bộ..." : "Đồng bộ Binance"}</span>
          </button>
        </div>
      </div>

      {/* Trade Win/Loss Summary Bar */}
      {currentPnl?.has_data && (
        <div
          style={{
            display: "flex",
            gap: "16px",
            background: "var(--bg-secondary)",
            padding: "10px 16px",
            borderRadius: "8px",
            marginBottom: "12px",
            fontSize: "13px",
            alignItems: "center",
            flexWrap: "wrap",
            border: "1px solid var(--border-color)",
          }}
        >
          <span>
            Tổng lệnh đã đóng: <strong className="mono" style={{ color: "#fff" }}>{currentPnl.total_closed_trades || (currentPnl.win_count + currentPnl.loss_count)}</strong>
          </span>
          <span>
            Lệnh thắng: <strong className="mono text-success">{currentPnl.win_count || 0}</strong>
          </span>
          <span>
            Lệnh thua: <strong className="mono text-danger">{currentPnl.loss_count || 0}</strong>
          </span>
          <span>
            Tỷ lệ thắng (Win Rate): <strong className="mono" style={{ color: "var(--color-accent)", fontWeight: 700 }}>{currentPnl.win_rate_pct ?? 0}%</strong>
          </span>
        </div>
      )}

      <div className="card-grid">
        <div className="card">
          <div className="card-title">Realized PnL (Tổng Lãi/Lỗ Đã Đóng)</div>
          <div className="card-value mono">
            {currentPnl?.has_data && currentPnl?.realized_pnl != null ? (
              <span className={parseFloat(currentPnl.realized_pnl) >= 0 ? "text-success" : "text-danger"}>
                {parseFloat(currentPnl.realized_pnl) >= 0 ? `+${currentPnl.realized_pnl}` : currentPnl.realized_pnl} USDT
              </span>
            ) : (
              <span className="text-muted" style={{ fontSize: "16px" }}>Chưa có dữ liệu</span>
            )}
          </div>
          <div className="card-subtitle">Chưa trừ chi phí giao dịch</div>
        </div>

        <div className="card">
          <div className="card-title">Commission (Phí Hoa Hồng Sàn)</div>
          <div className="card-value mono text-warning">
            {currentPnl?.has_data && currentPnl?.commission != null ? (
              `-${currentPnl.commission} USDT`
            ) : (
              <span className="text-muted" style={{ fontSize: "16px" }}>Chưa có dữ liệu</span>
            )}
          </div>
          <div className="card-subtitle">Phí mở & đóng lệnh khớp thực tế</div>
        </div>

        <div className="card">
          <div className="card-title">Funding Fee (Phí Funding)</div>
          <div className="card-value mono">
            {currentPnl?.has_data && currentPnl?.funding_fee != null ? (
              `${currentPnl.funding_fee} USDT`
            ) : (
              <span className="text-muted" style={{ fontSize: "16px" }}>Chưa có dữ liệu</span>
            )}
          </div>
          <div className="card-subtitle">Phí tài trợ qua đêm từ sàn</div>
        </div>

        <div className="card">
          <div className="card-title">Net PnL (Lãi/Lỗ Ròng Thực Nhận)</div>
          <div className="card-value mono">
            {currentPnl?.has_data && currentPnl?.net_pnl != null ? (
              <span className={parseFloat(currentPnl.net_pnl) >= 0 ? "text-success" : "text-danger"}>
                {parseFloat(currentPnl.net_pnl) >= 0 ? `+${currentPnl.net_pnl}` : currentPnl.net_pnl} USDT
              </span>
            ) : (
              <span className="text-muted" style={{ fontSize: "16px" }}>Chưa có dữ liệu</span>
            )}
          </div>
          <div className="card-subtitle">Net = Realized - Commission + signed Funding</div>
        </div>
      </div>

      <div style={{ marginTop: "12px", fontSize: "12px", color: "var(--text-muted)", display: "flex", justifyContent: "space-between" }}>
        <span>
          Mức độ đầy đủ dữ liệu: <strong style={{ color: currentPnl?.data_completeness === "FULL" ? "var(--color-success)" : "var(--color-warning)" }}>{currentPnl?.data_completeness || "UNKNOWN"}</strong>
        </span>
        <span>
          Thời điểm đồng bộ gần nhất: <strong className="mono">{currentPnl?.last_sync_time || "—"}</strong>
        </span>
      </div>
    </div>
  );
};
