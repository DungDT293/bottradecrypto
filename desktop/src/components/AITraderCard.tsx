import React, { useState, useEffect, useCallback } from "react";
import {
  Brain,
  Sparkles,
  Zap,
  Key,
  ShieldCheck,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  ExternalLink,
  CheckCircle2,
  Play,
  Sliders,
  Eye,
  EyeOff,
} from "lucide-react";
import { api } from "../services/api";
import { useApp } from "../context/AppContext";
import type { AIStatusResponse, AISetup } from "../types/api";

export const AITraderCard: React.FC = () => {
  const { addToast, snapshot } = useApp();

  const [aiStatus, setAiStatus] = useState<AIStatusResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [scanning, setScanning] = useState<boolean>(false);
  const [apiKeyInput, setApiKeyInput] = useState<string>("");
  const [showKeyInput, setShowKeyInput] = useState<boolean>(false);
  const [showKeySecret, setShowKeySecret] = useState<boolean>(false);
  const [savingKey, setSavingKey] = useState<boolean>(false);
  const [togglingEnabled, setTogglingEnabled] = useState<boolean>(false);
  const [executingSymbol, setExecutingSymbol] = useState<string | null>(null);
  const [scanInterval, setScanInterval] = useState<number>(15);
  const [minConfidence, setMinConfidence] = useState<number>(80);
  const [selectedModel, setSelectedModel] = useState<string>("gemini-2.0-flash");

  const openSymbols = React.useMemo(() => {
    return new Set(
      (snapshot?.positions || [])
        .filter((p: any) => Math.abs(Number(p.amount || p.positionAmt || p.size || p.contracts || 0)) > 0)
        .map((p: any) => String(p.symbol || "").toUpperCase())
    );
  }, [snapshot?.positions]);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await api.getAIStatus();
      setAiStatus(data);
      setScanInterval(data.scan_interval_minutes || 15);
      setMinConfidence(data.min_confidence || 80);
      if (data.preferred_model) setSelectedModel(data.preferred_model);
    } catch {
      // Ignored if backend not ready yet
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const timer = setInterval(fetchStatus, 8000);
    return () => clearInterval(timer);
  }, [fetchStatus]);

  const handleToggleAI = async () => {
    if (!aiStatus) return;
    const nextState = !aiStatus.enabled;
    setTogglingEnabled(true);
    try {
      const res = await api.updateAIConfig({ enabled: nextState });
      setAiStatus((prev) => (prev ? { ...prev, enabled: res.enabled } : null));
      addToast(
        nextState
          ? "Đã BẬT AI Quant Tự Động Trade. AI sẽ quét và khớp lệnh khi có tín hiệu chuẩn."
          : "Đã TẮT AI Tự Động Trade. AI sẽ chỉ ở chế độ quét phân tích.",
        nextState ? "success" : "info"
      );
    } catch (err: any) {
      addToast(err?.message || "Lỗi bật/tắt AI", "error");
    } finally {
      setTogglingEnabled(false);
    }
  };

  const handleSaveApiKey = async () => {
    if (!apiKeyInput.trim()) return;
    setSavingKey(true);
    try {
      const res = await api.updateAIConfig({ gemini_api_key: apiKeyInput.trim() });
      setAiStatus((prev) =>
        prev
          ? {
              ...prev,
              has_gemini_key: res.has_gemini_key,
              gemini_key_masked: res.gemini_key_masked,
            }
          : null
      );
      setApiKeyInput("");
      setShowKeyInput(false);
      addToast("Đã lưu Google Gemini API Key thành công!", "success");
    } catch (err: any) {
      addToast(err?.message || "Lỗi lưu Gemini API Key", "error");
    } finally {
      setSavingKey(false);
    }
  };

  const handleRemoveGeminiKey = async () => {
    try {
      await api.updateAIConfig({ gemini_api_key: "" });
      setAiStatus((prev) =>
        prev ? { ...prev, has_gemini_key: false, gemini_key_masked: null } : null
      );
      addToast("Đã gỡ bỏ Gemini API Key. Hệ thống chuyển sang Quant Engine tích hợp sẵn.", "info");
    } catch (err: any) {
      addToast(err?.message || "Lỗi gỡ Gemini Key", "error");
    }
  };

  const handleSaveParams = async (interval: number, confidence: number) => {
    try {
      await api.updateAIConfig({
        scan_interval_minutes: interval,
        min_confidence: confidence,
        preferred_model: selectedModel,
      });
      addToast("Đã cập nhật tham số quét AI thành công.", "success");
    } catch (err: any) {
      addToast(err?.message || "Lỗi cập nhật tham số AI", "error");
    }
  };

  const handleSaveModel = async (model: string) => {
    setSelectedModel(model);
    try {
      await api.updateAIConfig({ preferred_model: model });
      const display = model.replace("gemini-", "Gemini ").toUpperCase();
      addToast(`Đã chuyển sang sử dụng mô hình ${display}`, "success");
    } catch (err: any) {
      addToast(err?.message || "Lỗi cập nhật model AI", "error");
    }
  };

  const handleScanNow = async () => {
    setScanning(true);
    try {
      const res = await api.scanAIMarket();
      addToast(
        res.count > 0
          ? `Quét xong! Tìm thấy ${res.count} cơ hội vào lệnh R:R cao.`
          : "Quét xong! Thị trường hiện chưa có kèo đạt chuẩn an toàn.",
        res.count > 0 ? "success" : "info"
      );
      await fetchStatus();
    } catch (err: any) {
      addToast(err?.message || "Lỗi trong khi quét thị trường", "error");
    } finally {
      setScanning(false);
    }
  };

  const handleExecuteSetup = async (setup: AISetup) => {
    setExecutingSymbol(setup.symbol);
    try {
      const res = await api.executeAISetup(setup);
      if (res.success) {
        addToast(
          `Khớp lệnh ${setup.direction} ${setup.symbol} thành công theo phân tích AI!`,
          "success"
        );
        await fetchStatus();
      } else {
        addToast(res.reason || "Không thể vào lệnh lúc này.", "warning");
      }
    } catch (err: any) {
      addToast(err?.message || "Lỗi thực thi lệnh AI", "error");
    } finally {
      setExecutingSymbol(null);
    }
  };

  const openGoogleStudio = () => {
    window.open("https://aistudio.google.com/app/apikey", "_blank");
  };

  const isLive = snapshot?.mode === "LIVE";
  const setups: AISetup[] = aiStatus?.last_scan_results || [];

  return (
    <div id="gemini-section" className="card" style={{ marginTop: "20px", border: "1px solid rgba(139, 92, 246, 0.4)", boxShadow: "0 4px 20px rgba(124, 58, 237, 0.1)" }}>
      {/* CARD HEADER */}
      <div
        className="card-title"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "12px",
          paddingBottom: "14px",
          borderBottom: "1px solid var(--border-color)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <div
            style={{
              width: "36px",
              height: "36px",
              borderRadius: "8px",
              background: "linear-gradient(135deg, #7c3aed 0%, #2563eb 100%)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#fff",
            }}
          >
            <Brain size={20} />
          </div>
          <div>
            <div style={{ fontSize: "16px", fontWeight: 700, color: "#fff", display: "flex", alignItems: "center", gap: "8px" }}>
              <span>AI Quant Autonomous Trader</span>
              <span
                style={{
                  fontSize: "11px",
                  fontWeight: 600,
                  padding: "2px 8px",
                  borderRadius: "12px",
                  background: aiStatus?.enabled ? "rgba(16, 185, 129, 0.15)" : "rgba(148, 163, 184, 0.15)",
                  color: aiStatus?.enabled ? "#10b981" : "#94a3b8",
                  border: `1px solid ${aiStatus?.enabled ? "rgba(16, 185, 129, 0.3)" : "rgba(148, 163, 184, 0.3)"}`,
                }}
              >
                {aiStatus?.enabled ? "🟢 TỰ ĐỘNG: ĐANG BẬT" : "⚪ TỰ ĐỘNG: ĐANG TẮT"}
              </span>
              <span
                style={{
                  fontSize: "11px",
                  fontWeight: 600,
                  padding: "2px 8px",
                  borderRadius: "12px",
                  background: aiStatus?.has_gemini_key ? "rgba(168, 85, 247, 0.15)" : "rgba(245, 158, 11, 0.15)",
                  color: aiStatus?.has_gemini_key ? "#c084fc" : "#fbbf24",
                  border: `1px solid ${aiStatus?.has_gemini_key ? "rgba(168, 85, 247, 0.3)" : "rgba(245, 158, 11, 0.3)"}`,
                }}
              >
                {aiStatus?.has_gemini_key
                  ? (selectedModel === "gemini-1.5-flash"
                      ? "✦ Gemini 1.5 Flash"
                      : selectedModel === "gemini-2.0-flash-lite"
                      ? "✦ Gemini 2.0 Flash Lite"
                      : "✦ Gemini 2.0 Flash")
                  : "⚡ Quant Engine Fallback"}
              </span>
              {aiStatus?.quota_status === "RATE_LIMITED_COOLDOWN" && (
                <span
                  style={{
                    fontSize: "11px",
                    fontWeight: 600,
                    padding: "2px 8px",
                    borderRadius: "12px",
                    background: "rgba(245, 158, 11, 0.2)",
                    color: "#fbbf24",
                    border: "1px solid rgba(245, 158, 11, 0.4)",
                  }}
                >
                  🛡️ Cooldown: còn {aiStatus.cooldown_remaining_seconds || 0}s (Quant Engine)
                </span>
              )}
              {aiStatus?.quota_status === "PREPAY_DEPLETED" && (
                <span
                  style={{
                    fontSize: "11px",
                    fontWeight: 600,
                    padding: "2px 8px",
                    borderRadius: "12px",
                    background: "rgba(239, 68, 68, 0.2)",
                    color: "#f87171",
                    border: "1px solid rgba(239, 68, 68, 0.4)",
                  }}
                >
                  ⚠️ Google Prepay Depleted
                </span>
              )}
            </div>
            <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>
              Hệ thống AI tự động phân tích đa khung 1h, đo lường xung lực EMA/RSI/ATR và tự động khớp lệnh R:R cao trên Binance Futures.
            </div>
          </div>
        </div>

        {/* Quick Actions */}
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <button
            className={`btn btn-sm ${aiStatus?.enabled ? "btn-warning" : "btn-primary"}`}
            onClick={handleToggleAI}
            disabled={togglingEnabled || loading}
            style={{ display: "flex", alignItems: "center", gap: "6px" }}
          >
            <Zap size={14} />
            <span>{aiStatus?.enabled ? "Tạm dừng AI Trade" : "Bật AI Tự Động Trade"}</span>
          </button>

          <button
            className="btn btn-secondary btn-sm"
            onClick={handleScanNow}
            disabled={scanning || loading || aiStatus?.is_scanning}
            style={{ display: "flex", alignItems: "center", gap: "6px" }}
          >
            <RefreshCw size={14} className={scanning || aiStatus?.is_scanning ? "spin" : ""} />
            <span>{scanning || aiStatus?.is_scanning ? "Đang quét..." : "Quét thị trường ngay"}</span>
          </button>
        </div>
      </div>

      {/* CARD BODY */}
      <div style={{ padding: "16px 0 0 0" }}>
        {/* Info Banner */}
        <div
          style={{
            background: "rgba(139, 92, 246, 0.08)",
            border: "1px solid rgba(139, 92, 246, 0.2)",
            borderRadius: "8px",
            padding: "12px 14px",
            marginBottom: "16px",
            display: "flex",
            alignItems: "flex-start",
            gap: "10px",
          }}
        >
          <Sparkles size={18} style={{ color: "#a855f7", marginTop: "2px", flexShrink: 0 }} />
          <div style={{ fontSize: "12px", color: "#e2e8f0", lineHeight: 1.5 }}>
            <strong>Cơ chế tự động hóa:</strong> Bạn không cần phụ thuộc vào tín hiệu từ Telegram. Bot có thể quét
            các cặp tiền thanh khoản cao (BTC, ETH, SOL, NEAR, SUI,...) để tìm điểm vào lệnh có xác suất thắng cao.
            Nếu có Gemini API Key, Google AI sẽ đọc diễn biến nến; nếu chưa nhập, bộ thuật toán Quantitative (EMA Cross + RSI Divergence + ATR) sẽ trực tiếp quét độc lập.
          </div>
        </div>

        {/* Configuration Row */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1.1fr 1fr 1fr",
            gap: "14px",
            marginBottom: "18px",
          }}
        >
          {/* Gemini API Key Box */}
          <div
            style={{
              background: "var(--bg-input)",
              padding: "12px 14px",
              borderRadius: "8px",
              border: "1px solid var(--border-color)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", fontWeight: 600, color: "#fff" }}>
                <Key size={14} style={{ color: "#c084fc" }} />
                <span>Google Gemini API Key</span>
              </div>
              <button
                type="button"
                className="btn btn-text btn-sm"
                onClick={openGoogleStudio}
                style={{ fontSize: "11px", color: "#60a5fa", display: "flex", alignItems: "center", gap: "4px", padding: 0 }}
              >
                <span>Nhận Key Free</span>
                <ExternalLink size={11} />
              </button>
            </div>

            {aiStatus?.has_gemini_key && !showKeyInput ? (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <CheckCircle2 size={16} className="text-success" />
                  <span className="mono" style={{ fontSize: "13px", color: "#fff" }}>
                    {aiStatus.gemini_key_masked || "Đã lưu API Key"}
                  </span>
                </div>
                <div style={{ display: "flex", gap: "6px" }}>
                  <button
                    className="btn btn-secondary btn-sm"
                    style={{ padding: "3px 8px", fontSize: "11px", color: "#f87171", borderColor: "rgba(248, 113, 113, 0.4)" }}
                    onClick={handleRemoveGeminiKey}
                  >
                    Gỡ Key
                  </button>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => setShowKeyInput(true)}
                    style={{ fontSize: "11px", padding: "3px 8px" }}
                  >
                    Đổi Key
                  </button>
                </div>
              </div>
            ) : (
              <div style={{ display: "flex", gap: "8px" }}>
                <div style={{ position: "relative", flex: 1 }}>
                  <input
                    type={showKeySecret ? "text" : "password"}
                    className="input"
                    placeholder="Dán API Key (AIzaSy...)"
                    value={apiKeyInput}
                    onChange={(e) => setApiKeyInput(e.target.value)}
                    style={{ fontSize: "12px", width: "100%", paddingRight: "32px" }}
                  />
                  <button
                    type="button"
                    onClick={() => setShowKeySecret(!showKeySecret)}
                    style={{
                      position: "absolute",
                      right: "8px",
                      top: "50%",
                      transform: "translateY(-50%)",
                      background: "transparent",
                      border: "none",
                      color: "var(--text-muted)",
                      cursor: "pointer",
                    }}
                  >
                    {showKeySecret ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={handleSaveApiKey}
                  disabled={savingKey || !apiKeyInput.trim()}
                >
                  {savingKey ? "Lưu..." : "Lưu"}
                </button>
                {showKeyInput && (
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => setShowKeyInput(false)}
                  >
                    Hủy
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Gemini 3.6+ Model Selector & Quota Guard Box */}
          <div
            style={{
              background: "var(--bg-input)",
              padding: "12px 14px",
              borderRadius: "8px",
              border: "1px solid var(--border-color)",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", fontWeight: 600, color: "#fff" }}>
                <Sparkles size={14} style={{ color: "#a855f7" }} />
                <span>Mô Hình AI (≥ 3.6)</span>
              </div>
              <span
                style={{
                  fontSize: "10px",
                  padding: "1px 6px",
                  borderRadius: "10px",
                  background: "rgba(16, 185, 129, 0.15)",
                  color: "#10b981",
                  border: "1px solid rgba(16, 185, 129, 0.3)",
                }}
              >
                Zero Limit Guard
              </span>
            </div>

            <div>
              <label style={{ fontSize: "11px", color: "var(--text-muted)", display: "block", marginBottom: "4px" }}>
                Chọn Mô hình AI
              </label>
              <select
                className="input"
                style={{ fontSize: "12px", padding: "4px 8px", width: "100%" }}
                value={selectedModel}
                onChange={(e) => handleSaveModel(e.target.value)}
              >
                <option value="gemini-2.0-flash">Gemini 2.0 Flash (Free 15 RPM | Siêu Tốc 400ms | News Sentinel)</option>
                <option value="gemini-1.5-flash">Gemini 1.5 Flash (Free 15 RPM | Cực Nhẹ 300ms)</option>
                <option value="gemini-2.0-flash-lite">Gemini 2.0 Flash Lite (Free | Tiết Kiệm Quota)</option>
              </select>
              <div style={{ fontSize: "10px", color: "#94a3b8", marginTop: "4px" }}>
                🛡️ Lọc Quant trước khi gọi API (tiết kiệm 90% quota) + Delay 2.5s chống Limit.
              </div>
            </div>
          </div>

          {/* Scanner Parameters Box */}
          <div
            style={{
              background: "var(--bg-input)",
              padding: "12px 14px",
              borderRadius: "8px",
              border: "1px solid var(--border-color)",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", fontWeight: 600, color: "#fff", marginBottom: "8px" }}>
              <Sliders size={14} style={{ color: "#38bdf8" }} />
              <span>Tham Số Quét Thị Trường</span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-muted)", display: "block", marginBottom: "4px" }}>
                  Chu kỳ quét
                </label>
                <select
                  className="input"
                  style={{ fontSize: "12px", padding: "4px 8px" }}
                  value={scanInterval}
                  onChange={(e) => {
                    const val = Number(e.target.value);
                    setScanInterval(val);
                    handleSaveParams(val, minConfidence);
                  }}
                >
                  <option value={5}>5 phút / lần</option>
                  <option value={15}>15 phút / lần (Khuyên dùng)</option>
                  <option value={30}>30 phút / lần</option>
                  <option value={60}>60 phút / lần</option>
                </select>
              </div>

              <div>
                <label style={{ fontSize: "11px", color: "var(--text-muted)", display: "block", marginBottom: "4px" }}>
                  Phân cấp tin cậy tối thiểu
                </label>
                <select
                  className="input"
                  style={{ fontSize: "12px", padding: "4px 8px" }}
                  value={minConfidence}
                  onChange={(e) => {
                    const val = Number(e.target.value);
                    setMinConfidence(val);
                    handleSaveParams(scanInterval, val);
                  }}
                >
                  <option value={80}>Tier 80%+ (Mở Rộng: Quét tất cả từ 80%, 85% &amp; 90% - Bắt trọn mọi kèo ngon)</option>
                  <option value={85}>Tier 85%+ (Tiêu Chuẩn: Bắt Order Block &amp; Vua Sóng &gt;= 85% - WR 81.3%)</option>
                  <option value={90}>Tier 90%+ (Siêu Chọn Lọc: Chỉ bắt Trend Continuation Vua Sóng &gt;= 90% - WR 89.4%)</option>
                </select>
              </div>
            </div>
          </div>
        </div>

        {/* Watchlist Chips */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", marginBottom: "16px" }}>
          <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>Danh sách theo dõi (Top 35 Coin):</span>
          {(aiStatus?.watchlist || [
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
            "LINKUSDT", "SUIUSDT", "NEARUSDT", "PEPEUSDT", "APTUSDT", "FETUSDT", "TAOUSDT", "RENDERUSDT",
            "WIFUSDT", "SHIBUSDT", "ARBUSDT", "OPUSDT", "TIAUSDT", "INJUSDT", "SEIUSDT", "DOTUSDT",
            "ATOMUSDT", "LTCUSDT", "BCHUSDT", "UNIUSDT", "AAVEUSDT", "FILUSDT", "FTMUSDT", "ORDIUSDT",
            "BONKUSDT", "FLOKIUSDT", "ENAUSDT"
          ]).map((sym) => (
            <span
              key={sym}
              style={{
                fontSize: "11px",
                padding: "2px 6px",
                background: "rgba(255, 255, 255, 0.05)",
                borderRadius: "4px",
                color: "#94a3b8",
                border: "1px solid rgba(255, 255, 255, 0.08)",
              }}
            >
              {sym.replace("USDT", "")}
            </span>
          ))}
          {aiStatus?.last_scan_time && (
            <span style={{ fontSize: "11px", color: "var(--text-muted)", marginLeft: "auto" }}>
              Lần quét gần nhất: {new Date(aiStatus.last_scan_time).toLocaleTimeString("vi-VN")}
            </span>
          )}
        </div>

        {/* MARKET SCAN RESULTS */}
        <div>
          <div style={{ fontSize: "13px", fontWeight: 600, color: "#fff", marginBottom: "10px", display: "flex", alignItems: "center", gap: "6px" }}>
            <Zap size={14} style={{ color: "#eab308" }} />
            <span>Cơ Hội Giao Dịch &amp; Tín Hiệu AI ({setups.length})</span>
          </div>

          {setups.length === 0 ? (
            <div
              style={{
                background: "rgba(255, 255, 255, 0.02)",
                border: "1px dashed var(--border-color)",
                borderRadius: "8px",
                padding: "24px",
                textAlign: "center",
                color: "var(--text-muted)",
                fontSize: "13px",
              }}
            >
              <ShieldCheck size={28} style={{ color: "#10b981", margin: "0 auto 8px auto" }} />
              <div>Hiện chưa có cặp tiền nào thỏa mãn điều kiện an toàn (R:R ≥ 2.0 & Tin cậy ≥ {minConfidence}%).</div>
              <div style={{ fontSize: "11px", marginTop: "4px", color: "var(--text-secondary)" }}>
                Hệ thống ưu tiên bảo toàn vốn và chỉ kích hoạt khi xác suất thắng cao. Nhấn <strong>"Quét thị trường ngay"</strong> để cập nhật dữ liệu nến mới nhất.
              </div>
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: "12px" }}>
              {setups.map((setup, idx) => {
                const isLong = setup.direction === "LONG";
                const isExecuting = executingSymbol === setup.symbol;
                return (
                  <div
                    key={`${setup.symbol}_${idx}`}
                    style={{
                      background: "var(--bg-input)",
                      border: `1px solid ${isLong ? "rgba(16, 185, 129, 0.3)" : "rgba(239, 68, 68, 0.3)"}`,
                      borderRadius: "8px",
                      padding: "12px 14px",
                      display: "flex",
                      flexDirection: "column",
                      justifyContent: "space-between",
                    }}
                  >
                    <div>
                      {/* Top Setup Row */}
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                          <span style={{ fontSize: "15px", fontWeight: 700, color: "#fff" }}>{setup.symbol}</span>
                          <span
                            style={{
                              fontSize: "11px",
                              fontWeight: 700,
                              padding: "2px 6px",
                              borderRadius: "4px",
                              background: isLong ? "rgba(16, 185, 129, 0.2)" : "rgba(239, 68, 68, 0.2)",
                              color: isLong ? "#10b981" : "#ef4444",
                              display: "flex",
                              alignItems: "center",
                              gap: "3px",
                            }}
                          >
                            {isLong ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                            {setup.direction}
                          </span>
                          {openSymbols.has(setup.symbol.toUpperCase()) && (
                            <span
                              className="badge"
                              style={{
                                backgroundColor: "rgba(16, 185, 129, 0.25)",
                                color: "#10b981",
                                border: "1px solid #10b981",
                                fontSize: "10px",
                                fontWeight: 700,
                                padding: "2px 6px",
                                borderRadius: "4px",
                                display: "inline-flex",
                                alignItems: "center",
                                gap: "3px",
                              }}
                            >
                              <ShieldCheck size={11} />
                              <span>ĐÃ VÀO LỆNH (ĐANG CHẠY)</span>
                            </span>
                          )}
                        </div>

                        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                          <span
                            style={{
                              fontSize: "11px",
                              padding: "2px 6px",
                              borderRadius: "4px",
                              background: "rgba(139, 92, 246, 0.15)",
                              color: "#c084fc",
                            }}
                          >
                            R:R {setup.estimated_rr ?? 2.0}
                          </span>
                          <span
                            style={{
                              fontSize: "11px",
                              padding: "2px 6px",
                              borderRadius: "4px",
                              background: setup.confidence >= 90
                                ? "rgba(168, 85, 247, 0.2)"
                                : setup.confidence >= 85
                                  ? "rgba(59, 130, 246, 0.2)"
                                  : "rgba(16, 185, 129, 0.2)",
                              color: setup.confidence >= 90
                                ? "#c084fc"
                                : setup.confidence >= 85
                                  ? "#60a5fa"
                                  : "#34d399",
                              fontWeight: 700,
                              border: setup.confidence >= 90
                                ? "1px solid rgba(168, 85, 247, 0.4)"
                                : setup.confidence >= 85
                                  ? "1px solid rgba(59, 130, 246, 0.4)"
                                  : "1px solid rgba(16, 185, 129, 0.4)",
                            }}
                          >
                            Tier {setup.confidence}% ({setup.confidence >= 90 ? "Trend Sóng (89.4%)" : setup.confidence >= 85 ? "Order Block (81.3%)" : "Sweep Reversal (79.5%)"})
                          </span>
                        </div>
                      </div>

                      {/* Levels Grid */}
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "1fr 1fr 1fr",
                          gap: "6px",
                          background: "rgba(0, 0, 0, 0.2)",
                          padding: "8px",
                          borderRadius: "6px",
                          marginBottom: "8px",
                          fontSize: "11px",
                        }}
                      >
                        <div>
                          <div style={{ color: "var(--text-muted)" }}>Entry (Giá vào)</div>
                          <div className="mono" style={{ color: "#fff", fontWeight: 600 }}>
                            {setup.entry_price}
                          </div>
                        </div>
                        <div>
                          <div style={{ color: "#ef4444" }}>Stop Loss (SL)</div>
                          <div className="mono" style={{ color: "#ef4444", fontWeight: 600 }}>
                            {setup.stop_loss}
                          </div>
                        </div>
                        <div>
                          <div style={{ color: "#10b981" }}>Take Profit (TP2)</div>
                          <div className="mono" style={{ color: "#10b981", fontWeight: 600 }}>
                            {setup.take_profit_2}
                          </div>
                        </div>
                      </div>

                      {/* Multi-Agent Committee Debate Section */}
                      {(setup.bull_arguments || setup.bear_arguments) && (
                        <div
                          style={{
                            background: "rgba(0, 0, 0, 0.25)",
                            border: "1px solid rgba(255, 255, 255, 0.06)",
                            borderRadius: "6px",
                            padding: "8px 10px",
                            marginBottom: "8px",
                            fontSize: "11px",
                            display: "flex",
                            flexDirection: "column",
                            gap: "4px",
                          }}
                        >
                          {setup.bull_arguments && (
                            <div style={{ display: "flex", alignItems: "flex-start", gap: "6px" }}>
                              <span style={{ color: "#10b981", fontWeight: 700, flexShrink: 0 }}>🟢 Phe Bò:</span>
                              <span style={{ color: "#a7f3d0" }}>{setup.bull_arguments}</span>
                            </div>
                          )}
                          {setup.bear_arguments && (
                            <div style={{ display: "flex", alignItems: "flex-start", gap: "6px" }}>
                              <span style={{ color: "#ef4444", fontWeight: 700, flexShrink: 0 }}>🔴 Phe Gấu:</span>
                              <span style={{ color: "#fca5a5" }}>{setup.bear_arguments}</span>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Rationale / Committee Verdict */}
                      <div style={{ fontSize: "11px", color: "#cbd5e1", lineHeight: 1.4, marginBottom: "10px" }}>
                        <span style={{ color: "#fbbf24", fontWeight: 600 }}>⚖️ Phán quyết Quỹ: </span>
                        {setup.rationale}
                      </div>
                    </div>

                    {/* Bottom Action Row */}
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        paddingTop: "8px",
                        borderTop: "1px solid rgba(255, 255, 255, 0.05)",
                      }}
                    >
                      <span style={{ fontSize: "10px", color: "var(--text-muted)" }}>
                        Nguồn: {setup.source}
                      </span>

                      {openSymbols.has(setup.symbol.toUpperCase()) ? (
                        <span
                          className="badge"
                          style={{
                            backgroundColor: "rgba(16, 185, 129, 0.15)",
                            color: "#10b981",
                            border: "1px solid rgba(16, 185, 129, 0.3)",
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "4px",
                            padding: "4px 8px",
                            fontSize: "11px",
                            fontWeight: 600,
                            borderRadius: "4px",
                          }}
                          title="Hệ thống đang giữ vị thế cặp tiền này trên sàn Binance. Cơ chế Zero-Overleveraging tự động ngăn ngừa nhồi lệnh trùng lặp."
                        >
                          <ShieldCheck size={12} />
                          <span>Đã vào lệnh (Đang chạy vị thế)</span>
                        </span>
                      ) : (
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => handleExecuteSetup(setup)}
                          disabled={isExecuting || !isLive}
                          title={!isLive ? "Cần bật chế độ Tiền Thật (LIVE) để đặt lệnh" : undefined}
                          style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "11px", padding: "3px 10px" }}
                        >
                          {isExecuting ? (
                            <>
                              <RefreshCw size={12} className="spin" />
                              <span>Đang vào...</span>
                            </>
                          ) : (
                            <>
                              <Play size={12} />
                              <span>Vào lệnh ngay</span>
                            </>
                          )}
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Zero Liquidation Safety Footer */}
        <div
          style={{
            marginTop: "16px",
            padding: "8px 12px",
            background: "rgba(16, 185, 129, 0.05)",
            border: "1px solid rgba(16, 185, 129, 0.15)",
            borderRadius: "6px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
            fontSize: "11px",
            color: "#94a3b8",
          }}
        >
          <ShieldCheck size={16} className="text-success" style={{ flexShrink: 0 }} />
          <div>
            <strong>Cam kết An toàn Vốn:</strong> Tất cả các lệnh do AI vào đều tự động kích hoạt Đòn bẩy an toàn
            (Safe Leverage), Margin chế độ Crossed, Khối lượng tính toán chuẩn 2% Rủi ro và Lệnh Cắt lỗ STOP_MARKET
            đặt ngay khi mở vị thế.
          </div>
        </div>
      </div>
    </div>
  );
};
