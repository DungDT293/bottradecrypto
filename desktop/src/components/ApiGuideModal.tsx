import React, { useState, useEffect } from "react";
import {
  X,
  BookOpen,
  ShieldCheck,
  ExternalLink,
  CheckCircle2,
  XCircle,
  Key,
  Send,
  Copy,
  Check,
  Globe,
} from "lucide-react";
import { api } from "../services/api";

interface ApiGuideModalProps {
  isOpen: boolean;
  initialTab?: "telegram" | "binance";
  onClose: () => void;
}

export const ApiGuideModal: React.FC<ApiGuideModalProps> = ({
  isOpen,
  initialTab = "binance",
  onClose,
}) => {
  const [activeTab, setActiveTab] = useState<"telegram" | "binance">(initialTab);
  const [publicIp, setPublicIp] = useState<string>("");
  const [loadingIp, setLoadingIp] = useState<boolean>(true);
  const [copiedIp, setCopiedIp] = useState<boolean>(false);

  useEffect(() => {
    if (!isOpen) return;
    let isMounted = true;

    const fetchIp = async () => {
      try {
        const res = await api.getPublicIp();
        if (isMounted && res?.ip) {
          setPublicIp(res.ip);
          setLoadingIp(false);
          return;
        }
      } catch {}

      // Fallback directly to public ipify
      try {
        const resp = await fetch("https://api.ipify.org?format=json");
        const data = await resp.json();
        if (isMounted && data?.ip) {
          setPublicIp(data.ip);
        }
      } catch {}

      if (isMounted) setLoadingIp(false);
    };

    fetchIp();
    return () => {
      isMounted = false;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const handleCopyIp = () => {
    if (!publicIp) return;
    navigator.clipboard.writeText(publicIp);
    setCopiedIp(true);
    setTimeout(() => setCopiedIp(false), 2000);
  };

  return (
    <div className="modal-overlay" onClick={onClose} style={{ zIndex: 1000 }}>
      <div
        className="modal-content"
        onClick={(e) => e.stopPropagation()}
        style={{
          maxWidth: "700px",
          width: "95%",
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div className="modal-header" style={{ padding: "16px 20px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <div
              style={{
                width: "36px",
                height: "36px",
                borderRadius: "8px",
                background: "linear-gradient(135deg, rgba(59, 130, 246, 0.2) 0%, rgba(37, 99, 235, 0.1) 100%)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                border: "1px solid rgba(59, 130, 246, 0.4)",
              }}
            >
              <BookOpen size={20} color="#60a5fa" />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "#fff" }}>
                Hướng Dẫn Cấp Phép Kết Nối API & Bảo Mật
              </h3>
              <p style={{ margin: "2px 0 0 0", fontSize: "12px", color: "var(--text-muted)" }}>
                Hướng dẫn cấp quyền IP và cấu hình Binance Futures an toàn 100%
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
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

        {/* Tab Switcher */}
        <div
          style={{
            display: "flex",
            borderBottom: "1px solid var(--border-color)",
            padding: "0 20px",
            background: "rgba(15, 23, 42, 0.4)",
            gap: "10px",
          }}
        >
          <button
            onClick={() => setActiveTab("binance")}
            style={{
              padding: "12px 16px",
              background: "none",
              border: "none",
              borderBottom: activeTab === "binance" ? "2px solid #f3ba2f" : "2px solid transparent",
              color: activeTab === "binance" ? "#f3ba2f" : "var(--text-secondary)",
              fontWeight: activeTab === "binance" ? 700 : 500,
              fontSize: "13px",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "8px",
              transition: "all 0.2s",
            }}
          >
            <Key size={15} color={activeTab === "binance" ? "#f3ba2f" : "var(--text-muted)"} />
            <span>Sàn Binance Futures (Cấp quyền IP bắt buộc)</span>
          </button>

          <button
            onClick={() => setActiveTab("telegram")}
            style={{
              padding: "12px 16px",
              background: "none",
              border: "none",
              borderBottom: activeTab === "telegram" ? "2px solid #38bdf8" : "2px solid transparent",
              color: activeTab === "telegram" ? "#38bdf8" : "var(--text-secondary)",
              fontWeight: activeTab === "telegram" ? 700 : 500,
              fontSize: "13px",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "8px",
              transition: "all 0.2s",
            }}
          >
            <Send size={15} color={activeTab === "telegram" ? "#38bdf8" : "var(--text-muted)"} />
            <span>Tài Khoản Telegram (MTProto)</span>
          </button>
        </div>

        {/* Body (Scrollable) */}
        <div className="modal-body" style={{ padding: "20px", overflowY: "auto", flex: 1 }}>
          {/* ========================================================= */}
          {/* TAB: BINANCE FUTURES API GUIDE                           */}
          {/* ========================================================= */}
          {activeTab === "binance" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
              {/* Safety Highlight Box */}
              <div
                style={{
                  padding: "14px 16px",
                  borderRadius: "8px",
                  background: "linear-gradient(135deg, rgba(16, 185, 129, 0.12) 0%, rgba(5, 150, 105, 0.05) 100%)",
                  border: "1px solid rgba(16, 185, 129, 0.4)",
                  display: "flex",
                  gap: "12px",
                  alignItems: "flex-start",
                }}
              >
                <ShieldCheck size={24} color="#34d399" style={{ flexShrink: 0, marginTop: "2px" }} />
                <div style={{ fontSize: "13px", lineHeight: "1.5" }}>
                  <strong style={{ color: "#34d399", fontSize: "14px" }}>
                    Cam Kết Bảo Vệ Vốn An Toàn 100%:
                  </strong>
                  <div style={{ color: "var(--text-secondary)", marginTop: "4px" }}>
                    Bot chỉ cần quyền đọc số dư và quyền đặt lệnh Futures.{" "}
                    <strong style={{ color: "#fff" }}>TUYỆT ĐỐI KHÔNG BẬT quyền Rút tiền (Withdrawals)</strong>.
                    Khi quyền rút tiền bị tắt, bất kỳ ai (kể cả người giữ API key) cũng không thể rút 1 xu nào ra khỏi ví sàn Binance của bạn.
                  </div>
                </div>
              </div>

              {/* 5 Steps Section */}
              <div>
                <h4 style={{ margin: "0 0 12px 0", fontSize: "14px", fontWeight: 700, color: "#fff" }}>
                  5 Bước Tạo API & Cấp Quyền IP Trên Binance:
                </h4>

                <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
                  {/* Step 1 */}
                  <div
                    style={{
                      padding: "12px 14px",
                      borderRadius: "6px",
                      background: "rgba(255, 255, 255, 0.03)",
                      border: "1px solid var(--border-color)",
                      display: "flex",
                      gap: "10px",
                    }}
                  >
                    <div
                      style={{
                        width: "24px",
                        height: "24px",
                        borderRadius: "50%",
                        background: "#f3ba2f",
                        color: "#000",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: 700,
                        fontSize: "12px",
                        flexShrink: 0,
                      }}
                    >
                      1
                    </div>
                    <div style={{ fontSize: "13px" }}>
                      <strong>Vào trang Quản lý API trên Binance:</strong>
                      <p style={{ margin: "4px 0 0 0", color: "var(--text-secondary)", fontSize: "12px" }}>
                        Đăng nhập Binance trên trình duyệt → Bấm biểu tượng <strong>Tài khoản (Avatar)</strong> → Chọn{" "}
                        <strong>Quản lý API (API Management)</strong>.
                      </p>
                      <a
                        href="https://www.binance.com/vi/my/settings/api-management"
                        target="_blank"
                        rel="noreferrer"
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "4px",
                          marginTop: "6px",
                          color: "#f3ba2f",
                          fontSize: "12px",
                          textDecoration: "underline",
                        }}
                      >
                        Mở trang Quản lý API Binance <ExternalLink size={12} />
                      </a>
                    </div>
                  </div>

                  {/* Step 2 */}
                  <div
                    style={{
                      padding: "12px 14px",
                      borderRadius: "6px",
                      background: "rgba(255, 255, 255, 0.03)",
                      border: "1px solid var(--border-color)",
                      display: "flex",
                      gap: "10px",
                    }}
                  >
                    <div
                      style={{
                        width: "24px",
                        height: "24px",
                        borderRadius: "50%",
                        background: "#f3ba2f",
                        color: "#000",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: 700,
                        fontSize: "12px",
                        flexShrink: 0,
                      }}
                    >
                      2
                    </div>
                    <div style={{ fontSize: "13px" }}>
                      <strong>Tạo khóa mới:</strong>
                      <p style={{ margin: "4px 0 0 0", color: "var(--text-secondary)", fontSize: "12px" }}>
                        Bấm nút vàng <strong>Tạo API (Create API)</strong> → Chọn loại{" "}
                        <strong>"Tạo bởi hệ thống (System generated)"</strong> → Nhập nhãn đặt tên (vd:{" "}
                        <code>BotTradeCrypto</code>) → Xác thực bảo mật 2FA (Email / Google Auth).
                      </p>
                    </div>
                  </div>

                  {/* Step 3 - IP RESTRICTION (CRITICAL REQUIREMENT) */}
                  <div
                    style={{
                      padding: "14px",
                      borderRadius: "6px",
                      background: "linear-gradient(135deg, rgba(243, 186, 47, 0.12) 0%, rgba(217, 119, 6, 0.05) 100%)",
                      border: "1px solid rgba(243, 186, 47, 0.5)",
                      display: "flex",
                      gap: "12px",
                    }}
                  >
                    <div
                      style={{
                        width: "24px",
                        height: "24px",
                        borderRadius: "50%",
                        background: "#f3ba2f",
                        color: "#000",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: 700,
                        fontSize: "12px",
                        flexShrink: 0,
                      }}
                    >
                      3
                    </div>
                    <div style={{ fontSize: "13px", width: "100%" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <strong style={{ color: "#f3ba2f", fontSize: "14px" }}>
                          CẤP PHÉP IP (BẮT BUỘC ĐỂ MỞ KHÓA QUYỀN FUTURES):
                        </strong>
                      </div>
                      
                      <div
                        style={{
                          margin: "6px 0 10px 0",
                          padding: "8px 12px",
                          background: "rgba(0, 0, 0, 0.35)",
                          borderRadius: "4px",
                          fontSize: "12px",
                          color: "#fde047",
                          lineHeight: "1.5",
                        }}
                      >
                        ⚠️ <strong>Lưu ý quan trọng từ Binance:</strong> Nếu bạn để tùy chọn <em>"Unrestricted (Không giới hạn IP)"</em>, Binance sẽ <strong>KHÓA / LÀM MỜ nút Enable Futures</strong> và không cho phép bạn bật. Bạn bắt buộc phải chọn <em>"Restrict access to trusted IPs only"</em> và thêm IP máy tính này vào thì nút <strong>Enable Futures</strong> mới sáng lên để tích chọn!
                      </div>

                      {/* User's Public IP Box with Copy button */}
                      <div
                        style={{
                          padding: "10px 14px",
                          background: "rgba(15, 23, 42, 0.8)",
                          borderRadius: "6px",
                          border: "1px dashed rgba(243, 186, 47, 0.5)",
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          marginBottom: "10px",
                          gap: "10px",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <Globe size={16} color="#60a5fa" />
                          <div>
                            <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                              Địa chỉ IP mạng máy tính hiện tại của bạn:
                            </div>
                            <div className="mono" style={{ fontSize: "14px", fontWeight: 700, color: "#fff" }}>
                              {loadingIp ? "Đang phát hiện IP..." : publicIp || "Chưa lấy được IP (Kiểm tra mạng)"}
                            </div>
                          </div>
                        </div>

                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          onClick={handleCopyIp}
                          disabled={!publicIp}
                          style={{
                            background: copiedIp ? "#10b981" : "#f3ba2f",
                            color: "#000",
                            fontWeight: 700,
                            display: "flex",
                            alignItems: "center",
                            gap: "6px",
                            padding: "6px 12px",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {copiedIp ? <Check size={14} color="#000" /> : <Copy size={14} color="#000" />}
                          <span>{copiedIp ? "Đã sao chép!" : "Sao Chép IP"}</span>
                        </button>
                      </div>

                      <div style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: "1.6" }}>
                        <strong>Thao tác thực hiện trên Binance:</strong>
                        <ol style={{ margin: "4px 0 0 0", paddingLeft: "20px" }}>
                          <li>Bấm nút <strong>"Sao Chép IP"</strong> ở khung màu vàng bên trên.</li>
                          <li>Trên trang Binance, bấm nút <strong>"Sửa (Edit restrictions)"</strong>.</li>
                          <li>Tại mục <em>IP Access Restriction</em>, tích chọn: <strong>"Restrict access to trusted IPs only (Recommended)"</strong>.</li>
                          <li>Dán IP vừa chép vào ô trống → Bấm nút <strong>Xác nhận (Confirm)</strong>.</li>
                        </ol>
                      </div>
                    </div>
                  </div>

                  {/* Step 4 - Permissions Checklist */}
                  <div
                    style={{
                      padding: "12px 14px",
                      borderRadius: "6px",
                      background: "rgba(255, 255, 255, 0.03)",
                      border: "1px solid var(--border-color)",
                      display: "flex",
                      gap: "10px",
                    }}
                  >
                    <div
                      style={{
                        width: "24px",
                        height: "24px",
                        borderRadius: "50%",
                        background: "#f3ba2f",
                        color: "#000",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: 700,
                        fontSize: "12px",
                        flexShrink: 0,
                      }}
                    >
                      4
                    </div>
                    <div style={{ fontSize: "13px", width: "100%" }}>
                      <strong>Tích chọn phân quyền (Ngay sau khi đã thêm IP):</strong>
                      <p style={{ margin: "4px 0 10px 0", color: "var(--text-secondary)", fontSize: "12px" }}>
                        Sau khi đã thêm IP ở bước 3, checkbox <strong>Enable Futures</strong> sẽ sáng lên. Hãy tích đúng như bảng sau:
                      </p>

                      <div style={{ display: "flex", flexDirection: "column", gap: "6px", fontSize: "12px" }}>
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            padding: "6px 10px",
                            background: "rgba(16, 185, 129, 0.1)",
                            borderRadius: "4px",
                            border: "1px solid rgba(16, 185, 129, 0.3)",
                          }}
                        >
                          <span style={{ display: "flex", alignItems: "center", gap: "6px", color: "#34d399", fontWeight: 600 }}>
                            <CheckCircle2 size={14} /> Enable Reading (Đọc dữ liệu ví & lệnh)
                          </span>
                          <span style={{ color: "#34d399", fontWeight: 600 }}>✓ BẬT (Mặc định)</span>
                        </div>

                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            padding: "6px 10px",
                            background: "rgba(16, 185, 129, 0.15)",
                            borderRadius: "4px",
                            border: "1px solid rgba(16, 185, 129, 0.4)",
                          }}
                        >
                          <span style={{ display: "flex", alignItems: "center", gap: "6px", color: "#34d399", fontWeight: 700 }}>
                            <CheckCircle2 size={14} /> Enable Futures (Hợp đồng tương lai)
                          </span>
                          <span style={{ color: "#34d399", fontWeight: 700 }}>✓ BẮT BUỘC BẬT (Đã mở khóa)</span>
                        </div>

                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            padding: "6px 10px",
                            background: "rgba(239, 68, 68, 0.12)",
                            borderRadius: "4px",
                            border: "1px solid rgba(239, 68, 68, 0.3)",
                          }}
                        >
                          <span style={{ display: "flex", alignItems: "center", gap: "6px", color: "#f87171", fontWeight: 600 }}>
                            <XCircle size={14} /> Enable Withdrawals (Rút tiền)
                          </span>
                          <span style={{ color: "#f87171", fontWeight: 700 }}>⛔ TUYỆT ĐỐI TẮT (Không chọn)</span>
                        </div>

                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            padding: "6px 10px",
                            background: "rgba(0, 0, 0, 0.2)",
                            borderRadius: "4px",
                          }}
                        >
                          <span style={{ color: "var(--text-muted)" }}>
                            Spot & Margin, Chuyển nội bộ, Vay vốn...
                          </span>
                          <span style={{ color: "var(--text-muted)" }}>Tắt (Không cần)</span>
                        </div>
                      </div>

                      <div style={{ marginTop: "10px", fontSize: "12px", color: "var(--text-secondary)" }}>
                        Bấm nút <strong>Lưu (Save)</strong> ở góc trên bên phải trang Binance → Xác thực 2FA để hoàn tất lưu quyền!
                      </div>
                    </div>
                  </div>

                  {/* Step 5 */}
                  <div
                    style={{
                      padding: "12px 14px",
                      borderRadius: "6px",
                      background: "rgba(255, 255, 255, 0.03)",
                      border: "1px solid var(--border-color)",
                      display: "flex",
                      gap: "10px",
                    }}
                  >
                    <div
                      style={{
                        width: "24px",
                        height: "24px",
                        borderRadius: "50%",
                        background: "#f3ba2f",
                        color: "#000",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: 700,
                        fontSize: "12px",
                        flexShrink: 0,
                      }}
                    >
                      5
                    </div>
                    <div style={{ fontSize: "13px" }}>
                      <strong>Dán vào Bot & Xác nhận kết nối:</strong>
                      <p style={{ margin: "4px 0 0 0", color: "var(--text-secondary)", fontSize: "12px" }}>
                        Sao chép <strong>API Key</strong> và <strong>Secret Key</strong> dán vào mục{" "}
                        <strong>"Khóa API Live (Tài khoản thật Binance)"</strong> trong mục Kết nối của Bot → Bấm{" "}
                        <strong>"Lưu khóa Live"</strong> → Bấm nút <strong>"Thử Live API"</strong> để bot hiển thị số dư ví thật!
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ========================================================= */}
          {/* TAB: TELEGRAM API & LOGIN GUIDE                           */}
          {/* ========================================================= */}
          {activeTab === "telegram" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
              {/* How it works info */}
              <div
                style={{
                  padding: "14px 16px",
                  borderRadius: "8px",
                  background: "linear-gradient(135deg, rgba(56, 189, 248, 0.12) 0%, rgba(14, 165, 233, 0.05) 100%)",
                  border: "1px solid rgba(56, 189, 248, 0.4)",
                  display: "flex",
                  gap: "12px",
                  alignItems: "flex-start",
                }}
              >
                <Send size={22} color="#38bdf8" style={{ flexShrink: 0, marginTop: "2px" }} />
                <div style={{ fontSize: "13px", lineHeight: "1.5" }}>
                  <strong style={{ color: "#38bdf8", fontSize: "14px" }}>
                    Nguyên Lý Kết Nối Telegram MTProto:
                  </strong>
                  <div style={{ color: "var(--text-secondary)", marginTop: "4px" }}>
                    Bot đóng vai trò như một ứng dụng Telegram Client độc lập (tương tự Telegram Desktop) kết nối trực tiếp đến Telegram Server.
                    Dữ liệu phiên đăng nhập lưu trong file <code>session</code> cục bộ trên máy của bạn, tuyệt đối bảo mật.
                  </div>
                </div>
              </div>

              <div>
                <h4 style={{ margin: "0 0 12px 0", fontSize: "14px", fontWeight: 700, color: "#fff" }}>
                  Các Bước Đăng Nhập & Cấp Quyền Telegram:
                </h4>

                <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                  {/* Step 1 */}
                  <div
                    style={{
                      padding: "12px 14px",
                      borderRadius: "6px",
                      background: "rgba(255, 255, 255, 0.03)",
                      border: "1px solid var(--border-color)",
                      display: "flex",
                      gap: "10px",
                    }}
                  >
                    <div
                      style={{
                        width: "24px",
                        height: "24px",
                        borderRadius: "50%",
                        background: "#38bdf8",
                        color: "#000",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: 700,
                        fontSize: "12px",
                        flexShrink: 0,
                      }}
                    >
                      1
                    </div>
                    <div style={{ fontSize: "13px" }}>
                      <strong>Lấy API ID & API Hash (Chỉ cần làm 1 lần):</strong>
                      <p style={{ margin: "4px 0 6px 0", color: "var(--text-secondary)", fontSize: "12px" }}>
                        Truy cập website chính thức của Telegram:{" "}
                        <a
                          href="https://my.telegram.org"
                          target="_blank"
                          rel="noreferrer"
                          style={{ color: "#38bdf8", textDecoration: "underline" }}
                        >
                          https://my.telegram.org <ExternalLink size={11} style={{ display: "inline" }} />
                        </a>
                      </p>
                      <ul style={{ margin: 0, paddingLeft: "18px", color: "var(--text-secondary)", fontSize: "12px", lineHeight: "1.6" }}>
                        <li>Nhập Số điện thoại Telegram của bạn (kèm mã quốc gia, vd: <code>+84912345678</code>).</li>
                        <li>Nhập mã code xác thực gửi về ứng dụng Telegram.</li>
                        <li>Chọn mục <strong>"API development tools"</strong>.</li>
                        <li>Điền App title (vd: <code>TradeBot</code>), Short name (vd: <code>tradebot</code>) → Bấm <strong>Create application</strong>.</li>
                        <li>Sao chép <strong>App api_id</strong> (dãy số) và <strong>App api_hash</strong> (dãy chữ).</li>
                        <li>Bấm nút <strong>"API Settings"</strong> trên Bot để dán vào và bấm Lưu.</li>
                      </ul>
                    </div>
                  </div>

                  {/* Step 2 */}
                  <div
                    style={{
                      padding: "12px 14px",
                      borderRadius: "6px",
                      background: "rgba(255, 255, 255, 0.03)",
                      border: "1px solid var(--border-color)",
                      display: "flex",
                      gap: "10px",
                    }}
                  >
                    <div
                      style={{
                        width: "24px",
                        height: "24px",
                        borderRadius: "50%",
                        background: "#38bdf8",
                        color: "#000",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: 700,
                        fontSize: "12px",
                        flexShrink: 0,
                      }}
                    >
                      2
                    </div>
                    <div style={{ fontSize: "13px" }}>
                      <strong>Đăng nhập bằng số điện thoại:</strong>
                      <p style={{ margin: "4px 0 0 0", color: "var(--text-secondary)", fontSize: "12px" }}>
                        Nhập số điện thoại → Nhấn <strong>Gửi mã OTP</strong> → Nhập mã 5 số được Telegram gửi tới ứng dụng Telegram của bạn.
                        (Nếu tài khoản có cài mật khẩu 2 bước Cloud Password, nhập mật khẩu để hoàn tất).
                      </p>
                    </div>
                  </div>

                  {/* Step 3 */}
                  <div
                    style={{
                      padding: "12px 14px",
                      borderRadius: "6px",
                      background: "linear-gradient(135deg, rgba(16, 185, 129, 0.08) 0%, rgba(15, 23, 42, 0.4) 100%)",
                      border: "1px solid rgba(16, 185, 129, 0.3)",
                      display: "flex",
                      gap: "10px",
                    }}
                  >
                    <div
                      style={{
                        width: "24px",
                        height: "24px",
                        borderRadius: "50%",
                        background: "#34d399",
                        color: "#000",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: 700,
                        fontSize: "12px",
                        flexShrink: 0,
                      }}
                    >
                      3
                    </div>
                    <div style={{ fontSize: "13px" }}>
                      <strong style={{ color: "#34d399" }}>1-Click Tự Động Tham Gia 8 Kênh Tinh Hoa:</strong>
                      <p style={{ margin: "4px 0 0 0", color: "var(--text-secondary)", fontSize: "12px" }}>
                        Sau khi đăng nhập xong, chỉ cần bấm nút <strong>"Tham Gia 8 Kênh Ngay"</strong>.
                        Bot sẽ tự động join và tự động kích hoạt giám sát tín hiệu của 8 kênh tinh hoa chuẩn mực (Whales Circle, Coin Chief, Leopard, Crypto Devil, The Wolf, Monk, Bitcoin Bulls, Mermaids).
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          className="modal-footer"
          style={{
            padding: "12px 20px",
            borderTop: "1px solid var(--border-color)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>
            💡 Cần hỗ trợ thêm? Đọc tài liệu tại thư mục <code>docs/</code>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={onClose}>
            Đã hiểu, đóng cửa sổ
          </button>
        </div>
      </div>
    </div>
  );
};