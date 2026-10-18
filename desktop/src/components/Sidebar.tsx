import React from "react";
import {
  LayoutDashboard,
  Link2,
  Users,
  Radio,
  TrendingUp,
  History,
  BarChart2,
  CheckSquare,
  FileText,
  Settings,
  ShieldCheck,
  Trophy,
} from "lucide-react";
import { useApp } from "../context/AppContext";
import type { NavTab } from "../context/AppContext";
import { api } from "../services/api";

interface NavItemDef {
  key: NavTab;
  label: string;
  icon: React.ElementType;
  badge?: number;
}

export const Sidebar: React.FC = () => {
  const { tab, setTab, snapshot } = useApp();
  const [reviewCount, setReviewCount] = React.useState<number>(0);

  React.useEffect(() => {
    api.getSignals("NEEDS_REVIEW").then((sigs) => {
      setReviewCount(sigs.length);
    }).catch(() => {});
  }, [snapshot]);

  const unreadAlerts = snapshot?.unread_alerts_count ?? (snapshot?.alerts?.filter((a) => !a.read).length || 0);

  const navItems: NavItemDef[] = [
    { key: "overview", label: "Tổng quan", icon: LayoutDashboard },
    { key: "connections", label: "Kết nối", icon: Link2 },
    { key: "groups", label: "Nhóm Telegram", icon: Users },
    { key: "leaderboard", label: "Đánh giá & Xếp hạng", icon: Trophy },
    { key: "signals", label: "Tín hiệu", icon: Radio },
    { key: "trading", label: "Đang giao dịch", icon: TrendingUp },
    { key: "history", label: "Lịch sử", icon: History },
    { key: "stats", label: "Thống kê", icon: BarChart2 },
    { key: "reviews", label: "Chờ xác nhận", icon: CheckSquare, badge: reviewCount },
    { key: "logs", label: "Nhật ký & Cảnh báo", icon: FileText, badge: unreadAlerts },
    { key: "settings", label: "Cài đặt", icon: Settings },
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <ShieldCheck size={24} className="text-success" />
        <div>
          <h1>Signal Executor</h1>
          <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>v1.2.0 Desktop Shell</div>
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
          Chế độ: <strong style={{ color: "var(--text-secondary)" }}>{snapshot?.mode || "READ_ONLY"}</strong>
        </div>
      </div>
    </aside>
  );
};
