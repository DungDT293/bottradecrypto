import React, { useState, useEffect } from "react";
import { Calendar, RefreshCw } from "lucide-react";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";

export const HistoryPage: React.FC = () => {
  const { addToast } = useApp();
  const [daysBack, setDaysBack] = useState<number>(7);
  const [pnlData, setPnlData] = useState<any | null>(null);
  const [trades, setTrades] = useState<any[]>([]);
  const [selectedChannel, setSelectedChannel] = useState<string>("ALL");
  const [loading, setLoading] = useState(false);

  const fetchHistory = async () => {
    setLoading(true);
    try {
      const [pnl, tradeList] = await Promise.all([
        api.getPnL(daysBack),
        api.getTradeHistory(100),
      ]);
      setPnlData(pnl);
      setTrades(tradeList || []);
    } catch (err: any) {
      addToast("Lỗi tải lịch sử giao dịch.", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, [daysBack]);

  const tradesPnl = trades.reduce((acc, tr) => acc + (parseFloat(tr.realized_pnl) || 0), 0);
  const pnlFromApi = parseFloat(pnlData?.realized_pnl || "0");
  const effectiveRealizedPnl = pnlFromApi !== 0 ? pnlFromApi : tradesPnl;
  const commVal = parseFloat(pnlData?.commission || "0");
  const fundingVal = parseFloat(pnlData?.funding_fee || "0");
  const netPnlVal = pnlData?.net_pnl != null ? parseFloat(pnlData.net_pnl) : (effectiveRealizedPnl - commVal + fundingVal);

  const closedFills = trades.filter((tr) => (parseFloat(tr.realized_pnl) || 0) !== 0);
  const winFills = trades.filter((tr) => (parseFloat(tr.realized_pnl) || 0) > 0);
  const effectiveClosedCount = (pnlData?.total_closed_trades && pnlData.total_closed_trades > 0)
    ? pnlData.total_closed_trades
    : closedFills.length;
  const effectiveWinRate = (pnlData && pnlData.win_rate_pct > 0)
    ? pnlData.win_rate_pct
    : (closedFills.length > 0 ? Math.round((winFills.length / closedFills.length) * 1000) / 10 : 0);

  const uniqueChannels = Array.from(new Set(trades.map((tr) => tr.channel_name || "Thủ công / Khác")));
  const filteredTrades = selectedChannel === "ALL"
    ? trades
    : trades.filter((tr) => (tr.channel_name || "Thủ công / Khác") === selectedChannel);

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

      {/* Summary KPI Cards for the period */}
      <div className="card-grid">
        <div className="card">
          <div className="card-title">Realized PnL ({daysBack === 0 ? "Hôm nay" : `${daysBack + 1} ngày`})</div>
          <div className={`card-value ${effectiveRealizedPnl >= 0 ? "text-success" : "text-danger"}`}>
            {effectiveRealizedPnl >= 0 ? `+$${effectiveRealizedPnl.toFixed(2)}` : `-$${Math.abs(effectiveRealizedPnl).toFixed(2)}`}
          </div>
          <div className="card-subtitle">Chưa trừ phí hoa hồng & funding</div>
        </div>

        <div className="card">
          <div className="card-title">Net PnL (Lãi Ròng Thực Nhận)</div>
          <div className={`card-value ${netPnlVal >= 0 ? "text-success" : "text-danger"}`}>
            {netPnlVal >= 0 ? `+$${netPnlVal.toFixed(2)}` : `-$${Math.abs(netPnlVal).toFixed(2)}`}
          </div>
          <div className="card-subtitle">
            Phí sàn: -${commVal.toFixed(2)} | Funding: {fundingVal >= 0 ? `+$${fundingVal.toFixed(2)}` : `-$${Math.abs(fundingVal).toFixed(2)}`}
          </div>
        </div>

        <div className="card">
          <div className="card-title">Lượt khớp sàn & Vị thế đóng</div>
          <div className="card-value">{trades.length} <span style={{ fontSize: "14px", fontWeight: 400, color: "var(--text-muted)" }}>/ {effectiveClosedCount} đóng</span></div>
          <div className="card-subtitle">Khớp lệnh sàn Binance Futures</div>
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
            <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>Lọc theo Nhóm:</span>
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
                <td colSpan={9} style={{ textAlign: "center", color: "var(--text-muted)", padding: "32px" }}>
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
                    <span className={`badge ${tr.side.includes("BUY") || tr.side.includes("MUA") ? "badge-read-only" : "badge-live"}`}>
                      {tr.side}
                    </span>
                  </td>
                  <td className="mono" style={{ fontWeight: 600 }}>{tr.price}</td>
                  <td className="mono">{tr.qty}</td>
                  <td className="mono" style={{ fontSize: "12px", color: "var(--text-muted)" }}>{tr.commission}</td>
                  <td className={`mono ${tr.realized_pnl > 0 ? "text-success" : tr.realized_pnl < 0 ? "text-danger" : "text-muted"}`} style={{ fontWeight: 700 }}>
                    {tr.realized_pnl > 0 ? `+${tr.realized_pnl.toFixed(2)}` : tr.realized_pnl < 0 ? tr.realized_pnl.toFixed(2) : "0.00"} USDT
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
