import React, { useState } from "react";
import {
  Crown,
  Key,
  Copy,
  Check,
  AlertTriangle,
  Clock,
  Sparkles,
  ShieldCheck,
  X,
} from "lucide-react";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";

export const LicenseModal: React.FC = () => {
  const { license, refreshLicense, isLicenseModalOpen, closeLicenseModal, addToast } = useApp();

  const [inputKey, setInputKey] = useState("");
  const [activating, setActivating] = useState(false);
  const [activatingTrial, setActivatingTrial] = useState(false);
  const [copiedHwid, setCopiedHwid] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  if (!isLicenseModalOpen) return null;

  const handleCopyHwid = () => {
    if (!license?.hwid) return;
    navigator.clipboard.writeText(license.hwid);
    setCopiedHwid(true);
    addToast("Đã sao chép Mã Máy (HWID) vào clipboard!", "success");
    setTimeout(() => setCopiedHwid(false), 2500);
  };

  const handleActivate = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!inputKey.trim()) {
      setErrorMessage("Vui lòng nhập License Key.");
      return;
    }

    setActivating(true);
    setErrorMessage(null);
    try {
      const res = await api.activateLicense(inputKey.trim());
      addToast(res.message || "Kích hoạt bản quyền thành công!", "success");
      setInputKey("");
      await refreshLicense();
    } catch (err: any) {
      const msg = err?.user_message || err?.message || "Key không hợp lệ hoặc đã hết hạn.";
      setErrorMessage(msg);
      addToast(msg, "error");
    } finally {
      setActivating(false);
    }
  };

  const handleActivateTrial = async () => {
    setActivatingTrial(true);
    setErrorMessage(null);
    try {
      const res = await api.activateTrial();
      addToast(res.message || "Kích hoạt 3 ngày dùng thử thành công!", "success");
      await refreshLicense();
    } catch (err: any) {
      const msg = err?.user_message || err?.message || "Không thể kích hoạt dùng thử.";
      setErrorMessage(msg);
      addToast(msg, "warning");
    } finally {
      setActivatingTrial(false);
    }
  };

  const isVip = license?.is_active ?? false;
  const isLifetime = license?.is_lifetime ?? false;
  const isTrial = license?.plan?.includes("TRIAL") ?? false;

  return (
    <div className="modal-overlay" onClick={closeLicenseModal}>
      <div
        className="modal-content"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: "560px", width: "95%" }}
      >
        {/* Header */}
        <div className="modal-header">
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <div
              style={{
                width: "34px",
                height: "34px",
                borderRadius: "8px",
                background: "linear-gradient(135deg, rgba(245, 158, 11, 0.25) 0%, rgba(217, 119, 6, 0.15) 100%)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                border: "1px solid rgba(245, 158, 11, 0.4)",
              }}
            >
              <Crown size={20} color="#fbbf24" />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700 }}>
                Quản Lý Bản Quyền Thương Mại VIP
              </h3>
              <p style={{ margin: "2px 0 0 0", fontSize: "12px", color: "var(--text-muted)" }}>
                Hệ thống khóa phần cứng bảo mật độc quyền (HWID-Locked)
              </p>
            </div>
          </div>
          <button
            onClick={closeLicenseModal}
            style={{
              background: "none",
              border: "none",
              color: "var(--text-muted)",
              cursor: "pointer",
              padding: "4px",
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="modal-body" style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
          {/* Current License Status Card */}
          <div
            style={{
              padding: "16px",
              borderRadius: "8px",
              background: isLifetime
                ? "linear-gradient(135deg, rgba(245, 158, 11, 0.12) 0%, rgba(217, 119, 6, 0.05) 100%)"
                : isVip
                ? "linear-gradient(135deg, rgba(16, 185, 129, 0.12) 0%, rgba(5, 150, 105, 0.05) 100%)"
                : "linear-gradient(135deg, rgba(239, 68, 68, 0.12) 0%, rgba(185, 28, 28, 0.05) 100%)",
              border: `1px solid ${
                isLifetime
                  ? "rgba(245, 158, 11, 0.4)"
                  : isVip
                  ? "rgba(16, 185, 129, 0.4)"
                  : "rgba(239, 68, 68, 0.4)"
              }`,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "10px" }}>
              <div>
                <span style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.5px", color: "var(--text-muted)", fontWeight: 600 }}>
                  Trạng thái hiện tại
                </span>
                <div style={{ fontSize: "16px", fontWeight: 700, color: "#fff", display: "flex", alignItems: "center", gap: "6px", marginTop: "2px" }}>
                  {isLifetime ? (
                    <>
                      <Crown size={18} color="#fbbf24" />
                      <span style={{ color: "#fbbf24" }}>VIP TRỌN ĐỜI (VĨNH VIỄN)</span>
                    </>
                  ) : isVip ? (
                    <>
                      <ShieldCheck size={18} color="#34d399" />
                      <span style={{ color: "#34d399" }}>
                        {isTrial ? "DÙNG THỬ TRẢI NGHIỆM" : "BẢN QUYỀN VIP CHÍNH THỨC"}
                      </span>
                    </>
                  ) : (
                    <>
                      <AlertTriangle size={18} color="#f87171" />
                      <span style={{ color: "#f87171" }}>CHƯA KÍCH HOẠT / HẾT HẠN</span>
                    </>
                  )}
                </div>
              </div>

              <span
                className={`badge ${
                  isLifetime
                    ? "badge-vip-lifetime"
                    : isVip
                    ? (isTrial ? "badge-vip-trial" : "badge-vip-active")
                    : "badge-vip-expired"
                }`}
              >
                {license?.status || "UNLICENSED"}
              </span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginTop: "12px", fontSize: "13px" }}>
              <div>
                <span style={{ color: "var(--text-muted)" }}>Gói bản quyền:</span>{" "}
                <strong style={{ color: "#fff" }}>{license?.plan || "Chưa có"}</strong>
              </div>
              <div>
                <span style={{ color: "var(--text-muted)" }}>Thời hạn còn:</span>{" "}
                <strong style={{ color: isVip ? "#34d399" : "#f87171" }}>
                  {isLifetime
                    ? "Vĩnh viễn"
                    : isVip
                    ? `${license?.days_remaining ?? 0} ngày`
                    : "0 ngày"}
                </strong>
              </div>
              {license?.expires_at && !isLifetime && (
                <div style={{ gridColumn: "1 / -1" }}>
                  <span style={{ color: "var(--text-muted)" }}>Hạn dùng đến:</span>{" "}
                  <strong style={{ color: "#fff" }}>{license.expires_at}</strong>
                </div>
              )}
            </div>

            {license?.message && (
              <div style={{ marginTop: "10px", fontSize: "12px", color: isVip ? "var(--text-secondary)" : "#fca5a5" }}>
                ℹ️ {license.message}
              </div>
            )}
          </div>

          {/* Machine HWID Box */}
          <div>
            <label className="form-label" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: 600 }}>Mã Định Danh Máy (Machine HWID)</span>
              <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                Dùng để cấp bản quyền độc quyền
              </span>
            </label>
            <div style={{ display: "flex", gap: "8px" }}>
              <input
                type="text"
                className="form-input mono"
                readOnly
                value={license?.hwid || "Đang lấy mã HWID..."}
                style={{
                  backgroundColor: "rgba(0, 0, 0, 0.35)",
                  color: "#93c5fd",
                  fontWeight: 600,
                  fontSize: "13px",
                  cursor: "default",
                }}
              />
              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleCopyHwid}
                title="Sao chép mã máy để gửi Admin cấp Key"
                style={{ whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: "6px" }}
              >
                {copiedHwid ? <Check size={16} color="#34d399" /> : <Copy size={16} />}
                <span>{copiedHwid ? "Đã chép!" : "Sao Chép"}</span>
              </button>
            </div>
            <p style={{ margin: "4px 0 0 0", fontSize: "11px", color: "var(--text-muted)" }}>
              💡 Gửi chuỗi mã này cho Quản trị viên để nhận Key kích hoạt tương ứng cho máy tính này.
            </p>
          </div>

          {/* Activate Key Form */}
          <form onSubmit={handleActivate}>
            <label className="form-label" style={{ fontWeight: 600 }}>
              Nhập Mã Bản Quyền (License Key)
            </label>
            <div style={{ display: "flex", gap: "8px" }}>
              <input
                type="text"
                className="form-input mono"
                placeholder="VIP-eyJuYW1lIjoi..."
                value={inputKey}
                onChange={(e) => {
                  setInputKey(e.target.value);
                  if (errorMessage) setErrorMessage(null);
                }}
                disabled={activating}
                style={{ fontSize: "12px" }}
              />
              <button
                type="submit"
                className="btn btn-primary"
                disabled={activating || !inputKey.trim()}
                style={{ whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: "6px" }}
              >
                {activating ? (
                  <>
                    <Clock size={16} className="spin" />
                    <span>Đang kiểm tra...</span>
                  </>
                ) : (
                  <>
                    <Key size={16} />
                    <span>Kích Hoạt Key</span>
                  </>
                )}
              </button>
            </div>
            {errorMessage && (
              <div style={{ marginTop: "6px", fontSize: "12px", color: "#f87171" }}>
                ⚠️ {errorMessage}
              </div>
            )}
          </form>

          {/* 1-Click Free Trial Box (if not already lifetime) */}
          {!isLifetime && (
            <div
              style={{
                padding: "14px",
                borderRadius: "8px",
                background: "rgba(59, 130, 246, 0.08)",
                border: "1px dashed rgba(59, 130, 246, 0.35)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "12px",
              }}
            >
              <div>
                <div style={{ fontSize: "13px", fontWeight: 600, color: "#93c5fd", display: "flex", alignItems: "center", gap: "6px" }}>
                  <Sparkles size={16} />
                  <span>Dùng Thử Miễn Phí 3 Ngày (1-Click)</span>
                </div>
                <p style={{ margin: "2px 0 0 0", fontSize: "11px", color: "var(--text-secondary)" }}>
                  Trải nghiệm đầy đủ tính năng tự động giao dịch 24/7 mà không cần License Key.
                </p>
              </div>

              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleActivateTrial}
                disabled={activatingTrial || isVip}
                style={{
                  whiteSpace: "nowrap",
                  borderColor: "rgba(59, 130, 246, 0.4)",
                  color: "#93c5fd",
                }}
              >
                {activatingTrial ? "Đang xử lý..." : isVip ? "Đang có bản quyền" : "Dùng Thử Ngay"}
              </button>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="modal-footer" style={{ justifyContent: "space-between" }}>
          <div style={{ fontSize: "11px", color: "var(--text-muted)", display: "flex", alignItems: "center", gap: "4px" }}>
            <span>Telegram Bot Commercial Suite v1.3.1</span>
          </div>
          <button className="btn btn-secondary" onClick={closeLicenseModal}>
            Đóng
          </button>
        </div>
      </div>
    </div>
  );
};