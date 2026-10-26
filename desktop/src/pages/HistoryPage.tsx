import React, { useState, useEffect, useRef } from "react";
import { Calendar, RefreshCw } from "lucide-react";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";
import { PnLChart } from "../components/PnLChart";
import type { PnLSummary, TradeRecord } from "../types/api";

const toFiniteNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const formatPnl = (value: number | null): string => {
  if (value === null) return "Chưa có dữ liệu";
  return `${value >= 0 ? "+$" : "-$"}${Math.abs(value).toFixed(2)}`;
};

export const HistoryPage: React.FC = () => {
  const { addToast } = useApp();
  const [daysBack, setDaysBack] = useState<number>(6);
  const [pnlData, setPnlData] = useState<PnLSummary | null>(null);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [selectedChannel, setSelectedChannel] = useState<string>("ALL");
  const [filterType, setFilterType] = useState<"ALL" | "CLOSE_ONLY" | "ENTRY_ONLY">("ALL");
  const [loading, setLoading] = useState(false);
  const requestId = useRef(0);

  const fetchHistory = async () => {
    const currentRequestId = ++requestId.current;
    setLoading(true);
    try {
      const [pnl, tradeList] = await Promise.all([
        api.getPnL(daysBack),
        api.getTradeHistory(100, daysBack),
      ]);
      if (currentRequestId !== requestId.current) return;
      setPnlData(pnl);
      setTrades(tradeList || []);
    } catch (err: any) {
      if (currentRequestId === requestId.current) addToast("Lỗi tải lịch sử giao dịch.", "error");
    } finally {
      if (currentRequestId === requestId.current) setLoading(false);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, [daysBack]);

  const realizedPnl = toFiniteNumber(pnlData?.realized_pnl);
  const commission = toFiniteNumber(pnlData?.commission);
  const funding = toFiniteNumber(pnlData?.funding_fee);
  const netPnl = toFiniteNumber(pnlData?.net_pnl);
  const effectiveRealizedPnl = realizedPnl ?? 0;
  const commVal = commission ?? 0;
  const fundingVal = funding ?? 0;
  const netPnlVal = netPnl ?? (realizedPnl === null ? null : effectiveRealizedPnl - commVal + fundingVal);

  const tradePnls = trades.map((trade) => toFiniteNumber(trade.realized_pnl));
  const closedFills = tradePnls.filter((pnl): pnl is number => pnl !== null && pnl !== 0);
  const winFills = closedFills.filter((pnl) => pnl > 0);
  const effectiveClosedCount = pnlData?.has_data
    ? pnlData.total_closed_trades
    : closedFills.length;
  const effectiveWinRate = pnlData?.has_data
    ? pnlData.win_rate_pct
    : (closedFills.length > 0 ? Math.round((winFills.length / closedFills.length) * 1000) / 10 : 0);

  const uniqueChannels = Array.from(new Set(trades.map((tr) => tr.channel_name || "Thủ công / Khác")));
  const filteredTrades = trades.filter((tr) => {
    const channelMatch = selectedChannel === "ALL" || (tr.channel_name || "Thủ công / Khác") === selectedChannel;
    const pnl = toFiniteNumber(tr.realized_pnl) || 0;
    if (filterType === "CLOSE_ONLY") return channelMatch && pnl !== 0;
    if (filterType === "ENTRY_ONLY") return channelMatch && pnl === 0;
    return channelMatch;
  });

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
        <div>
          <h2 style={{ fontSize: "20px", fontWeight: 700, color: "#fff" }}>Lịch Sử Khớp Lệnh & Giao Dịch</h2>
          <p style={{ color: "var(--text-secondary)", fontSize: "13px" }}>
            Hồ sơ lệnh đã khớp trên sàn Binance Futures và kết quả lãi/lỗ của các vị thế.
          </p>
        </div>

        <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
          <button className="btn btn-secondary btn-sm" onClick={fetchHistory} disabled={loading}>
            <RefreshCw size={13} className={loading ? "spin" : ""} />
            <span>{loading ? "Đang tải..." : "Làm mới"}</span>
          </button>
          <Calendar size={14} className="text-muted" />
          <select
            className="form-input"
            style={{ width: "auto" }}
            value={daysBack}
            onChange={(e) => setDaysBack(parseInt(e.target.value))}
          >
            <option value={0}>Hôm nay</option>
            <option value={6}>7 ngày qua</option>
            <option value={29}>30 ngày qua</option>
          </select>
        </div>
      </div>

      {/* Visual PnL Chart (Daily / Weekly / Monthly & Bar / Line) */}
      <PnLChart />

      {/* Summary KPI Cards for the period */}
      <div className="card-grid">
        <div className="card">
          <div className="card-title">Realized PnL ({daysBack === 0 ? "Hôm nay" : `${daysBack + 1} ngày`})</div>
          <div className={`card-value ${realizedPnl === null ? "text-muted" : realizedPnl >= 0 ? "text-success" : "text-danger"}`}>
            {formatPnl(realizedPnl)}
          </div>
          <div className="card-subtitle">Chưa trừ phí hoa hồng & funding</div>
        </div>

        <div className="card">
          <div className="card-title">Net PnL (Lãi Ròng Thực Nhận)</div>
          <div className={`card-value ${netPnlVal === null ? "text-muted" : netPnlVal >= 0 ? "text-success" : "text-danger"}`}>
            {netPnlVal === null ? "Chưa có dữ liệu" : formatPnl(netPnlVal)}
          </div>
          <div className="card-subtitle">
            Phí sàn: -${commVal.toFixed(2)} | Funding: {fundingVal >= 0 ? `+$${fundingVal.toFixed(2)}` : `-$${Math.abs(fundingVal).toFixed(2)}`}
          </div>
        </div>

        <div className="card">
          <div className="card-title">Vị thế Đã Đóng & Khớp Sàn</div>
          <div className="card-value">{effectiveClosedCount} <span style={{ fontSize: "14px", fontWeight: 400, color: "var(--text-muted)" }}>vị thế đã đóng</span></div>
          <div className="card-subtitle">{trades.length} lượt khớp lệnh sàn gần nhất</div>
        </div>

        <div className="card">
          <div className="card-title">Tỷ lệ thắng (Win Rate)</div>
          <div className={`card-value ${effectiveWinRate >= 50 ? "text-success" : "text-danger"}`}>
            {effectiveWinRate}%
          </div>
          <div className="card-subtitle">
            Thắng {pnlData?.win_count ?? winFills.length} / {effectiveClosedCount} vị thế đã đóng
          </div>
        </div>
      </div>

      {/* Trade Execution Fills Table */}
      <div className="table-container" style={{ marginBottom: "24px" }}>
        <div className="table-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div className="table-title">Lịch Sử Khớp Lệnh Sàn Binance Futures ({filteredTrades.length} / {trades.length})</div>
          <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
            <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>Lọc lệnh:</span>
            <select
              className="form-input"
              style={{ width: "auto", padding: "4px 10px", fontSize: "12px" }}
              value={filterType}
              onChange={(e) => setFilterType(e.target.value as any)}
            >
              <option value="ALL">Tất cả ({trades.length})</option>
              <option value="CLOSE_ONLY">🟢 Đóng lệnh / Chốt PnL ({trades.filter(t => (toFiniteNumber(t.realized_pnl) || 0) !== 0).length})</option>
              <option value="ENTRY_ONLY">🔵 Mở vị thế ({trades.filter(t => (toFiniteNumber(t.realized_pnl) || 0) === 0).length})</option>
            </select>

            <span style={{ fontSize: "12px", color: "var(--text-muted)", marginLeft: "4px" }}>Nhóm:</span>
            <select
              className="form-input"
              style={{ width: "auto", padding: "4px 10px", fontSize: "12px" }}
              value={selectedChannel}
              onChange={(e) => setSelectedChannel(e.target.value)}
            >
              <option value="ALL">Tất cả Nhóm ({trades.length})</option>
              {uniqueChannels.map((ch) => (
                <option key={ch} value={ch}>
                  {ch} ({trades.filter((t) => (t.channel_name || "Thủ công / Khác") === ch).length})
                </option>
              ))}
            </select>
          </div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Thời gian khớp</th>
              <th>Mã lệnh sàn (ID)</th>
              <th>Nhóm Nguồn</th>
              <th>Cặp giao dịch</th>
              <th>Phân loại</th>
              <th>Chiều</th>
              <th>Giá khớp</th>
              <th>Khối lượng</th>
              <th>Phí sàn (Fee)</th>
              <th>PnL Đã chốt</th>
            </tr>
          </thead>
          <tbody>
            {filteredTrades.length === 0 ? (
              <tr>
                <td colSpan={10} style={{ textAlign: "center", color: "var(--text-muted)", padding: "32px" }}>
                  {loading ? "Đang truy vấn lịch sử khớp lệnh từ Binance..." : "Không có giao dịch khớp lệnh nào phù hợp bộ lọc."}
                </td>
              </tr>
            ) : (
              filteredTrades.map((tr) => (
                <tr key={tr.id}>
                  <td className="mono" style={{ fontSize: "12px" }}>{tr.time}</td>
                  <td className="mono" style={{ fontSize: "12px", color: "var(--text-muted)" }}>{tr.id}</td>
                  <td>
                    <span
                      className={`badge ${
                        tr.channel_name && tr.channel_name.includes("LEOPARD")
                          ? "badge-success"
                          : tr.channel_name && tr.channel_name.includes("Boom")
                          ? "badge-info"
                          : tr.channel_name && tr.channel_name.includes("WOLF")
                          ? "badge-live"
                          : "badge-read-only"
                      }`}
                      style={{ fontSize: "11px" }}
                    >
                      {tr.channel_name || "Thủ công / Khác"}
                    </span>
                  </td>
                  <td className="mono" style={{ fontWeight: 700, color: "#fff" }}>{tr.symbol}</td>
                  <td>
                    {toFiniteNumber(tr.realized_pnl) !== null && toFiniteNumber(tr.realized_pnl)! !== 0 ? (
                      <span className={`badge ${toFiniteNumber(tr.realized_pnl)! > 0 ? "badge-success" : "badge-live"}`} style={{ fontSize: "11px", fontWeight: 700 }}>
                        {toFiniteNumber(tr.realized_pnl)! > 0 ? "CHỐT LÃI" : "CẮT LỖ"}
                      </span>
                    ) : (
                      <span className="badge badge-info" style={{ fontSize: "11px" }}>
                        MỞ VỊ THẾ
                      </span>
                    )}
                  </td>
                  <td>
                    <span className={`badge ${tr.side.includes("BUY") || tr.side.includes("MUA") ? "badge-read-only" : "badge-live"}`}>
                      {tr.side}
                    </span>
                  </td>
                  <td className="mono" style={{ fontWeight: 600 }}>{tr.price}</td>
                  <td className="mono">{tr.qty}</td>
                  <td className="mono" style={{ fontSize: "12px", color: "var(--text-muted)" }}>{tr.commission}</td>
                  <td className={`mono ${toFiniteNumber(tr.realized_pnl) === null ? "text-muted" : toFiniteNumber(tr.realized_pnl)! > 0 ? "text-success" : toFiniteNumber(tr.realized_pnl)! < 0 ? "text-danger" : "text-muted"}`} style={{ fontWeight: 700 }}>
                    {toFiniteNumber(tr.realized_pnl) === null ? "—" : toFiniteNumber(tr.realized_pnl)! === 0 ? (
                      <span style={{ color: "var(--text-muted)", fontSize: "12px" }}>— (Vị thế mở)</span>
                    ) : (
                      `${toFiniteNumber(tr.realized_pnl)! >= 0 ? "+" : ""}${toFiniteNumber(tr.realized_pnl)!.toFixed(2)} USDT`
                    )}
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
