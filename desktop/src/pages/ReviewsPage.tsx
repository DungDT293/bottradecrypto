import React, { useState, useEffect } from "react";
import { CheckCircle2, XCircle, AlertTriangle } from "lucide-react";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";
import { formatDateTime } from "../utils/date";
import type { SignalRecord } from "../types/api";

export const ReviewsPage: React.FC = () => {
  const { addToast, refreshSnapshot } = useApp();
  const [reviewSignals, setReviewSignals] = useState<SignalRecord[]>([]);
  const [loading, setLoading] = useState(false);

  // Resolution modal state
  const [resolvingSignal, setResolvingSignal] = useState<SignalRecord | null>(null);
  const [targetState, setTargetState] = useState<"VALIDATED" | "REJECTED">("REJECTED");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const fetchReviewSignals = async () => {
    setLoading(true);
    try {
      const data = await api.getSignals("NEEDS_REVIEW");
      setReviewSignals(data);
    } catch (err: any) {
      addToast("Lỗi tải danh sách tín hiệu chờ duyệt.", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReviewSignals();
  }, []);

  const openResolution = (sig: SignalRecord, state: "VALIDATED" | "REJECTED") => {
    setResolvingSignal(sig);
    setTargetState(state);
    setReason(
      state === "VALIDATED"
        ? "Người dùng đã kiểm tra và phê duyệt tín hiệu."
        : state === "REJECTED"
        ? "Người dùng từ chối tín hiệu do vi phạm rủi ro hoặc trùng coin."
        : "Người dùng hủy bỏ tín hiệu."
    );
  };

  const handleSubmitResolution = async () => {
    if (!resolvingSignal) return;
    setSubmitting(true);
    try {
      await api.resolveSignal(resolvingSignal.signal_id, targetState, reason);
      addToast(`Đã cập nhật tín hiệu ${resolvingSignal.symbol} sang trạng thái ${targetState}.`, "success");
      setResolvingSignal(null);
      await fetchReviewSignals();
      await refreshSnapshot();
    } catch (err: any) {
      addToast(err?.user_message || err?.message || "Lỗi cập nhật tín hiệu.", "error");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <div style={{ marginBottom: "20px" }}>
        <h2 style={{ fontSize: "20px", fontWeight: 700, color: "#fff" }}>Tín Hiệu Chờ Xác Nhận</h2>
        <p style={{ color: "var(--text-secondary)", fontSize: "13px" }}>
          Các tín hiệu bị chặn tự động bởi chính sách an toàn (trùng coin, nới SL tăng rủi ro, cú pháp mơ hồ).
        </p>
      </div>

      <div className="table-container">
        <div className="table-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div className="table-title">Danh sách Chờ Xem Xét ({reviewSignals.length})</div>
          {reviewSignals.length > 0 && (
            <button
              className="btn btn-secondary btn-sm"
              style={{ color: "var(--color-danger)" }}
              onClick={async () => {
                if (!window.confirm("Bạn có chắc chắn muốn từ chối tất cả các tín hiệu đang chờ duyệt này?")) return;
                for (const s of reviewSignals) {
                  try {
                    await api.resolveSignal(s.signal_id, "REJECTED", "Người dùng từ chối hàng loạt tín hiệu cũ.");
                  } catch {}
                }
                addToast("Đã từ chối tất cả tín hiệu chờ duyệt.", "success");
                await fetchReviewSignals();
                await refreshSnapshot();
              }}
            >
              <XCircle size={14} />
              <span>Từ chối tất cả</span>
            </button>
          )}
        </div>
        <table>
          <thead>
            <tr>
              <th>Thời gian</th>
              <th>Cặp</th>
              <th>Chiều</th>
              <th>Entry / SL / TP</th>
              <th>Lý do Cần Xem Xét</th>
              <th style={{ textAlign: "right" }}>Quyết định</th>
            </tr>
          </thead>
          <tbody>
            {reviewSignals.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ textAlign: "center", color: "var(--text-muted)", padding: "36px" }}>
                  {loading ? "Đang tải dữ liệu..." : "Tuyệt vời! Hiện không có tín hiệu nào cần xử lý thủ công."}
                </td>
              </tr>
            ) : (
              reviewSignals.map((sig) => (
                <tr key={sig.signal_id}>
                  <td className="mono" style={{ fontSize: "12px", color: "var(--text-muted)" }}>
                    {formatDateTime(sig.created_at)}
                  </td>
                  <td className="mono" style={{ fontWeight: 700, color: "#fff" }}>{sig.symbol}</td>
                  <td>
                    <span className={`badge ${sig.side === "BUY" ? "badge-read-only" : "badge-live"}`}>
                      {sig.side === "BUY" ? "LONG" : "SHORT"} {sig.leverage}x
                    </span>
                  </td>
                  <td className="mono" style={{ fontSize: "12px" }}>
                    <div style={{ fontWeight: 600 }}>
                      Entry: {Array.isArray(sig.entries) && sig.entries.length > 0 ? sig.entries.join(", ") : "Thị trường"}
                    </div>
                    <div style={{ color: "var(--text-muted)", fontSize: "11px", marginTop: "2px" }}>
                      SL: {sig.stop_loss || "—"} {sig.take_profits && sig.take_profits.length > 0 ? `| TP: ${sig.take_profits.join(", ")}` : ""}
                    </div>
                  </td>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px", color: "var(--color-warning)" }}>
                      <AlertTriangle size={15} />
                      <span style={{ fontSize: "13px" }}>{sig.blocking_reason || "Cần quản trị viên xác nhận"}</span>
                    </div>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <div style={{ display: "inline-flex", gap: "6px" }}>
                      <button
                        className="btn btn-secondary btn-sm"
                        style={{ color: "var(--color-success)" }}
                        onClick={() => openResolution(sig, "VALIDATED")}
                      >
                        <CheckCircle2 size={13} />
                        <span>Duyệt</span>
                      </button>
                      <button
                        className="btn btn-secondary btn-sm"
                        style={{ color: "var(--color-danger)" }}
                        onClick={() => openResolution(sig, "REJECTED")}
                      >
                        <XCircle size={13} />
                        <span>Từ chối</span>
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Manual Resolution Modal */}
      {resolvingSignal && (
        <div className="modal-overlay" onClick={() => setResolvingSignal(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>
                {targetState === "VALIDATED" ? "Duyệt Tín Hiệu" : "Từ Chối Tín Hiệu"}: {resolvingSignal.symbol}
              </h3>
              <button
                onClick={() => setResolvingSignal(null)}
                style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer" }}
              >
                ✕
              </button>
            </div>
            <div className="modal-body">
              <p style={{ marginBottom: "12px", color: "var(--text-secondary)" }}>
                Bạn đang chuẩn bị chuyển tín hiệu <strong className="mono">{resolvingSignal.symbol}</strong> sang trạng thái:{" "}
                <span className="badge badge-read-only">{targetState}</span>
              </p>

              <div className="form-group">
                <label className="form-label">Ghi chú / Lý do quyết định</label>
                <textarea
                  className="form-input"
                  rows={3}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Nhập lý do phê duyệt hoặc từ chối..."
                />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setResolvingSignal(null)}>
                Hủy bỏ
              </button>
              <button
                className={`btn ${targetState === "VALIDATED" ? "btn-primary" : "btn-danger"}`}
                onClick={handleSubmitResolution}
                disabled={submitting}
              >
                {submitting ? "Đang xử lý..." : "Lưu Quyết Định"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
