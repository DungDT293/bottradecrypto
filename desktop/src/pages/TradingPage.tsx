import React, { useState, useEffect } from "react";
import { AlertOctagon, XCircle, ShieldCheck, RefreshCw } from "lucide-react";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";
import { ConfirmModal } from "../components/ConfirmModal";
import { AITraderCard } from "../components/AITraderCard";
import type { PositionRecord, OrderRecord } from "../types/api";

export const TradingPage: React.FC = () => {
  const { snapshot, refreshSnapshot, addToast } = useApp();

  const [closingSymbol, setClosingSymbol] = useState<string | null>(null);
  const [showCloseAllModal, setShowCloseAllModal] = useState(false);
  const [loadingAction, setLoadingAction] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [localPositions, setLocalPositions] = useState<PositionRecord[] | null>(null);
  const [localOrders, setLocalOrders] = useState<OrderRecord[] | null>(null);

  const fetchLiveTradingData = async () => {
    setRefreshing(true);
    try {
      await refreshSnapshot();
      const [posList, ordList] = await Promise.all([
        api.getPositions().catch(() => null),
        api.getOrders().catch(() => null),
      ]);
      if (posList) setLocalPositions(posList);
      if (ordList) setLocalOrders(ordList);
    } catch {
      // Ignored
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchLiveTradingData();
    const interval = setInterval(() => {
      fetchLiveTradingData();
    }, 4000);
    return () => clearInterval(interval);
  }, []);

  const positions: PositionRecord[] = localPositions ?? snapshot?.positions ?? [];
  const orders: OrderRecord[] = localOrders ?? snapshot?.orders ?? [];
  const isReadOnly = snapshot?.mode === "READ_ONLY";
  const isTestnet = snapshot?.mode === "TESTNET";

  const handleClosePosition = async () => {
    if (!closingSymbol) return;
    setLoadingAction(true);
    try {
      const res = await api.closePosition(closingSymbol);
      addToast(res.message || `Đã gửi yêu cầu đóng vị thế ${closingSymbol}`, "info");
      await fetchLiveTradingData();
    } catch (err: any) {
      addToast(err?.user_message || err?.message || "Lỗi đóng vị thế.", "error");
    } finally {
      setLoadingAction(false);
      setClosingSymbol(null);
    }
  };

  const handleCloseAllPositions = async () => {
    setLoadingAction(true);
    try {
      const res = await api.closeAllBotPositions();
      addToast(res.message || "Đã gửi yêu cầu đóng tất cả vị thế bot", "info");
      await fetchLiveTradingData();
    } catch (err: any) {
      addToast(err?.user_message || err?.message || "Lỗi đóng toàn bộ vị thế.", "error");
    } finally {
      setLoadingAction(false);
      setShowCloseAllModal(false);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
        <div>
          <h2 style={{ fontSize: "20px", fontWeight: 700, color: "#fff" }}>Đang Giao Dịch</h2>
          <p style={{ color: "var(--text-secondary)", fontSize: "13px" }}>
            Quản lý các vị thế đang mở và lệnh điều kiện (SL/TP) trên Binance USD-M Futures.
          </p>
        </div>

        <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={fetchLiveTradingData}
            disabled={refreshing}
            title="Đồng bộ lại vị thế và lệnh từ sàn Binance"
          >
            <RefreshCw size={13} className={refreshing ? "spin" : ""} />
            <span>{refreshing ? "Đang đồng bộ..." : "Làm mới sàn"}</span>
          </button>

          {positions.length > 0 && (
            <button
              className="btn btn-danger"
              onClick={() => setShowCloseAllModal(true)}
              disabled={loadingAction}
            >
              <AlertOctagon size={16} />
              <span>ĐÓNG TẤT CẢ VỊ THẾ BOT</span>
            </button>
          )}
        </div>
      </div>

      {isReadOnly && (
        <div
          style={{
            background: "rgba(16, 185, 129, 0.1)",
            border: "1px solid rgba(16, 185, 129, 0.3)",
            borderRadius: "8px",
            padding: "12px 16px",
            marginBottom: "20px",
            display: "flex",
            alignItems: "center",
            gap: "12px",
          }}
        >
          <ShieldCheck size={20} className="text-success" />
          <div style={{ fontSize: "13px", color: "var(--text-primary)" }}>
            <strong>Chế độ READ_ONLY đang kích hoạt:</strong> Mọi thao tác đóng vị thế hoặc gửi lệnh sàn thật đều bị khóa an toàn tuyệt đối ở tầng Backend.
          </div>
        </div>
      )}

      {isTestnet && (
        <div
          style={{
            background: "rgba(59, 130, 246, 0.1)",
            border: "1px solid rgba(59, 130, 246, 0.3)",
            borderRadius: "8px",
            padding: "12px 16px",
            marginBottom: "20px",
            display: "flex",
            alignItems: "center",
            gap: "12px",
          }}
        >
          <ShieldCheck size={20} style={{ color: "#3b82f6" }} />
          <div style={{ fontSize: "13px", color: "var(--text-primary)" }}>
            <strong>Chế độ BINANCE TESTNET (Giao Dịch Thử Nghiệm):</strong> Các vị thế đang mở và lệnh chờ được kết nối, đồng bộ trực tiếp từ tài khoản sàn Binance USD-M Futures Testnet.
          </div>
        </div>
      )}

      {positions.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
            gap: "12px",
            marginBottom: "20px",
          }}
        >
          <div
            style={{
              background: "rgba(30, 41, 59, 0.7)",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              borderRadius: "8px",
              padding: "12px 16px",
            }}
          >
            <div style={{ fontSize: "11px", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>
              Tổng PnL Chưa Chốt (Net UPnL)
            </div>
            {(() => {
              const totalUnpnl = positions.reduce((acc, p) => acc + (parseFloat(p.unrealized_pnl || "0") || 0), 0);
              return (
                <div
                  style={{
                    fontSize: "18px",
                    fontWeight: 700,
                    color: totalUnpnl >= 0 ? "#10b981" : "#ef4444",
                    marginTop: "4px",
                  }}
                >
                  {totalUnpnl >= 0 ? `+${totalUnpnl.toFixed(2)}` : totalUnpnl.toFixed(2)} USDT
                </div>
              );
            })()}
          </div>

          <div
            style={{
              background: "rgba(30, 41, 59, 0.7)",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              borderRadius: "8px",
              padding: "12px 16px",
            }}
          >
            <div style={{ fontSize: "11px", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>
              Tổng Ký Quỹ Đang Dùng (Margin)
            </div>
            {(() => {
              const totalMargin = positions.reduce((acc, p) => {
                const m = parseFloat(p.initial_margin || "0") || (parseFloat(p.amount) * parseFloat(p.entry_price) / (p.leverage || 1));
                return acc + (isNaN(m) ? 0 : m);
              }, 0);
              return (
                <div style={{ fontSize: "18px", fontWeight: 700, color: "#38bdf8", marginTop: "4px" }}>
                  ${totalMargin.toFixed(2)} USDT
                </div>
              );
            })()}
          </div>

          <div
            style={{
              background: "rgba(30, 41, 59, 0.7)",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              borderRadius: "8px",
              padding: "12px 16px",
            }}
          >
            <div style={{ fontSize: "11px", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>
              Số Vị Thế Mở / Trần An Toàn
            </div>
            <div style={{ fontSize: "18px", fontWeight: 700, color: positions.length <= 5 ? "#10b981" : "#f59e0b", marginTop: "4px" }}>
              {positions.length} / 5 vị thế {positions.length > 5 ? "(Vượt trần khống chế)" : "(An toàn)"}
            </div>
          </div>

          <div
            style={{
              background: "rgba(30, 41, 59, 0.7)",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              borderRadius: "8px",
              padding: "12px 16px",
            }}
          >
            <div style={{ fontSize: "11px", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>
              Kèo Bất Tử (Đã Khóa Lãi)
            </div>
            {(() => {
              const riskFreeCount = positions.filter((p) => {
                if (!p.sl_price || !p.entry_price) return false;
                const sl = parseFloat(p.sl_price);
                const entry = parseFloat(p.entry_price);
                if (isNaN(sl) || isNaN(entry)) return false;
                return p.side === "LONG" ? sl >= entry : sl <= entry;
              }).length;
              return (
                <div style={{ fontSize: "18px", fontWeight: 700, color: "#a855f7", marginTop: "4px" }}>
                  🛡️ {riskFreeCount} vị thế (100% Risk-Free)
                </div>
              );
            })()}
          </div>
        </div>
      )}

      {/* Positions Table */}
      <div className="table-container">
        <div className="table-header">
          <div className="table-title">Vị thế Đang Nắm Giữ ({positions.length})</div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Cặp & Nguồn</th>
              <th>Chiều & Đòn bẩy</th>
              <th>Ký quỹ (Margin) / Số lượng</th>
              <th>Giá vào (Entry)</th>
              <th>Giá hiện tại (Mark)</th>
              <th>Unrealized PnL</th>
              <th>% PnL (ROE)</th>
              <th>Bảo vệ SL</th>
              <th>Lệnh TP</th>
              <th style={{ textAlign: "right" }}>Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 ? (
              <tr>
                <td colSpan={10} style={{ textAlign: "center", color: "var(--text-muted)", padding: "32px" }}>
                  Hiện không có vị thế bot nào đang mở.
                </td>
              </tr>
            ) : (
              positions.map((pos) => {
                const unpnl = parseFloat(pos.unrealized_pnl || "0");
                const posMargin = parseFloat(pos.initial_margin || "0") || (parseFloat(pos.amount) * parseFloat(pos.entry_price) / (pos.leverage || 1));
                const posNotional = parseFloat(pos.notional || "0") || (parseFloat(pos.amount) * parseFloat(pos.entry_price));
                const roePct = pos.roe_pct ? pos.roe_pct : (posMargin > 0 ? `${(unpnl / posMargin * 100).toFixed(2)}%` : "+0.00%");
                const isRoePos = !roePct.startsWith("-");
                const isAi = pos.source_type === "AI" || pos.source_label?.includes("AI");
                const isTelegram = pos.source_type === "TELEGRAM" || (!isAi && pos.source_type !== "MANUAL");

                return (
                  <tr key={pos.symbol}>
                    <td>
                      <div className="mono" style={{ fontWeight: 700, color: "#fff", fontSize: "14px" }}>
                        {pos.symbol}
                      </div>
                      <div style={{ marginTop: "4px" }}>
                        {isAi ? (
                          <span
                            className="badge"
                            style={{
                              background: "rgba(168, 85, 247, 0.15)",
                              color: "#c084fc",
                              border: "1px solid rgba(168, 85, 247, 0.35)",
                              fontSize: "10px",
                              fontWeight: 600,
                              padding: "2px 6px",
                            }}
                          >
                            🤖 AI Quant (Argon 4)
                          </span>
                        ) : isTelegram ? (
                          <span
                            className="badge"
                            style={{
                              background: "rgba(59, 130, 246, 0.12)",
                              color: "#60a5fa",
                              border: "1px solid rgba(59, 130, 246, 0.3)",
                              fontSize: "10px",
                              fontWeight: 600,
                              padding: "2px 6px",
                            }}
                          >
                            {pos.source_label || "📢 Telegram"}
                          </span>
                        ) : (
                          <span
                            className="badge"
                            style={{
                              background: "rgba(156, 163, 175, 0.12)",
                              color: "#9ca3af",
                              fontSize: "10px",
                              padding: "2px 6px",
                            }}
                          >
                            👤 Thủ công
                          </span>
                        )}
                      </div>
                    </td>
                    <td>
                      <span className={`badge ${pos.side === "LONG" ? "badge-read-only" : "badge-live"}`}>
                        {pos.side} {pos.leverage}x ({pos.margin_type})
                      </span>
                    </td>
                    <td className="mono">
                      <div style={{ fontWeight: 700, color: "#10b981", fontSize: "13px" }}>
                        ${posMargin.toFixed(2)} USDT
                      </div>
                      <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                        {pos.amount} coin (~${posNotional.toFixed(1)})
                      </div>
                    </td>
                    <td className="mono">{pos.entry_price}</td>
                    <td className="mono">{pos.mark_price || "—"}</td>
                    <td className={`mono ${unpnl >= 0 ? "text-success" : "text-danger"}`} style={{ fontWeight: 700 }}>
                      <div style={{ fontSize: "14px" }}>
                        {unpnl >= 0 ? `+${unpnl.toFixed(2)}` : unpnl.toFixed(2)} USDT
                      </div>
                    </td>
                    <td className={`mono ${isRoePos ? "text-success" : "text-danger"}`} style={{ fontWeight: 700, fontSize: "13px" }}>
                      <div>{isRoePos && !roePct.startsWith("+") ? `+${roePct}` : roePct}</div>
                      <div style={{ fontSize: "10px", color: "var(--text-muted)", fontWeight: 400 }}>trên margin</div>
                    </td>
                    <td>
                      {(() => {
                        const slVal = parseFloat(pos.sl_price || "0");
                        const entryVal = parseFloat(pos.entry_price || "0");
                        const isBreakevenLocked = Boolean(
                          pos.sl_price && entryVal > 0 && (
                            (pos.side === "LONG" && slVal >= entryVal) ||
                            (pos.side === "SHORT" && slVal <= entryVal)
                          )
                        );

                        if (isBreakevenLocked) {
                          return (
                            <span
                              className="badge"
                              style={{
                                background: "rgba(16, 185, 129, 0.18)",
                                color: "#34d399",
                                border: "1px solid rgba(16, 185, 129, 0.45)",
                                fontWeight: 700,
                                fontSize: "11px",
                                padding: "3px 8px",
                              }}
                              title="Lệnh này đã dời Stop Loss qua giá Entry. Đã khóa lãi thành công, 100% không còn rủi ro!"
                            >
                              🛡️ KHÓA LÃI: {pos.sl_price}
                            </span>
                          );
                        }

                        if (pos.sl_price) {
                          return (
                            <span
                              className="badge"
                              style={{
                                background: "rgba(239, 68, 68, 0.15)",
                                color: "#f87171",
                                border: "1px solid rgba(239, 68, 68, 0.35)",
                                fontWeight: 700,
                              }}
                            >
                              SL: {pos.sl_price}
                            </span>
                          );
                        }

                        if (pos.sl_order_id) {
                          return <span className="badge badge-read-only">SL: {pos.sl_order_id.slice(-6)}</span>;
                        }

                        return <span className="badge badge-live">CHƯA CÓ SL</span>;
                      })()}
                    </td>
                    <td className="mono" style={{ fontSize: "12px" }}>
                      {pos.tp_order_ids?.length > 0 ? `${pos.tp_order_ids.length} lệnh TP` : "Chưa có"}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => setClosingSymbol(pos.symbol)}
                      >
                        <XCircle size={13} className="text-danger" />
                        <span>Đóng vị thế</span>
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Active Orders Table */}
      <div className="table-container">
        <div className="table-header">
          <div className="table-title">Lệnh Điều Kiện & Giới Hạn Sàn ({orders.length})</div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Order ID</th>
              <th>Cặp</th>
              <th>Chiều</th>
              <th>Loại lệnh</th>
              <th>Giá đặt</th>
              <th>Số lượng</th>
              <th>Đã khớp</th>
              <th>Trạng thái</th>
            </tr>
          </thead>
          <tbody>
            {orders.length === 0 ? (
              <tr>
                <td colSpan={8} style={{ textAlign: "center", color: "var(--text-muted)", padding: "28px" }}>
                  Không có lệnh chờ nào trên sàn.
                </td>
              </tr>
            ) : (
              orders.map((ord) => (
                <tr key={ord.order_id}>
                  <td className="mono" style={{ fontSize: "12px", color: "var(--text-muted)" }}>
                    {ord.order_id}
                  </td>
                  <td className="mono" style={{ fontWeight: 600 }}>{ord.symbol}</td>
                  <td>
                    <span className={`badge ${ord.side === "BUY" ? "badge-read-only" : "badge-live"}`}>
                      {ord.side}
                    </span>
                  </td>
                  <td><code>{ord.type}</code></td>
                  <td className="mono">{ord.price}</td>
                  <td className="mono">{ord.orig_qty}</td>
                  <td className="mono">{ord.executed_qty}</td>
                  <td><span className="badge badge-shadow">{ord.status}</span></td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Autonomous AI Quant Scanner & Setups */}
      <AITraderCard />

      {/* Confirmation Modal for Single Position Close */}
      <ConfirmModal
        isOpen={closingSymbol !== null}
        title={`Xác nhận đóng vị thế ${closingSymbol}`}
        message={
          isReadOnly
            ? `Hệ thống hiện ở chế độ READ_ONLY. Thao tác này sẽ chỉ kiểm tra chính sách và không gửi lệnh đóng lên sàn Binance thật.`
            : `CẢNH BÁO: Lệnh đóng thị trường (MARKET CLOSE) sẽ được gửi lên sàn Binance để thanh lý toàn bộ vị thế ${closingSymbol}. Bạn có chắc chắn muốn thực hiện?`
        }
        confirmText="Đồng ý Đóng vị thế"
        isDanger={true}
        onConfirm={handleClosePosition}
        onCancel={() => setClosingSymbol(null)}
      />

      {/* Confirmation Modal for Closing All Bot Positions */}
      <ConfirmModal
        isOpen={showCloseAllModal}
        title="KHẨN CẤP: ĐÓNG TẤT CẢ VỊ THẾ BOT"
        message={`Hành động này sẽ gửi lệnh MARKET CLOSE để đóng TOÀN BỘ ${positions.length} vị thế đang nắm giữ và hủy toàn bộ lệnh Stop-Loss, Take-Profit liên quan.`}
        confirmText="XÁC NHẬN ĐÓNG TẤT CẢ"
        requiredKeyword="DONG HET"
        isDanger={true}
        onConfirm={handleCloseAllPositions}
        onCancel={() => setShowCloseAllModal(false)}
      />
    </div>
  );
};
