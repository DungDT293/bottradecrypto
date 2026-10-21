import React, { useState, useEffect } from "react";
import { Search, Filter, Eye, AlertTriangle, RefreshCw } from "lucide-react";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";
import { wsClient } from "../services/websocket";
import { formatDateTime } from "../utils/date";
import type { SignalRecord } from "../types/api";

const ELITE_TOP5_CHAT_IDS = [
  -1002007658025, // THE WOLF (CRYPTO)®
  -1001756316676, // Boom_Boom_Billionaires
  -1002052872813, // CRYPTO LEOPARD'S
  -1001552004524, // CRYPTO MONK
  -1001370457350, // Crypto Neon
];

export const SignalsPage: React.FC = () => {
  const { addToast } = useApp();
  const [signals, setSignals] = useState<SignalRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [stateFilter, setStateFilter] = useState<string>("");
  const [symbolSearch, setSymbolSearch] = useState<string>("");
  const [selectedSignal, setSelectedSignal] = useState<any | null>(null);

  const fetchSignals = async (showLoading: boolean = false) => {
    if (showLoading) setLoading(true);
    try {
      const data = await api.getSignals(stateFilter || undefined, symbolSearch || undefined);
      const validData = (data || []).filter(
        (s) =>
          s.symbol &&
          s.symbol !== "UNKNOWN" &&
          s.symbol !== "None" &&
          (!s.chat_id || ELITE_TOP5_CHAT_IDS.includes(Number(s.chat_id)))
      );
      setSignals(validData);
    } catch (err: any) {
      if (showLoading) {
        addToast(err?.user_message || err?.message || "Lỗi tải danh sách tín hiệu.", "error");
      }
    } finally {
      if (showLoading) setLoading(false);
    }
  };

  useEffect(() => {
    fetchSignals(true);

    // 1. Subscribe to WebSocket events for instant realtime updates
    const unsub = wsClient.subscribe((event) => {
      if (
        event.event_type.startsWith("signal_") ||
        event.event_type.startsWith("order_") ||
        event.event_type.startsWith("position_") ||
        event.event_type === "backend_status_changed" ||
        event.event_type === "stats_updated"
      ) {
        fetchSignals(false);
      }
    });

    // 2. Realtime fallback polling every 5 seconds
    const interval = setInterval(() => {
      fetchSignals(false);
    }, 5000);

    return () => {
      unsub();
      clearInterval(interval);
    };
  }, [stateFilter]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchSignals(true);
  };

  const handleViewDetail = async (signalId: string) => {
    try {
      const detail = await api.getSignalDetail(signalId);
      setSelectedSignal(detail);
    } catch (err: any) {
      addToast("Không thể tải chi tiết tín hiệu.", "error");
    }
  };

  const renderStateBadge = (state: string) => {
    switch (state) {
      case "VALIDATED":
        return <span className="badge badge-read-only" style={{ background: "rgba(16, 185, 129, 0.15)", color: "#10b981", border: "1px solid rgba(16, 185, 129, 0.3)" }}>HỢP LỆ (VALIDATED)</span>;
      case "ENTRY_PENDING":
      case "PENDING_ENTRY":
        return <span className="badge badge-shadow" style={{ color: "#3b82f6", background: "rgba(59, 130, 246, 0.15)", border: "1px solid rgba(59, 130, 246, 0.3)" }}>CHỜ KHỚP (PENDING)</span>;
      case "OPEN_PROTECTED":
      case "ACTIVE":
      case "FILLED":
        return <span className="badge badge-read-only" style={{ background: "rgba(16, 185, 129, 0.2)", color: "#10b981", border: "1px solid rgba(16, 185, 129, 0.4)", fontWeight: 700 }}>ĐANG MỞ (CÓ SL)</span>;
      case "CLOSED":
        return <span className="badge" style={{ background: "rgba(148, 163, 184, 0.15)", color: "#94a3b8", border: "1px solid rgba(148, 163, 184, 0.3)" }}>ĐÃ ĐÓNG (CLOSED)</span>;
      case "STOPPED_OUT":
      case "CANCELLED":
        return <span className="badge badge-live-off">{state}</span>;
      case "REJECTED":
        return <span className="badge badge-live-off" style={{ opacity: 0.7 }}>BỊ TỪ CHỐI</span>;
      case "NEEDS_REVIEW":
      case "NEEDS_POLICY":
        return <span className="badge badge-live" style={{ background: "rgba(245, 158, 11, 0.15)", color: "#f59e0b" }}>CẦN XEM XÉT</span>;
      default:
        return <span className="badge">{state}</span>;
    }
  };

  return (
    <div>
      <div style={{ marginBottom: "20px" }}>
        <h2 style={{ fontSize: "20px", fontWeight: 700, color: "#fff" }}>Danh Sách Tín Hiệu</h2>
        <p style={{ color: "var(--text-secondary)", fontSize: "13px" }}>
          Tất cả tín hiệu thu thập và trích xuất từ các nhóm Telegram cùng trạng thái thực thi.
        </p>
      </div>

      {/* Filter and Search Bar */}
      <div style={{ display: "flex", gap: "12px", marginBottom: "16px", flexWrap: "wrap" }}>
        <form onSubmit={handleSearchSubmit} style={{ display: "flex", gap: "8px", flex: 1, minWidth: "260px" }}>
          <input
            type="text"
            className="form-input"
            placeholder="Tìm theo symbol (vd: BTC, ETH, SOL)..."
            value={symbolSearch}
            onChange={(e) => setSymbolSearch(e.target.value)}
          />
          <button type="submit" className="btn btn-secondary">
            <Search size={14} />
            <span>Tìm</span>
          </button>
        </form>

        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <Filter size={14} className="text-muted" />
          <select
            className="form-input"
            style={{ width: "auto" }}
            value={stateFilter}
            onChange={(e) => setStateFilter(e.target.value)}
          >
            <option value="">Tất cả trạng thái</option>
            <option value="OPEN_PROTECTED">ĐANG MỞ (CÓ SL)</option>
            <option value="ENTRY_PENDING">CHỜ KHỚP (ENTRY_PENDING)</option>
            <option value="VALIDATED">HỢP LỆ (VALIDATED)</option>
            <option value="CLOSED">ĐÃ ĐÓNG (CLOSED)</option>
            <option value="NEEDS_REVIEW">CẦN XEM XÉT (NEEDS_REVIEW)</option>
            <option value="REJECTED">BỊ TỪ CHỐI (REJECTED)</option>
          </select>

          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => fetchSignals(true)}
            disabled={loading}
            title="Làm mới danh sách tín hiệu ngay"
          >
            <RefreshCw size={14} className={loading ? "spin" : ""} />
            <span>Làm mới</span>
          </button>
        </div>
      </div>

      {/* Signals Table */}
      <div className="table-container">
        <div className="table-header">
          <div className="table-title">Tín hiệu giao dịch ({signals.length})</div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Thời gian</th>
              <th>Nhóm Telegram</th>
              <th>Cặp giao dịch</th>
              <th>Hướng</th>
              <th>Vùng Entry</th>
              <th>Stop Loss</th>
              <th>Mục tiêu TP</th>
              <th>Trạng thái</th>
              <th style={{ textAlign: "right" }}>Chi tiết</th>
            </tr>
          </thead>
          <tbody>
            {signals.length === 0 ? (
              <tr>
                <td colSpan={9} style={{ textAlign: "center", color: "var(--text-muted)", padding: "30px" }}>
                  {loading ? "Đang tải dữ liệu..." : "Không tìm thấy tín hiệu nào phù hợp điều kiện lọc."}
                </td>
              </tr>
            ) : (
              signals.map((sig) => (
                <tr key={sig.signal_id}>
                  <td className="mono" style={{ fontSize: "12px", color: "var(--text-muted)" }}>
                    {formatDateTime(sig.created_at)}
                  </td>
                  <td>
                    <span
                      className="badge badge-read-only"
                      style={{
                        fontSize: "11px",
                        background: "rgba(59, 130, 246, 0.12)",
                        color: "#60a5fa",
                        border: "1px solid rgba(59, 130, 246, 0.3)",
                      }}
                    >
                      {(sig as any).channel_name || "Top 5 Tinh hoa"}
                    </span>
                  </td>
                  <td className="mono" style={{ fontWeight: 600, color: "#fff" }}>
                    {sig.symbol}
                  </td>
                  <td>
                    {(() => {
                      const isLong = sig.side === "LONG" || sig.side === "BUY";
                      return (
                        <span
                          className="badge"
                          style={
                            isLong
                              ? { background: "rgba(16, 185, 129, 0.15)", color: "#10b981", border: "1px solid rgba(16, 185, 129, 0.3)", fontWeight: 700 }
                              : { background: "rgba(239, 68, 68, 0.15)", color: "#ef4444", border: "1px solid rgba(239, 68, 68, 0.3)", fontWeight: 700 }
                          }
                        >
                          {isLong ? "LONG" : "SHORT"} {sig.leverage}x
                        </span>
                      );
                    })()}
                  </td>
                  <td className="mono">
                    {(() => {
                      if (Array.isArray(sig.entries) && sig.entries.length > 0) return sig.entries.join(" - ");
                      if (typeof sig.entries === "string" && sig.entries) return sig.entries;
                      if ((sig as any).entries_json) {
                        try {
                          const parsed = JSON.parse((sig as any).entries_json);
                          if (Array.isArray(parsed) && parsed.length > 0) return parsed.join(" - ");
                        } catch {}
                      }
                      return "—";
                    })()}
                  </td>
                  <td className="mono text-danger" style={{ fontWeight: 600 }}>
                    {sig.stop_loss || "—"}
                  </td>
                  <td className="mono text-success" style={{ fontSize: "12px" }}>
                    {(() => {
                      if (Array.isArray(sig.take_profits) && sig.take_profits.length > 0) return sig.take_profits.join(", ");
                      if (typeof sig.take_profits === "string" && sig.take_profits) return sig.take_profits;
                      if ((sig as any).take_profits_json) {
                        try {
                          const parsed = JSON.parse((sig as any).take_profits_json);
                          if (Array.isArray(parsed) && parsed.length > 0) return parsed.join(", ");
                        } catch {}
                      }
                      return "—";
                    })()}
                  </td>
                  <td>{renderStateBadge(sig.state)}</td>
                  <td style={{ textAlign: "right" }}>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => handleViewDetail(sig.signal_id)}
                      title="Xem chi tiết và dòng thời gian tín hiệu"
                    >
                      <Eye size={13} />
                      <span>Xem</span>
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Signal Detail Modal */}
      {selectedSignal && (() => {
        const sig = selectedSignal.signal || selectedSignal;
        const rawMsg = selectedSignal.raw_message || {};
        const versions: any[] = selectedSignal.versions || [];
        const timeline: any[] = selectedSignal.timeline || [];
        const orders: any[] = selectedSignal.orders || [];
        const isLong = sig.side === "LONG" || sig.side === "BUY";

        const parseArray = (val: any) => {
          if (Array.isArray(val)) return val;
          if (typeof val === "string" && val.startsWith("[")) {
            try { return JSON.parse(val); } catch {}
          }
          if (typeof val === "string" && val) return [val];
          return [];
        };

        const entriesArr = parseArray(sig.entries || sig.entries_json);
        const tpsArr = parseArray(sig.take_profits || sig.take_profits_json);

        return (
          <div className="modal-overlay" onClick={() => setSelectedSignal(null)}>
            <div className="modal-content" style={{ maxWidth: "750px", maxHeight: "90vh", overflowY: "auto" }} onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                  <h3 style={{ margin: 0 }}>Chi tiết Tín hiệu: {sig.symbol || "UNKNOWN"}</h3>
                  <span
                    className="badge"
                    style={
                      isLong
                        ? { background: "rgba(16, 185, 129, 0.15)", color: "#10b981", border: "1px solid rgba(16, 185, 129, 0.3)", fontWeight: 700 }
                        : { background: "rgba(239, 68, 68, 0.15)", color: "#ef4444", border: "1px solid rgba(239, 68, 68, 0.3)", fontWeight: 700 }
                    }
                  >
                    {isLong ? "LONG" : "SHORT"} {sig.leverage}x
                  </span>
                  {renderStateBadge(sig.state)}
                </div>
                <button
                  onClick={() => setSelectedSignal(null)}
                  style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: "16px" }}
                >
                  ✕
                </button>
              </div>

              <div className="modal-body" style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                {/* 1. Core Params Grid */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", background: "rgba(255,255,255,0.02)", padding: "12px", borderRadius: "8px", border: "1px solid var(--border-color)" }}>
                  <div><strong>Mã tín hiệu (ID):</strong> <span className="mono" style={{ fontSize: "12px" }}>{sig.signal_id}</span></div>
                  <div><strong>Chat ID:</strong> <span className="mono" style={{ fontSize: "12px" }}>{sig.chat_id}</span> (Msg #{sig.message_id})</div>
                  <div><strong>Đòn bẩy & Margin:</strong> {sig.leverage}x ({sig.margin_mode || "ISOLATED"})</div>
                  <div><strong>Chế độ Entry:</strong> {sig.entry_mode || "LIMIT"}</div>
                  <div><strong>Mức Entry:</strong> <span className="mono" style={{ color: "#fff", fontWeight: 600 }}>{entriesArr.length > 0 ? entriesArr.join(" - ") : "—"}</span></div>
                  <div><strong>Stop Loss (Cắt lỗ):</strong> <span className="mono text-danger" style={{ fontWeight: 600 }}>{sig.stop_loss || "—"}</span></div>
                  <div style={{ gridColumn: "span 2" }}>
                    <strong>Take Profit (Chốt lời):</strong>{" "}
                    <span className="mono text-success" style={{ fontWeight: 600 }}>
                      {tpsArr.length > 0 ? tpsArr.map((tp: string, idx: number) => `TP${idx + 1}: ${tp}`).join(" | ") : "—"}
                    </span>
                  </div>
                  <div style={{ gridColumn: "span 2", fontSize: "12px", color: "var(--text-muted)" }}>
                    <strong>Thời gian tạo:</strong> {sig.created_at ? formatDateTime(sig.created_at) : "—"}
                  </div>
                </div>

                {/* 2. Blocking Reason Alert if any */}
                {sig.blocking_reason && (
                  <div style={{ padding: "12px 14px", background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.4)", borderRadius: "6px" }}>
                    <div style={{ fontWeight: 600, color: "var(--color-danger)", display: "flex", alignItems: "center", gap: "6px" }}>
                      <AlertTriangle size={16} /> Lý do chặn / Từ chối vào lệnh:
                    </div>
                    <div style={{ fontSize: "13px", marginTop: "4px", color: "#fca5a5" }}>
                      {sig.blocking_reason}
                    </div>
                  </div>
                )}

                {/* 3. Message Versions & Audit Trail */}
                <div>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "6px" }}>
                    <strong style={{ fontSize: "13px", color: "#fff" }}>
                      Lịch sử Sửa đổi Tin nhắn Telegram ({versions.length > 0 ? versions.length : 1} phiên bản):
                    </strong>
                    {versions.length > 1 && (
                      <span className="badge" style={{ background: "rgba(245, 158, 11, 0.15)", color: "#f59e0b", border: "1px solid rgba(245, 158, 11, 0.3)", fontSize: "11px" }}>
                        ⚠️ Admin đã sửa đổi tin nhắn
                      </span>
                    )}
                  </div>

                  {versions.length > 1 ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                      {versions.map((v: any) => (
                        <div key={v.version} style={{ border: "1px solid var(--border-color)", borderRadius: "6px", background: "var(--bg-input)", padding: "10px" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px", fontSize: "11px", color: "var(--text-muted)" }}>
                            <span style={{ fontWeight: 600, color: v.is_edit ? "#f59e0b" : "#10b981" }}>
                              Phiên bản {v.version} {v.is_edit ? "✏️ (Đã chỉnh sửa)" : "📌 (Bản gốc ban đầu)"}
                            </span>
                            <span>{formatDateTime(v.event_date || v.received_at)}</span>
                          </div>
                          <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: "12px", fontFamily: "var(--font-mono)", color: "#e2e8f0" }}>
                            {v.raw_text}
                          </pre>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <pre
                      style={{
                        background: "var(--bg-input)",
                        padding: "12px",
                        borderRadius: "6px",
                        marginTop: "4px",
                        whiteSpace: "pre-wrap",
                        fontSize: "12px",
                        fontFamily: "var(--font-mono)",
                        border: "1px solid var(--border-color)",
                        maxHeight: "180px",
                        overflowY: "auto",
                        color: "#e2e8f0",
                      }}
                    >
                      {rawMsg.raw_text || sig.raw_text || (versions[0] && versions[0].raw_text) || "Không có nội dung lưu trữ"}
                    </pre>
                  )}
                </div>

                {/* 4. Timeline Events */}
                {timeline.length > 0 && (
                  <div>
                    <strong style={{ fontSize: "13px", color: "#fff", display: "block", marginBottom: "8px" }}>
                      Dòng thời gian sự kiện (Timeline):
                    </strong>
                    <div style={{ display: "flex", flexDirection: "column", gap: "6px", maxHeight: "160px", overflowY: "auto", paddingRight: "4px" }}>
                      {timeline.map((evt: any, idx: number) => (
                        <div key={idx} style={{ display: "flex", alignItems: "flex-start", gap: "10px", fontSize: "12px", padding: "6px 10px", background: "rgba(255,255,255,0.02)", borderRadius: "4px", border: "1px solid var(--border-color)" }}>
                          <span className="mono" style={{ color: "var(--text-muted)", fontSize: "11px", minWidth: "140px" }}>
                            {formatDateTime(evt.timestamp)}
                          </span>
                          <span className="badge badge-read-only" style={{ fontSize: "10px", padding: "1px 6px" }}>
                            {evt.event_type}
                          </span>
                          <span style={{ color: "#e2e8f0", flex: 1 }}>{evt.description}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* 5. Binance Orders */}
                {orders.length > 0 && (
                  <div>
                    <strong style={{ fontSize: "13px", color: "#fff", display: "block", marginBottom: "8px" }}>
                      Lệnh Binance thực thi ({orders.length}):
                    </strong>
                    <table style={{ width: "100%", fontSize: "11px" }}>
                      <thead>
                        <tr>
                          <th>Client Order ID</th>
                          <th>Side</th>
                          <th>Loại</th>
                          <th>Giá</th>
                          <th>Số lượng</th>
                          <th>Trạng thái</th>
                        </tr>
                      </thead>
                      <tbody>
                        {orders.map((ord: any) => (
                          <tr key={ord.client_order_id}>
                            <td className="mono">{ord.client_order_id}</td>
                            <td>{ord.side}</td>
                            <td>{ord.order_type}</td>
                            <td className="mono">{ord.price || ord.trigger_price || "Market"}</td>
                            <td className="mono">{ord.quantity}</td>
                            <td><span className="badge badge-read-only">{ord.status}</span></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              <div className="modal-footer" style={{ borderTop: "1px solid var(--border-color)", padding: "12px 18px", display: "flex", justifyContent: "flex-end" }}>
                <button className="btn btn-secondary" onClick={() => setSelectedSignal(null)}>
                  Đóng
                </button>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
};
