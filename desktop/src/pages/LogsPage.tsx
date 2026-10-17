import React, { useState, useEffect } from "react";
import { CheckCheck, Filter, Download } from "lucide-react";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";
import { getBackendInfo } from "../services/backendBridge";
import { formatDateTime } from "../utils/date";
import type { AlertRecord } from "../types/api";

export const LogsPage: React.FC = () => {
  const { snapshot, addToast, refreshSnapshot } = useApp();
  const [alerts, setAlerts] = useState<AlertRecord[]>([]);
  const [levelFilter, setLevelFilter] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const fetchAlerts = async () => {
    setLoading(true);
    try {
      const data = await api.getAlerts(100);
      setAlerts(data);
    } catch (err: any) {
      addToast("Lỗi tải danh sách nhật ký.", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAlerts();
  }, []);

  const handleExportDiagnostics = async () => {
    try {
      const backend = await getBackendInfo().catch(() => null);
      const diagnosticData = {
        timestamp: new Date().toISOString(),
        frontend_version: "0.1.1",
        user_agent: navigator.userAgent,
        is_tauri: Boolean((window as any).__TAURI_INTERNALS__),
        backend_info: backend
          ? {
              host: backend.host,
              port: backend.port,
              status: backend.status,
              session_token_masked: backend.session_token ? `${backend.session_token.substring(0, 4)}...***` : "MISSING",
              pid: backend.pid,
              instance_id: backend.instance_id,
            }
          : "UNREACHABLE",
        system_snapshot: snapshot
          ? {
              mode: snapshot.mode,
              live_trading_enabled: snapshot.live_trading_enabled,
              entry_enabled: snapshot.entry_enabled,
              engine_status: snapshot.engine_status,
              account_connected: snapshot.account?.connected,
              telegram_connected: snapshot.telemetry?.messages_processed != null,
            }
          : "NO_SNAPSHOT",
        recent_alerts: alerts.slice(0, 20).map((a) => ({
          time: a.timestamp,
          level: a.level,
          title: a.title,
          message: a.message,
        })),
      };

      const blob = new Blob([JSON.stringify(diagnosticData, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `diagnostics_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      addToast("Đã xuất báo cáo chẩn đoán hệ thống (đã che thông tin nhạy cảm).", "success");
    } catch {
      addToast("Lỗi khi xuất chẩn đoán hệ thống.", "error");
    }
  };

  const handleMarkAllRead = async () => {
    try {
      const res = await api.markAllAlertsRead();
      addToast(`Đã đánh dấu ${res.marked_count} cảnh báo là đã đọc.`, "success");
      await fetchAlerts();
      await refreshSnapshot();
    } catch (err: any) {
      addToast("Lỗi khi cập nhật trạng thái đã đọc.", "error");
    }
  };

  const filteredAlerts = levelFilter
    ? alerts.filter((a) => a.level === levelFilter)
    : alerts;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
        <div>
          <h2 style={{ fontSize: "20px", fontWeight: 700, color: "#fff" }}>Nhật Ký & Cảnh Báo</h2>
          <p style={{ color: "var(--text-secondary)", fontSize: "13px" }}>
            Lịch sử thông báo hệ thống, cảnh báo an toàn và nhật ký sự kiện giao dịch.
          </p>
        </div>

        <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <Filter size={14} className="text-muted" />
            <select
              className="form-input"
              style={{ width: "auto" }}
              value={levelFilter}
              onChange={(e) => setLevelFilter(e.target.value)}
            >
              <option value="">Tất cả mức độ</option>
              <option value="CRITICAL">CRITICAL (Nghiêm trọng)</option>
              <option value="WARNING">WARNING (Cảnh báo)</option>
              <option value="INFO">INFO (Thông tin)</option>
            </select>
          </div>

          <button className="btn btn-secondary" onClick={handleMarkAllRead}>
            <CheckCheck size={14} />
            <span>Đánh dấu đã đọc</span>
          </button>

          <button
            className="btn btn-secondary"
            onClick={handleExportDiagnostics}
            title="Xuất file chẩn đoán hệ thống (đã che thông tin nhạy cảm)"
          >
            <Download size={14} />
            <span>Xuất chẩn đoán</span>
          </button>
        </div>
      </div>

      <div className="table-container">
        <div className="table-header">
          <div className="table-title">Nhật ký Hoạt động ({filteredAlerts.length})</div>
        </div>
        <table>
          <thead>
            <tr>
              <th style={{ width: "110px" }}>Mức độ</th>
              <th style={{ width: "220px" }}>Tiêu đề</th>
              <th>Chi tiết thông điệp</th>
              <th style={{ width: "120px" }}>Nguồn</th>
              <th style={{ width: "170px" }}>Thời gian</th>
            </tr>
          </thead>
          <tbody>
            {filteredAlerts.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ textAlign: "center", color: "var(--text-muted)", padding: "36px" }}>
                  {loading ? "Đang tải dữ liệu..." : "Không có nhật ký nào phù hợp bộ lọc."}
                </td>
              </tr>
            ) : (
              filteredAlerts.map((al) => (
                <tr key={al.id} style={{ opacity: al.read ? 0.75 : 1 }}>
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
                  <td style={{ fontWeight: 600, color: "#fff" }}>{al.title}</td>
                  <td style={{ color: "var(--text-secondary)" }}>{al.message}</td>
                  <td>
                    <code style={{ fontSize: "11px" }}>{al.source}</code>
                  </td>
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
