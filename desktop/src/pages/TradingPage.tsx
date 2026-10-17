import React, { useState, useEffect } from "react";
import { AlertOctagon, XCircle, ShieldCheck, RefreshCw } from "lucide-react";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";
import { ConfirmModal } from "../components/ConfirmModal";
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

      {/* Positions Table */}
      <div className="table-container">
        <div className="table-header">
          <div className="table-title">Vị thế Đang Nắm Giữ ({positions.length})</div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Cặp giao dịch</th>
              <th>Chiều & Đòn bẩy</th>
              <th>Khối lượng</th>
              <th>Giá vào (Entry)</th>
              <th>Giá hiện tại (Mark)</th>
              <th>Unrealized PnL</th>
              <th>Bảo vệ SL</th>
              <th>Lệnh TP</th>
              <th style={{ textAlign: "right" }}>Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 ? (
              <tr>
                <td colSpan={9} style={{ textAlign: "center", color: "var(--text-muted)", padding: "32px" }}>
                  Hiện không có vị thế bot nào đang mở.
                </td>
              </tr>
            ) : (
              positions.map((pos) => {
                const unpnl = parseFloat(pos.unrealized_pnl || "0");
                return (
                  <tr key={pos.symbol}>
                    <td className="mono" style={{ fontWeight: 700, color: "#fff" }}>{pos.symbol}</td>
                    <td>
                      <span className={`badge ${pos.side === "LONG" ? "badge-read-only" : "badge-live"}`}>
                        {pos.side} {pos.leverage}x ({pos.margin_type})
                      </span>
                    </td>
                    <td className="mono">{pos.amount}</td>
                    <td className="mono">{pos.entry_price}</td>
                    <td className="mono">{pos.mark_price || "—"}</td>
                    <td className={`mono ${unpnl >= 0 ? "text-success" : "text-danger"}`} style={{ fontWeight: 700 }}>
                      {unpnl >= 0 ? `+${unpnl.toFixed(2)}` : unpnl.toFixed(2)} USDT
                    </td>
                    <td>
                      {pos.sl_order_id ? (
                        <span className="badge badge-read-only">SL: {pos.sl_order_id.slice(-6)}</span>
                      ) : (
                        <span className="badge badge-live">CHƯA CÓ SL</span>
                      )}
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
