import React, { useState } from "react";
import { AlertTriangle, X } from "lucide-react";

interface ConfirmModalProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  isDanger?: boolean;
  requiredKeyword?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export const ConfirmModal: React.FC<ConfirmModalProps> = ({
  isOpen,
  title,
  message,
  confirmText = "Xác nhận",
  cancelText = "Hủy bỏ",
  isDanger = false,
  requiredKeyword,
  onConfirm,
  onCancel,
}) => {
  const [typedInput, setTypedInput] = useState("");

  if (!isOpen) return null;

  const isConfirmedAllowed = !requiredKeyword || typedInput.trim().toUpperCase() === requiredKeyword.toUpperCase();

  const handleConfirm = () => {
    if (isConfirmedAllowed) {
      onConfirm();
      setTypedInput("");
    }
  };

  const handleCancel = () => {
    setTypedInput("");
    onCancel();
  };

  return (
    <div className="modal-overlay" onClick={handleCancel}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            {isDanger && <AlertTriangle size={18} className="text-danger" />}
            <h3>{title}</h3>
          </div>
          <button
            onClick={handleCancel}
            style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer" }}
          >
            <X size={18} />
          </button>
        </div>

        <div className="modal-body">
          <p style={{ whiteSpace: "pre-line", marginBottom: requiredKeyword ? "16px" : "0" }}>
            {message}
          </p>

          {requiredKeyword && (
            <div style={{ marginTop: "12px" }}>
              <div style={{ fontSize: "12px", color: "var(--color-danger)", marginBottom: "6px" }}>
                Vui lòng gõ chính xác từ <strong>{requiredKeyword}</strong> để mở khóa nút xác nhận:
              </div>
              <input
                type="text"
                className="form-input"
                placeholder={requiredKeyword}
                value={typedInput}
                onChange={(e) => setTypedInput(e.target.value)}
                autoFocus
              />
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={handleCancel}>
            {cancelText}
          </button>
          <button
            className={`btn ${isDanger ? "btn-danger" : "btn-primary"}`}
            onClick={handleConfirm}
            disabled={!isConfirmedAllowed}
            style={{ opacity: isConfirmedAllowed ? 1 : 0.5, cursor: isConfirmedAllowed ? "pointer" : "not-allowed" }}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
};

