import React, { useState, useEffect } from "react";
import {
  Trophy,
  Search,
  RefreshCw,
  ShieldAlert,
  Eye,
  X,
  Flame,
} from "lucide-react";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";
import { formatDateTime } from "../utils/date";
import type {
  ChannelLeaderboardItem,
  ChannelLeaderboardSummary,
  ChannelLeaderboardResponse,
} from "../types/api";

export const ELITE_TOP5_CHAT_IDS = [
  -1002007658025, // THE WOLF (CRYPTO)®
  -1001756316676, // Boom_Boom_Billionaires
  -1002052872813, // CRYPTO LEOPARD'S
  -1001552004524, // CRYPTO MONK
  -1001370457350, // Crypto Neon
];

export const LeaderboardPage: React.FC = () => {
  const { snapshot, addToast } = useApp();
  const [loading, setLoading] = useState<boolean>(true);
  const [timeframe, setTimeframe] = useState<string>("all");

  // Determine user's real Binance Futures capital from live snapshot
  const rawEquity =
    snapshot?.account?.equity ||
    snapshot?.account?.total_margin_balance ||
    snapshot?.account?.wallet_balance ||
    "86.18";
  const realEquitySafe =
    Number.isFinite(parseFloat(rawEquity)) && parseFloat(rawEquity) > 0
      ? parseFloat(parseFloat(rawEquity).toFixed(2))
      : 86.18;

  // Capital simulation mode: "real" (default) or "1000" or "5000"
  const [capitalMode, setCapitalMode] = useState<"real" | "1000" | "5000">("real");
  const marginPct = 1.5; // Matches config.risk.target_margin_pct (1.5%)

  const effectiveBankroll =
    capitalMode === "real" ? realEquitySafe : capitalMode === "1000" ? 1000 : 5000;

  const [summary, setSummary] = useState<ChannelLeaderboardSummary | null>(null);
  const [channels, setChannels] = useState<ChannelLeaderboardItem[]>([]);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [selectedTier, setSelectedTier] = useState<string>("ALL");

  // Detail Modal State
  const [detailModalOpen, setDetailModalOpen] = useState<boolean>(false);
  const [selectedChannel, setSelectedChannel] = useState<ChannelLeaderboardItem | null>(null);
  const [channelSignals, setChannelSignals] = useState<any[]>([]);
  const [signalsLoading, setSignalsLoading] = useState<boolean>(false);

  const fetchLeaderboard = async () => {
    setLoading(true);
    try {
      const res: ChannelLeaderboardResponse = await api.getChannelLeaderboard(
        timeframe,
        effectiveBankroll,
        marginPct
      );
      if (res.success) {
        const top5Channels = (res.channels || []).filter((c) =>
          ELITE_TOP5_CHAT_IDS.includes(Number(c.chat_id))
        );
        const updatedSummary = res.summary
          ? {
              ...res.summary,
              total_channels: top5Channels.length,
              total_pinned_channels: top5Channels.length,
              active_trading_channels: top5Channels.length,
              total_signals_validated: top5Channels.reduce(
                (acc, c) => acc + (c.validated_signals || 0),
                0
              ),
              overall_win_rate_pct:
                top5Channels.length > 0
                  ? Math.round(
                      (top5Channels.reduce(
                        (acc, c) => acc + (c.performance?.win_rate_pct || 0),
                        0
                      ) /
                        top5Channels.length) *
                        10
                    ) / 10
                  : 0,
            }
          : null;
        setSummary(updatedSummary);
        setChannels(top5Channels);
      }
    } catch (err: any) {
      addToast(err?.user_message || err?.message || "Lỗi tải dữ liệu bảng xếp hạng", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLeaderboard();
  }, [timeframe, effectiveBankroll, marginPct]);

  const handleOpenDetail = async (channel: ChannelLeaderboardItem) => {
    setSelectedChannel(channel);
    setDetailModalOpen(true);
    setSignalsLoading(true);
    try {
      const res = await api.getChannelDetail(channel.chat_id);
      if (res.success) {
        setChannelSignals(res.signals);
      }
    } catch (err: any) {
      addToast("Không thể tải danh sách chi tiết kèo của nhóm", "error");
    } finally {
      setSignalsLoading(false);
    }
  };

  // Filtered channels list - Strictly Elite Top 5 Only
  const filteredChannels = channels
    .filter((ch) => ELITE_TOP5_CHAT_IDS.includes(Number(ch.chat_id)))
    .filter((ch) => {
      const matchesSearch =
        ch.channel_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        ch.chat_id.toString().includes(searchQuery);
      const matchesTier = selectedTier === "ALL" || ch.tier === selectedTier;
      return matchesSearch && matchesTier;
    });

  return (
    <div className="page-content" style={{ padding: "24px", maxWidth: "1600px", margin: "0 auto" }}>
      {/* Top Title & Control Bar */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "24px", flexWrap: "wrap", gap: "16px" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "6px" }}>
            <div style={{ padding: "8px", background: "rgba(234, 179, 8, 0.15)", borderRadius: "8px", color: "#eab308" }}>
              <Trophy size={26} />
            </div>
            <div>
              <h1 style={{ fontSize: "24px", fontWeight: "bold", margin: 0, color: "#fff" }}>
                Bảng Xếp Hạng & Đánh Giá Nhóm Telegram
              </h1>
              <div style={{ fontSize: "13px", color: "var(--text-muted)", marginTop: "2px" }}>
                Đánh giá chuyên sâu các nhóm tín hiệu Telegram: Tỉ lệ thắng thực tế (Backtest 6 tháng Binance), tần suất lệnh, và cảnh báo nhóm sai/scam.
              </div>

            </div>
          </div>
        </div>

        {/* Global Controls: Capital Mode, Timeframe & Refresh */}
        <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
          {/* Capital Simulation Mode Selector */}
          <div style={{ display: "flex", background: "var(--bg-card)", padding: "4px", borderRadius: "8px", border: "1px solid var(--border-color)", gap: "4px" }}>
            {[
              { key: "real", label: `💎 Vốn thật Binance ($${realEquitySafe})` },
              { key: "1000", label: "Mô phỏng $1,000" },
              { key: "5000", label: "Mô phỏng $5,000" },
            ].map((c) => (
              <button
                key={c.key}
                onClick={() => setCapitalMode(c.key as any)}
                style={{
                  padding: "6px 12px",
                  fontSize: "12px",
                  fontWeight: 600,
                  borderRadius: "6px",
                  border: "none",
                  cursor: "pointer",
                  background: capitalMode === c.key ? "rgba(16, 185, 129, 0.2)" : "transparent",
                  color: capitalMode === c.key ? "#10b981" : "var(--text-muted)",
                  outline: capitalMode === c.key ? "1px solid #10b981" : "none",
                  transition: "all 0.2s",
                }}
              >
                {c.label}
              </button>
            ))}
          </div>

          {/* Timeframe Tabs */}
          <div style={{ display: "flex", background: "var(--bg-card)", padding: "4px", borderRadius: "8px", border: "1px solid var(--border-color)" }}>
            {[
              { key: "all", label: "Toàn bộ (90 ngày)" },
              { key: "month", label: "30 ngày (Tháng)" },
              { key: "week", label: "7 ngày (Tuần)" },
              { key: "day", label: "24h (Hôm nay)" },
            ].map((t) => (
              <button
                key={t.key}
                onClick={() => setTimeframe(t.key)}
                style={{
                  padding: "6px 14px",
                  fontSize: "12px",
                  fontWeight: 600,
                  borderRadius: "6px",
                  border: "none",
                  cursor: "pointer",
                  background: timeframe === t.key ? "var(--primary-color, #2563eb)" : "transparent",
                  color: timeframe === t.key ? "#fff" : "var(--text-muted)",
                  transition: "all 0.2s",
                }}
              >
                {t.label}
              </button>
            ))}
          </div>

          <button
            onClick={fetchLeaderboard}
            disabled={loading}
            className="btn btn-secondary"
            style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", padding: "8px 14px" }}
          >
            <RefreshCw size={14} className={loading ? "spin" : ""} />
            <span>Làm mới</span>
          </button>
        </div>
      </div>

      {/* 4 Commercial KPI Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "16px", marginBottom: "24px" }}>
        {/* Card 1: Best Channel */}
        <div className="card" style={{ padding: "18px", borderLeft: "4px solid #10b981", background: "var(--bg-card)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
            <span style={{ fontSize: "12px", fontWeight: 600, textTransform: "uppercase", color: "var(--text-muted)", letterSpacing: "0.5px" }}>
              🏆 Nhóm Tốt Nhất (Top 1)
            </span>
            <span className="badge badge-success" style={{ fontSize: "11px", fontWeight: 700 }}>TIER S</span>
          </div>
          <div style={{ fontSize: "18px", fontWeight: "bold", color: "#fff", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {summary?.best_channel_name || "Đang tính toán..."}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "12px", marginTop: "8px", fontSize: "13px" }}>
            <span style={{ color: "#10b981", fontWeight: 700 }}>
              Winrate: {summary?.best_channel_winrate ?? 0}%
            </span>
            <span style={{ color: "var(--text-muted)" }}>•</span>
            <span style={{ color: (summary?.best_channel_pnl ?? 0) >= 0 ? "#10b981" : "#ef4444", fontWeight: 700 }}>
              PnL: {(summary?.best_channel_pnl ?? 0) >= 0 ? "+" : ""}${summary?.best_channel_pnl?.toFixed(2) ?? "0.00"}
            </span>
          </div>
        </div>

        {/* Card 2: Highest Risk / Worst */}
        <div className="card" style={{ padding: "18px", borderLeft: "4px solid #ef4444", background: "var(--bg-card)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
            <span style={{ fontSize: "12px", fontWeight: 600, textTransform: "uppercase", color: "var(--text-muted)", letterSpacing: "0.5px" }}>
              ⚠️ Nhóm Cần Lưu Ý (Trong {summary?.total_channels || summary?.total_pinned_channels || 18} Nhóm)
            </span>
            <span className="badge badge-error" style={{ fontSize: "11px", fontWeight: 700 }}>CẢNH BÁO</span>
          </div>
          <div style={{ fontSize: "18px", fontWeight: "bold", color: "#fff", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {summary?.worst_channel_name || "Đang tính toán..."}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "8px", fontSize: "13px", color: "#ef4444" }}>
            <ShieldAlert size={14} />
            <span>Tỉ lệ tin từ chối / chưa đạt: <strong>{summary?.worst_channel_rejection_rate ?? 0}%</strong></span>
          </div>
        </div>

        {/* Card 3: Total Signal Velocity */}
        <div className="card" style={{ padding: "18px", borderLeft: "4px solid #3b82f6", background: "var(--bg-card)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
            <span style={{ fontSize: "12px", fontWeight: 600, textTransform: "uppercase", color: "var(--text-muted)", letterSpacing: "0.5px" }}>
              📊 Tần Suất Kèo Đã Lọc
            </span>
            <span className="badge badge-info" style={{ fontSize: "11px" }}>{summary?.active_trading_channels ?? 0} Kênh Hoạt Động</span>
          </div>
          <div style={{ fontSize: "22px", fontWeight: "bold", color: "#fff" }}>
            {summary?.total_signals_validated?.toLocaleString() ?? 0} <span style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-muted)" }}>tín hiệu chuẩn</span>
          </div>
          <div style={{ fontSize: "13px", color: "var(--text-muted)", marginTop: "6px" }}>
            Độ chính xác toàn thị trường: <strong style={{ color: "#3b82f6" }}>{summary?.overall_win_rate_pct ?? 0}% Winrate</strong>
          </div>
        </div>

        {/* Card 4: Simulated Net PnL */}
        <div className="card" style={{ padding: "18px", borderLeft: "4px solid #8b5cf6", background: "var(--bg-card)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
            <span style={{ fontSize: "12px", fontWeight: 600, textTransform: "uppercase", color: "var(--text-muted)", letterSpacing: "0.5px" }}>
              💰 Lợi Nhuận Giả Định {capitalMode === "real" ? `(Vốn thật $${realEquitySafe})` : `(Vốn $${effectiveBankroll.toLocaleString()})`}
            </span>
            <span className="badge" style={{ background: "rgba(139, 92, 246, 0.2)", color: "#a78bfa", fontSize: "11px" }}>
              ROI: +{(((summary?.total_net_pnl_usd ?? 0) / effectiveBankroll) * 100).toFixed(1)}%
            </span>
          </div>
          <div style={{ fontSize: "22px", fontWeight: "bold", color: (summary?.total_net_pnl_usd ?? 0) >= 0 ? "#10b981" : "#ef4444" }}>
            {(summary?.total_net_pnl_usd ?? 0) >= 0 ? "+" : ""}${summary?.total_net_pnl_usd?.toFixed(2) ?? "0.00"}
          </div>
          <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "6px" }}>
            Ký quỹ: {marginPct}% (~${(effectiveBankroll * (marginPct / 100)).toFixed(2)}/lệnh) • Crossed • Tối đa 5x
          </div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="card" style={{ padding: "14px 18px", marginBottom: "16px", background: "var(--bg-card)", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px", flex: 1, minWidth: "260px" }}>
          <div style={{ position: "relative", width: "100%", maxWidth: "340px" }}>
            <Search size={16} style={{ position: "absolute", left: "10px", top: "50%", transform: "translateY(-50%)", color: "var(--text-muted)" }} />
            <input
              type="text"
              placeholder="Tìm kiếm nhóm Telegram..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="input-field"
              style={{ paddingLeft: "34px", width: "100%", fontSize: "13px" }}
            />
          </div>

          {/* Tier Filter Buttons */}
          <div style={{ display: "flex", gap: "6px" }}>
            {["ALL", "S", "A", "B", "C", "D", "BLOCKED"].map((tier) => (
              <button
                key={tier}
                onClick={() => setSelectedTier(tier)}
                style={{
                  padding: "4px 10px",
                  fontSize: "12px",
                  fontWeight: 600,
                  borderRadius: "6px",
                  border: "1px solid var(--border-color)",
                  cursor: "pointer",
                  background: selectedTier === tier ? "var(--border-color)" : "transparent",
                  color: selectedTier === tier ? "#fff" : "var(--text-muted)",
                }}
              >
                {tier === "ALL" ? "Tất cả Tier" : tier === "BLOCKED" ? "Bị chặn" : `Tier ${tier}`}
              </button>
            ))}
          </div>
        </div>

        <div style={{ fontSize: "13px", color: "var(--text-muted)" }}>
          Hiển thị <strong>{filteredChannels.length}</strong> / {channels.length} nhóm tín hiệu
        </div>

      </div>

      {/* Main Leaderboard Table */}
      <div className="card" style={{ padding: 0, overflow: "hidden", background: "var(--bg-card)" }}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "13px" }}>
            <thead>
              <tr style={{ background: "rgba(255, 255, 255, 0.03)", borderBottom: "1px solid var(--border-color)", color: "var(--text-muted)", fontSize: "12px", textTransform: "uppercase" }}>
                <th style={{ padding: "14px 16px", width: "60px" }}>Hạng</th>
                <th style={{ padding: "14px 16px" }}>Tên Nhóm Telegram</th>
                <th style={{ padding: "14px 16px", textAlign: "center", width: "90px" }}>Phân Hạng</th>
                <th style={{ padding: "14px 16px", textAlign: "center" }}>Chất Lượng Kèo</th>
                <th style={{ padding: "14px 16px", textAlign: "center" }}>Tần Suất (Ngày/Tuần/Tháng)</th>
                <th style={{ padding: "14px 16px", width: "180px" }}>Tỉ Lệ Thắng (Winrate)</th>
                <th style={{ padding: "14px 16px", textAlign: "right" }}>Lợi Nhuận (PnL $)</th>
                <th style={{ padding: "14px 16px", textAlign: "center" }}>Đánh Giá Khuyến Nghị</th>
                <th style={{ padding: "14px 16px", textAlign: "center", width: "90px" }}>Chi Tiết</th>
              </tr>
            </thead>
            <tbody>
              {filteredChannels.map((ch) => {
                const isProfitable = ch.performance.net_pnl_usd >= 0;
                const winRate = ch.performance.win_rate_pct;

                // Rank badge styling
                let rankBadge = (
                  <span style={{ fontWeight: 700, color: "var(--text-muted)", fontSize: "14px" }}>
                    #{ch.rank}
                  </span>
                );
                if (ch.rank === 1) {
                  rankBadge = <span style={{ background: "#eab308", color: "#000", fontWeight: 800, padding: "3px 8px", borderRadius: "12px", fontSize: "11px" }}>🥇 #1</span>;
                } else if (ch.rank === 2) {
                  rankBadge = <span style={{ background: "#94a3b8", color: "#000", fontWeight: 800, padding: "3px 8px", borderRadius: "12px", fontSize: "11px" }}>🥈 #2</span>;
                } else if (ch.rank === 3) {
                  rankBadge = <span style={{ background: "#b45309", color: "#fff", fontWeight: 800, padding: "3px 8px", borderRadius: "12px", fontSize: "11px" }}>🥉 #3</span>;
                }

                // Tier badge color
                const tierStyles: Record<string, { bg: string; color: string; border: string }> = {
                  S: { bg: "rgba(16, 185, 129, 0.15)", color: "#10b981", border: "#10b981" },
                  A: { bg: "rgba(59, 130, 246, 0.15)", color: "#3b82f6", border: "#3b82f6" },
                  B: { bg: "rgba(234, 179, 8, 0.15)", color: "#eab308", border: "#eab308" },
                  C: { bg: "rgba(249, 115, 22, 0.15)", color: "#f97316", border: "#f97316" },
                  D: { bg: "rgba(239, 68, 68, 0.15)", color: "#ef4444", border: "#ef4444" },
                  BLOCKED: { bg: "rgba(239, 68, 68, 0.25)", color: "#ef4444", border: "#ef4444" },
                };
                const tStyle = tierStyles[ch.tier] || tierStyles.D;
                const isBlocked = ch.is_blacklisted || ch.tier === "BLOCKED";

                return (
                  <tr
                    key={ch.chat_id}
                    style={{
                      borderBottom: "1px solid var(--border-color)",
                      transition: "background 0.15s",
                      opacity: isBlocked ? 0.65 : 1.0,
                    }}
                    className="table-row-hover"
                  >
                    {/* Rank */}
                    <td style={{ padding: "14px 16px" }}>{rankBadge}</td>

                    {/* Name */}
                    <td style={{ padding: "14px 16px" }}>
                      <div style={{ fontWeight: 600, color: isBlocked ? "#ef4444" : "#fff", fontSize: "14px", display: "flex", alignItems: "center", gap: "6px" }}>
                        <span>{ch.channel_name}</span>
                        {ch.tier === "S" && <Flame size={14} color="#f59e0b" />}
                        {isBlocked && (
                          <span style={{
                            background: "#ef4444",
                            color: "#fff",
                            fontSize: "10px",
                            fontWeight: 800,
                            padding: "2px 6px",
                            borderRadius: "4px",
                            textTransform: "uppercase",
                            letterSpacing: "0.5px"
                          }}>
                            [ĐÃ TẮT / CHẶN]
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                        ID: {ch.chat_id} • Tổng: {ch.total_messages.toLocaleString()} tin nhắn
                      </div>
                    </td>

                    {/* Tier */}
                    <td style={{ padding: "14px 16px", textAlign: "center" }}>
                      <span
                        style={{
                          display: "inline-block",
                          padding: "3px 10px",
                          borderRadius: "6px",
                          fontSize: "12px",
                          fontWeight: 800,
                          background: tStyle.bg,
                          color: tStyle.color,
                          border: `1px solid ${tStyle.border}`,
                        }}
                      >
                        {ch.tier === "BLOCKED" ? "CHẶN" : `Tier ${ch.tier}`}
                      </span>
                    </td>

                    {/* Quality */}
                    <td style={{ padding: "14px 16px", textAlign: "center" }}>
                      <div style={{ fontWeight: 600, color: ch.quality_rate_pct >= 60 ? "#10b981" : ch.quality_rate_pct > 0 ? "#f59e0b" : "#ef4444" }}>
                        {ch.validated_signals} / {ch.total_signals} ({ch.quality_rate_pct}%)
                      </div>
                      <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                        {ch.rejected_signals} bị chặn (thiếu SL/scam)
                      </div>
                    </td>

                    {/* Frequency */}
                    <td style={{ padding: "14px 16px", textAlign: "center" }}>
                      <div style={{ fontWeight: 600, color: "#fff" }}>
                        {ch.frequencies.per_day} <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>kèo/ngày</span>
                      </div>
                      <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                        ~{ch.frequencies.per_week} kèo/tuần • ~{ch.frequencies.per_month} kèo/tháng
                      </div>
                    </td>

                    {/* Winrate */}
                    <td style={{ padding: "14px 16px" }}>
                      {ch.validated_signals > 0 ? (
                        <div>
                          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px", fontSize: "12px" }}>
                            <span style={{ fontWeight: 700, color: winRate >= 65 ? "#10b981" : winRate >= 50 ? "#eab308" : "#ef4444" }}>
                              {winRate}% Thắng
                            </span>
                            <span style={{ color: "var(--text-muted)", fontSize: "11px" }}>
                              {ch.performance.win_trades}W - {ch.performance.loss_trades}L
                            </span>
                          </div>
                          {/* Progress bar */}
                          <div style={{ width: "100%", height: "6px", background: "rgba(255, 255, 255, 0.1)", borderRadius: "3px", overflow: "hidden", display: "flex" }}>
                            <div style={{ width: `${winRate}%`, background: winRate >= 65 ? "#10b981" : winRate >= 50 ? "#eab308" : "#ef4444" }} />
                            <div style={{ width: `${100 - winRate}%`, background: "rgba(239, 68, 68, 0.3)" }} />
                          </div>
                        </div>
                      ) : (
                        <span style={{ color: "var(--text-muted)", fontSize: "12px" }}>Chưa có lệnh hợp lệ</span>
                      )}
                    </td>

                    {/* PnL $ */}
                    <td style={{ padding: "14px 16px", textAlign: "right" }}>
                      {ch.validated_signals > 0 ? (
                        <div>
                          <div style={{ fontWeight: 700, fontSize: "14px", color: isProfitable ? "#10b981" : "#ef4444" }}>
                            {isProfitable ? "+" : ""}${ch.performance.net_pnl_usd.toFixed(2)}
                          </div>
                          <div style={{ fontSize: "11px", color: isProfitable ? "#10b981" : "#ef4444" }}>
                            ROI: {isProfitable ? "+" : ""}{ch.performance.roi_pct.toFixed(1)}% • PF: {ch.performance.profit_factor}
                          </div>
                        </div>
                      ) : (
                        <span style={{ color: "var(--text-muted)", fontSize: "12px" }}>$0.00</span>
                      )}
                    </td>

                    {/* Verdict */}
                    <td style={{ padding: "14px 16px", textAlign: "center" }}>
                      <span
                        style={{
                          display: "inline-block",
                          padding: "4px 10px",
                          borderRadius: "12px",
                          fontSize: "11px",
                          fontWeight: 600,
                          background: tStyle.bg,
                          color: tStyle.color,
                        }}
                      >
                        {ch.verdict}
                      </span>
                    </td>

                    {/* Action Detail */}
                    <td style={{ padding: "14px 16px", textAlign: "center" }}>
                      <button
                        onClick={() => handleOpenDetail(ch)}
                        className="btn btn-secondary"
                        style={{ padding: "5px 10px", fontSize: "12px", display: "inline-flex", alignItems: "center", gap: "4px" }}
                        title="Xem lịch sử kèo của nhóm này"
                      >
                        <Eye size={13} />
                        <span>Xem</span>
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Signal Detail Modal */}
      {detailModalOpen && selectedChannel && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0, 0, 0, 0.75)",
            backdropFilter: "blur(4px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
            padding: "20px",
          }}
        >
          <div
            className="card"
            style={{
              width: "100%",
              maxWidth: "1100px",
              maxHeight: "85vh",
              display: "flex",
              flexDirection: "column",
              background: "#131722",
              border: "1px solid var(--border-color)",
              padding: 0,
              overflow: "hidden",
            }}
          >
            {/* Modal Header */}
            <div
              style={{
                padding: "18px 24px",
                borderBottom: "1px solid var(--border-color)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                background: "rgba(255, 255, 255, 0.02)",
              }}
            >
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                  <h2 style={{ fontSize: "18px", fontWeight: "bold", margin: 0, color: "#fff" }}>
                    Lịch Sử Tín Hiệu: {selectedChannel.channel_name}
                  </h2>
                  <span className="badge" style={{ background: "rgba(59, 130, 246, 0.2)", color: "#60a5fa" }}>
                    Tier {selectedChannel.tier}
                  </span>
                </div>
                <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "4px" }}>
                  Chat ID: {selectedChannel.chat_id} • Winrate: <strong>{selectedChannel.performance.win_rate_pct}%</strong> • PnL mô phỏng: <strong style={{ color: selectedChannel.performance.net_pnl_usd >= 0 ? "#10b981" : "#ef4444" }}>{selectedChannel.performance.net_pnl_usd >= 0 ? "+" : ""}${selectedChannel.performance.net_pnl_usd.toFixed(2)}</strong>
                </div>
              </div>
              <button
                onClick={() => setDetailModalOpen(false)}
                style={{ background: "transparent", border: "none", color: "var(--text-muted)", cursor: "pointer", padding: "4px" }}
              >
                <X size={20} />
              </button>
            </div>

            {/* Modal Content */}
            <div style={{ padding: "20px 24px", overflowY: "auto", flex: 1 }}>
              {signalsLoading ? (
                <div style={{ textAlign: "center", padding: "40px", color: "var(--text-muted)" }}>
                  <RefreshCw size={24} className="spin" style={{ margin: "0 auto 12px" }} />
                  <div>Đang tải danh sách tín hiệu...</div>
                </div>
              ) : channelSignals.length === 0 ? (
                <div style={{ textAlign: "center", padding: "40px", color: "var(--text-muted)" }}>
                  Không tìm thấy tín hiệu nào của nhóm này trong hệ thống.
                </div>
              ) : (
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--border-color)", color: "var(--text-muted)", textAlign: "left" }}>
                      <th style={{ padding: "10px" }}>Thời gian</th>
                      <th style={{ padding: "10px" }}>Coin / Cặp</th>
                      <th style={{ padding: "10px" }}>Hướng Lệnh</th>
                      <th style={{ padding: "10px" }}>Entry</th>
                      <th style={{ padding: "10px" }}>Stop Loss</th>
                      <th style={{ padding: "10px" }}>Take Profits</th>
                      <th style={{ padding: "10px" }}>Đòn bẩy</th>
                      <th style={{ padding: "10px" }}>Trạng thái</th>
                    </tr>
                  </thead>
                  <tbody>
                    {channelSignals.map((sig) => {
                      const isShort = sig.side === "SHORT";
                      return (
                        <tr key={sig.signal_id} style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.05)" }}>
                          <td style={{ padding: "10px", color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                            {sig.telegram_timestamp ? formatDateTime(sig.telegram_timestamp) : "N/A"}
                          </td>
                          <td style={{ padding: "10px", fontWeight: 700, color: "#fff" }}>
                            {sig.symbol || "UNKNOWN"}
                          </td>
                          <td style={{ padding: "10px" }}>
                            <span
                              style={{
                                padding: "2px 8px",
                                borderRadius: "4px",
                                fontWeight: 700,
                                fontSize: "11px",
                                background: isShort ? "rgba(239, 68, 68, 0.15)" : "rgba(16, 185, 129, 0.15)",
                                color: isShort ? "#ef4444" : "#10b981",
                              }}
                            >
                              {sig.side || "N/A"}
                            </span>
                          </td>
                          <td style={{ padding: "10px", fontFamily: "monospace" }}>
                            {sig.entries_json ? JSON.parse(sig.entries_json).join(", ") : "-"}
                          </td>
                          <td style={{ padding: "10px", fontFamily: "monospace", color: "#ef4444" }}>
                            {sig.stop_loss || "-"}
                          </td>
                          <td style={{ padding: "10px", fontFamily: "monospace", color: "#10b981" }}>
                            {sig.take_profits_json ? JSON.parse(sig.take_profits_json).join(", ") : "-"}
                          </td>
                          <td style={{ padding: "10px" }}>
                            {sig.leverage ? `${sig.leverage}x` : "-"}
                          </td>
                          <td style={{ padding: "10px" }}>
                            <span
                              className={`badge ${
                                sig.state === "VALIDATED"
                                  ? "badge-success"
                                  : sig.state === "NEEDS_REVIEW"
                                  ? "badge-warning"
                                  : "badge-error"
                              }`}
                              style={{ fontSize: "10px" }}
                            >
                              {sig.state}
                            </span>
                            {sig.blocking_reason && (
                              <div style={{ fontSize: "10px", color: "var(--text-muted)", marginTop: "2px", maxWidth: "200px" }}>
                                {sig.blocking_reason}
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>

            {/* Modal Footer */}
            <div
              style={{
                padding: "14px 24px",
                borderTop: "1px solid var(--border-color)",
                display: "flex",
                justifyContent: "flex-end",
                background: "rgba(255, 255, 255, 0.02)",
              }}
            >
              <button onClick={() => setDetailModalOpen(false)} className="btn btn-secondary" style={{ padding: "6px 16px" }}>
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
