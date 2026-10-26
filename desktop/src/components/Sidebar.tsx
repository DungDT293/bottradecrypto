import React from "react";
import {
  LayoutDashboard,
  Link2,
  TrendingUp,
  History,
  BarChart2,
  FileText,
  Settings,
  ShieldCheck,
} from "lucide-react";
import { useApp } from "../context/AppContext";
import type { NavTab } from "../context/AppContext";

interface NavItemDef {
  key: NavTab;
  label: string;
  icon: React.ElementType;
  badge?: number;
}

export const Sidebar: React.FC = () => {
  const { tab, setTab, snapshot } = useApp();

  const unreadAlerts = snapshot?.unread_alerts_count ?? (snapshot?.alerts?.filter((a) => !a.read).length || 0);

  const navItems: NavItemDef[] = [
    { key: "overview", label: "Tổng quan", icon: LayoutDashboard },
    { key: "trading", label: "Đang giao dịch", icon: TrendingUp },
    { key: "history", label: "Lịch sử", icon: History },
    { key: "stats", label: "Thống kê & PnL", icon: BarChart2 },
    { key: "connections", label: "Kết nối", icon: Link2 },
    { key: "logs", label: "Nhật ký & Cảnh báo", icon: FileText, badge: unreadAlerts },
    { key: "settings", label: "Cài đặt", icon: Settings },
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <ShieldCheck size={24} className="text-success" />
        <div>
          <h1>Signal Executor</h1>
          <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>v2.6.0 Quantum Dual-AI</div>
        </div>

      </div>

      <nav className="sidebar-nav">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = tab === item.key;
          return (
            <div
              key={item.key}
              className={`nav-item ${isActive ? "active" : ""}`}
              onClick={() => setTab(item.key)}
            >
              <Icon size={18} />
              <span>{item.label}</span>
              {item.badge !== undefined && item.badge > 0 && (
                <span className="nav-badge">{item.badge}</span>
              )}
            </div>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
          <span>Trạng thái Bot:</span>
          <span style={{ fontWeight: 600, color: "#fff" }}>
            {snapshot?.engine_status || "IDLE"}
          </span>
        </div>
        <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>
          Chế độ: <strong style={{ color: snapshot?.mode === "LIVE" ? "#10b981" : "var(--text-secondary)" }}>
            {snapshot?.mode === "LIVE" ? "TIỀN THẬT (LIVE)" : (snapshot?.mode || "LIVE")}
          </strong>
        </div>
      </div>
    </aside>
  );
};
