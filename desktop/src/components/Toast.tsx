import React from "react";
import { CheckCircle2, AlertCircle, Info, AlertTriangle, X } from "lucide-react";
import { useApp } from "../context/AppContext";

export const ToastContainer: React.FC = () => {
  const { toasts, removeToast } = useApp();

  if (toasts.length === 0) return null;

  return (
    <div className="toast-container">
      {toasts.map((toast) => {
        let Icon = Info;
        let className = "toast";

        if (toast.type === "success") {
          Icon = CheckCircle2;
          className = "toast toast-success";
        } else if (toast.type === "error") {
          Icon = AlertCircle;
          className = "toast toast-error";
        } else if (toast.type === "warning") {
          Icon = AlertTriangle;
          className = "toast toast-warning";
        }

        return (
          <div key={toast.id} className={className}>
            <Icon size={16} />
            <div style={{ flex: 1 }}>{toast.text}</div>
            <button
              onClick={() => removeToast(toast.id)}
              style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer" }}
            >
              <X size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
};

