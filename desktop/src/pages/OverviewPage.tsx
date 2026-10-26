import React, { useState, useEffect } from "react";
import { DollarSign, ArrowUpRight, ArrowDownRight, Radio } from "lucide-react";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";
import { formatDateTime } from "../utils/date";

export const OverviewPage: React.FC = () => {
  const { snapshot, setTab } = useApp();
  const [capitalStage, setCapitalStage] = useState<{
    stage: number;
    label: string;
    current_equity: number;
    max_positions: number;
    recommended_risk_pct: number;
    max_total_risk_pct: number;
    target_equity: number;
    progress_pct: number;
    mission: string;
  } | null>(null);

  useEffect(() => {
    let mounted = true;
    api
      .getCapitalStage()
      .then((res) => {
        if (mounted) setCapitalStage(res);
      })
      .catch(() => {});
    return () => {
      mounted = false;
    };
  }, [snapshot]);

  const account = snapshot?.account;
  const pnlToday = snapshot?.pnl_today;
  const pnl7d = snapshot?.pnl_7d;
  const telemetry = snapshot?.telemetry;
  const positions = snapshot?.positions || [];
  const alerts = (snapshot?.alerts || []).slice(0, 5);

  const isConnected = Boolean(account?.connected || account?.is_connected);
  const marginBalance = account?.total_margin_balance ?? account?.equity ?? account?.wallet_balance;

  // INVARIANT: Do NOT display $0.00 if balance is disconnected or unknown
  const displayBalance =
    isConnected && marginBalance != null
      ? `$${parseFloat(String(marginBalance)).toFixed(2)} USDT`
      : "Chưa có dữ liệu";

  const todayPnlVal = parseFloat(pnlToday?.net_pnl ?? pnlToday?.realized_pnl ?? "0");
  const pnl7dVal = parseFloat(pnl7d?.net_pnl ?? pnl7d?.realized_pnl ?? "0");

  return (
    <div>
      <div style={{ marginBottom: "20px" }}>
        <h2 style={{ fontSize: "20px", fontWeight: 700, color: "#fff" }}>Tổng quan Hệ thống</h2>
        <p style={{ color: "var(--text-secondary)", fontSize: "13px" }}>
          Giám sát trạng thái hoạt động thực thi tín hiệu Telegram và tài khoản Binance Futures.
        </p>
      </div>

      {/* Trụ Cột 7: Compounding Capital Growth Banner */}
      {capitalStage && (
        <div
          className="card"
          style={{
            marginBottom: "20px",
            background: "linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.8) 100%)",
            border: "1px solid rgba(59, 130, 246, 0.25)",
            padding: "16px 20px",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px", flexWrap: "wrap", gap: "8px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <span style={{ fontSize: "18px" }}>📈</span>
              <span style={{ fontWeight: 700, fontSize: "14px", color: "#60a5fa" }}>
                {capitalStage.label}
              </span>
              <span
                className="badge"
                style={{ backgroundColor: "rgba(59, 130, 246, 0.15)", color: "#93c5fd", fontSize: "11px" }}
              >
                Trần: {snapshot?.max_active_signals || capitalStage.max_positions} vị thế {snapshot?.ferrari_mode_enabled ? "(Ferrari Mode)" : ""} | Rủi ro: {capitalStage.recommended_risk_pct}% NAV/lệnh
              </span>
            </div>
            <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
              Mục tiêu giai đoạn: <strong style={{ color: "#fff" }}>${capitalStage.target_equity} USDT</strong> (Đạt {capitalStage.progress_pct}%)
            </div>
          </div>

          {/* Progress bar */}
          <div
            style={{
              width: "100%",
              height: "6px",
              backgroundColor: "rgba(255, 255, 255, 0.08)",
              borderRadius: "3px",
              overflow: "hidden",
              marginBottom: "8px",
            }}
          >
            <div
              style={{
                width: `${capitalStage.progress_pct}%`,
                height: "100%",
                background: "linear-gradient(90deg, #3b82f6, #10b981)",
                transition: "width 0.5s ease",
              }}
            />
          </div>

          <div style={{ fontSize: "12px", color: "var(--text-muted)", display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: "6px" }}>
            <span>🎯 Chiến lược: {capitalStage.mission}</span>
            <span>Vốn hiện tại: <strong>{isConnected && marginBalance != null ? `$${parseFloat(String(marginBalance)).toFixed(2)} USDT` : `$${capitalStage.current_equity?.toFixed(2)} USDT`}</strong></span>
          </div>
        </div>
      )}

      {/* KPI Cards */}
      <div className="card-grid">
        <div className="card">
          <div className="card-title">
            <span>Số dư Ký quỹ (USDT)</span>
            <DollarSign size={16} className="text-muted" />
          </div>
          <div className="card-value">{displayBalance}</div>
          <div className="card-subtitle">
            {isConnected ? (
              <span className="text-success">● Đã đồng bộ tài khoản</span>
            ) : (
              <span className="text-warning">Chưa kết nối Binance</span>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-title">
            <span>PnL Hôm nay</span>
            {todayPnlVal >= 0 ? (
              <ArrowUpRight size={16} className="text-success" />
            ) : (
              <ArrowDownRight size={16} className="text-danger" />
            )}
          </div>
          <div className={`card-value ${todayPnlVal >= 0 ? "text-success" : "text-danger"}`}>
            {todayPnlVal >= 0 ? `+$${todayPnlVal.toFixed(2)}` : `-$${Math.abs(todayPnlVal).toFixed(2)}`}
          </div>
          <div className="card-subtitle">
            {(pnlToday?.total_closed_trades ?? 0) > 0 ? (
              <>Tỷ lệ thắng: <strong>{pnlToday?.win_rate_pct ?? 0}%</strong> ({pnlToday?.win_count ?? 0}/{pnlToday?.total_closed_trades ?? 0} lệnh)</>
            ) : (
              <span className="text-muted">Chưa có vị thế đóng hôm nay</span>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-title">
            <span>PnL 7 Ngày</span>
            {pnl7dVal >= 0 ? (
              <ArrowUpRight size={16} className="text-success" />
            ) : (
              <ArrowDownRight size={16} className="text-danger" />
            )}
          </div>
          <div className={`card-value ${pnl7dVal >= 0 ? "text-success" : "text-danger"}`}>
            {pnl7dVal >= 0 ? `+$${pnl7dVal.toFixed(2)}` : `-$${Math.abs(pnl7dVal).toFixed(2)}`}
          </div>
          <div className="card-subtitle">
            Tổng số lệnh: <strong>{pnl7d?.total_closed_trades ?? 0}</strong> lệnh
          </div>
        </div>

        <div className="card">
          <div className="card-title">
            <span>Thông lượng Telegram</span>
            <Radio size={16} className="text-muted" />
          </div>
          <div className="card-value">
            {telemetry?.signals_validated ?? 0} <span style={{ fontSize: "14px", fontWeight: 400, color: "var(--text-muted)" }}>/ {telemetry?.messages_received ?? 0}</span>
          </div>
          <div className="card-subtitle">
            Tín hiệu hợp lệ: <strong>{telemetry?.signals_validated ?? 0}</strong> | Chờ duyệt: <strong>{telemetry?.signals_needs_review ?? 0}</strong>
          </div>
        </div>
      </div>

      {/* Quick Positions Section */}
      <div className="table-container">
        <div className="table-header">
          <div className="table-title">Vị thế Đang Mở ({positions.length})</div>
          <button className="btn btn-secondary btn-sm" onClick={() => setTab("trading")}>
            Xem chi tiết
          </button>
        </div>
        <table>
          <thead>
            <tr>
              <th>Cặp giao dịch</th>
              <th>Chiều</th>
              <th>Khối lượng</th>
              <th>Giá vào (Entry)</th>
              <th>Giá hiện tại (Mark)</th>
              <th>Unrealized PnL</th>
              <th>Bảo vệ (SL/TP)</th>
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ textAlign: "center", color: "var(--text-muted)", padding: "28px" }}>
                  Hiện không có vị thế nào đang mở.
                </td>
              </tr>
            ) : (
              positions.map((pos) => {
                const unpnl = parseFloat(pos.unrealized_pnl || "0");
                return (
                  <tr key={pos.symbol}>
                    <td className="mono" style={{ fontWeight: 600 }}>{pos.symbol}</td>
                    <td>
                      <span className={`badge ${pos.side === "LONG" ? "badge-read-only" : "badge-live"}`}>
                        {pos.side} {pos.leverage}x
                      </span>
                    </td>
                    <td className="mono">{pos.amount}</td>
                    <td className="mono">{pos.entry_price}</td>
                    <td className="mono">{pos.mark_price || "—"}</td>
                    <td className={`mono ${unpnl >= 0 ? "text-success" : "text-danger"}`} style={{ fontWeight: 600 }}>
                      {unpnl >= 0 ? `+${unpnl.toFixed(2)}` : unpnl.toFixed(2)} USDT
                    </td>
                    <td>
                      {pos.sl_order_id ? (
                        <span className="badge badge-read-only">Đã cài SL</span>
                      ) : (
                        <span className="badge badge-live">CHƯA CÓ SL</span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Recent Alerts */}
      <div className="table-container">
        <div className="table-header">
          <div className="table-title">Cảnh báo & Hoạt động Gần đây</div>
          <button className="btn btn-secondary btn-sm" onClick={() => setTab("logs")}>
            Xem tất cả nhật ký
          </button>
        </div>
        <table>
          <thead>
            <tr>
              <th>Mức độ</th>
              <th>Tiêu đề</th>
              <th>Nội dung</th>
              <th>Nguồn</th>
              <th>Thời gian</th>
            </tr>
          </thead>
          <tbody>
            {alerts.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ textAlign: "center", color: "var(--text-muted)", padding: "24px" }}>
                  Chưa có thông báo hoặc cảnh báo nào.
                </td>
              </tr>
            ) : (
              alerts.map((al) => (
                <tr key={al.id}>
                  <td>
                    <span
                      className={`badge ${
                        al.level === "CRITICAL"
                          ? "badge-live"
                          : al.level === "WARNING"
                          ? "badge-shadow"
                          : "badge-read-only"
                      }`}
                    >
                      {al.level}
                    </span>
                  </td>
                  <td style={{ fontWeight: 600 }}>{al.title}</td>
                  <td style={{ color: "var(--text-secondary)" }}>{al.message}</td>
                  <td><code style={{ fontSize: "11px" }}>{al.source}</code></td>
                  <td className="mono" style={{ fontSize: "12px", color: "var(--text-muted)" }}>
                    {formatDateTime(al.timestamp)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
