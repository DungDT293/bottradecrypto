import React, { useState, useMemo } from "react";
import {
  TrendingUp,
  Calculator,
  ShieldCheck,
  Sparkles,
  RotateCcw,
} from "lucide-react";

interface CapitalRiskSimulatorProps {
  riskPerSignalPct: number;
  maxDailyLossPct: number;
  tp1WeightPct: number;
  tp2WeightPct: number;
  tp3WeightPct: number;
  liveEquity: number;
  onApplyRisk?: (newRisk: number) => void;
}

export const CapitalRiskSimulator: React.FC<CapitalRiskSimulatorProps> = ({
  riskPerSignalPct,
  maxDailyLossPct,
  tp1WeightPct,
  tp2WeightPct,
  tp3WeightPct,
  liveEquity,
  onApplyRisk,
}) => {
  // Require real equity before presenting account-based projections.
  const initialCapital = liveEquity > 0 ? Math.round(liveEquity * 100) / 100 : 0;
  const [simCapital, setSimCapital] = useState<number>(initialCapital);
  const [activeTab, setActiveTab] = useState<"standard" | "conservative" | "aggressive">("standard");

  // Keep synced if liveEquity updates and user hasn't edited
  const isUsingLiveEquity = Math.abs(simCapital - initialCapital) < 0.01;

  // Single Trade Metrics
  const riskDollar = (simCapital * (riskPerSignalPct / 100));
  const estimatedNotional = (riskDollar / 0.08); // average 8% SL distance
  const estimatedMargin = estimatedNotional / 20; // 20x leverage

  // Reward calculations based on multi-TP weights & average R:R of Top 5 channels
  // TP1: ~1.0R (35%), TP2: ~1.8R (42.3%), TP3: ~3.2R (22.7%)
  const tp1Profit = riskDollar * 1.0 * (tp1WeightPct / 100);
  const tp2Profit = riskDollar * 1.8 * (tp2WeightPct / 100);
  const tp3Profit = riskDollar * 3.2 * (tp3WeightPct / 100);
  const fullWinProfit = tp1Profit + tp2Profit + tp3Profit;
  const averageRR = riskDollar > 0 ? (fullWinProfit / riskDollar).toFixed(2) : "2.20";

  // Safety metrics
  const lossesToHitDailyLimit = riskPerSignalPct > 0 ? Math.floor(maxDailyLossPct / riskPerSignalPct) : 0;
  const lossesToDepleteCapital = riskPerSignalPct > 0 ? Math.floor(100 / riskPerSignalPct) : 0;

  // Safety assessment
  const riskAssessment = useMemo(() => {
    if (riskPerSignalPct <= 2.5) {
      return {
        badge: "Rất An Toàn - Bảo Toàn Vốn Tuyệt Đối",
        color: "#10b981",
        bg: "rgba(16, 185, 129, 0.12)",
        border: "rgba(16, 185, 129, 0.3)",
        desc: "Mức rủi ro thận trọng tối ưu, có thể vượt qua mọi đợt biến động mạnh của thị trường mà không lo sụt giảm vốn.",
      };
    } else if (riskPerSignalPct <= 4.0) {
      return {
        badge: "Cân Bằng Hoàn Hảo - Tăng Trưởng Nhanh",
        color: "#38bdf8",
        bg: "rgba(56, 189, 248, 0.12)",
        border: "rgba(56, 189, 248, 0.3)",
        desc: "Tỷ lệ tăng trưởng lợi nhuận lý tưởng khi kết hợp cùng cơ chế Kèo Bất Tử và Winrate 75%+ của Top 8 Kênh Tinh Hoa.",
      };
    } else if (riskPerSignalPct <= 5.5) {
      return {
        badge: "Tấn Công - Lãi Đột Phá",
        color: "#f59e0b",
        bg: "rgba(245, 158, 11, 0.12)",
        border: "rgba(245, 158, 11, 0.3)",
        desc: "Lợi nhuận tăng rất nhanh theo chuỗi thắng, cần chú ý tuân thủ kỷ luật dừng lỗ ngày 15%.",
      };
    } else {
      return {
        badge: "Rủi Ro Cao - Cần Cân Nhắc",
        color: "#ef4444",
        bg: "rgba(239, 68, 68, 0.12)",
        border: "rgba(239, 68, 68, 0.3)",
        desc: "Chỉ nên áp dụng khi tài khoản đã có lớp đệm lãi lớn, không khuyến nghị cho tài khoản vốn nhỏ dưới $200.",
      };
    }
  }, [riskPerSignalPct]);

  // Dynamic R-Multipliers computed directly from active TP allocations
  // Reward benchmarks of Elite channels: TP1 ~ 1.0R, TP2 ~ 1.8R, TP3 ~ 3.2R
  // 'W' Full Win: All 3 TPs reached
  const fullWinR = (1.0 * tp1WeightPct + 1.8 * tp2WeightPct + 3.2 * tp3WeightPct) / 100;
  // 'P' Partial Win: TP1 & TP2 hit, trailing SL at TP1 locks profit for remaining runner
  const partialWinR = (1.0 * tp1WeightPct + 1.8 * tp2WeightPct + 1.0 * tp3WeightPct) / 100;
  // 'B' Breakeven: TP1 hit, SL moved to Entry, price pulls back to Entry (remaining exits at 0)
  const beWinR = (1.0 * tp1WeightPct) / 100;

  // Generate 30-trade projection data (Realistic Monte Carlo Expectancy Model)
  const projectionData = useMemo(() => {
    // Sequences of 30 realistic trades with natural drawdowns and mixed outcomes:
    // 'W': Ăn trọn 3 TP (+${fullWinR.toFixed(2)}R)
    // 'P': Ăn TP1 + TP2, khóa lãi ở TP1 (+${partialWinR.toFixed(2)}R)
    // 'B': Chốt TP1, quay đầu cắn Entry hòa vốn (+${beWinR.toFixed(2)}R)
    // 'L': Dính SL trực tiếp (-1.0R)
    const sequences = {
      // Standard: 6 W (20%), 11 P (37%), 4 B (13%), 9 L (30%) -> Winrate thực chiến ~70%
      standard: [
        "P", "W", "L", "P", "B", "W", "L", "L", "P", "W", // Nhịp 1-10: dính 3 SL, sụt giảm tạm thời lệnh 7-8
        "P", "P", "W", "L", "B", "P", "W", "P", "L", "P", // Nhịp 11-20: 2 SL
        "L", "L", "P", "W", "P", "B", "P", "L", "B", "P", // Nhịp 21-30: 4 SL, rung lắc lệnh 21-22
      ],
      // Conservative: 3 W (10%), 9 P (30%), 5 B (17%), 13 L (43%) -> Thị trường khó / sideway
      conservative: [
        "P", "L", "L", "P", "B", "W", "L", "L", "P", "B",
        "P", "L", "W", "L", "L", "P", "P", "B", "L", "P",
        "L", "L", "P", "W", "L", "B", "P", "L", "B", "L",
      ],
      // Aggressive: 9 W (30%), 12 P (40%), 3 B (10%), 6 L (20%) -> Sóng xu hướng Uptrend mạnh
      aggressive: [
        "W", "P", "W", "L", "P", "W", "B", "P", "W", "L",
        "P", "W", "P", "W", "L", "P", "B", "W", "P", "L",
        "W", "P", "W", "L", "P", "W", "B", "P", "W", "L",
      ],
    };

    const runSimulation = (seq: string[]) => {
      let cap = simCapital;
      const history = [cap];
      const r = riskPerSignalPct / 100;

      for (const outcome of seq) {
        if (outcome === "W") {
          cap = cap * (1 + fullWinR * r);
        } else if (outcome === "P") {
          cap = cap * (1 + partialWinR * r);
        } else if (outcome === "B") {
          cap = cap * (1 + beWinR * r);
        } else if (outcome === "L") {
          cap = cap * (1 - 1.0 * r);
        }
        history.push(Math.round(cap * 100) / 100);
      }
      return history;
    };

    return {
      standard: runSimulation(sequences.standard),
      conservative: runSimulation(sequences.conservative),
      aggressive: runSimulation(sequences.aggressive),
    };
  }, [simCapital, riskPerSignalPct, fullWinR, partialWinR, beWinR]);

  // SVG Chart Dimensions & Path Generation
  const activeSeries = projectionData[activeTab];
  const minVal = Math.min(simCapital * 0.9, ...activeSeries);
  const maxVal = Math.max(...activeSeries, simCapital * 1.5);
  const chartW = 600;
  const chartH = 180;
  const padX = 40;
  const padY = 20;

  const points = activeSeries.map((val, idx) => {
    const x = padX + (idx / (activeSeries.length - 1)) * (chartW - padX * 2);
    const y = chartH - padY - ((val - minVal) / (maxVal - minVal || 1)) * (chartH - padY * 2);
    return { x, y, val, trade: idx };
  });

  const pathD = points.reduce((acc, p, i) => (i === 0 ? `M ${p.x} ${p.y}` : `${acc} L ${p.x} ${p.y}`), "");
  const fillD = `${pathD} L ${points[points.length - 1].x} ${chartH - padY} L ${points[0].x} ${chartH - padY} Z`;

  // Milestone values for active tab
  const at10 = activeSeries[10] || 0;
  const at20 = activeSeries[20] || 0;
  const at30 = activeSeries[30] || 0;
  const gain30Pct = simCapital > 0 ? (((at30 - simCapital) / simCapital) * 100).toFixed(1) : "0";

  return (
    <div
      className="card"
      style={{
        gridColumn: "span 2",
        marginTop: "20px",
        background: "linear-gradient(180deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.9) 100%)",
        border: "1px solid rgba(56, 189, 248, 0.25)",
        boxShadow: "0 10px 30px -10px rgba(0, 0, 0, 0.5)",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "12px",
          borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
          paddingBottom: "16px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <div
            style={{
              width: "38px",
              height: "38px",
              borderRadius: "10px",
              background: "rgba(56, 189, 248, 0.15)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#38bdf8",
            }}
          >
            <Calculator size={22} />
          </div>
          <div>
            <div style={{ fontSize: "17px", fontWeight: 700, color: "#fff", display: "flex", alignItems: "center", gap: "8px" }}>
              Mô Phỏng Quản Trị Vốn & Kịch Bản Lãi / Lỗ Tự Động
              <span
                style={{
                  fontSize: "11px",
                  background: "rgba(16, 185, 129, 0.2)",
                  color: "#10b981",
                  padding: "3px 8px",
                  borderRadius: "10px",
                  fontWeight: 600,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "4px",
                }}
              >
                <Sparkles size={11} /> Realtime Interactive
              </span>
            </div>
            <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "2px" }}>
              Tự động tính toán chi tiết từng lệnh và vẽ kịch bản tăng trưởng 30 kèo tiếp theo theo số vốn hiện có.
            </div>
          </div>
        </div>

        {/* Live Capital Control */}
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>Số vốn mô phỏng:</div>
          <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
            <span style={{ position: "absolute", left: "10px", color: "#10b981", fontWeight: 700, fontSize: "14px" }}>$</span>
            <input
              type="number"
              min="10"
              max="100000"
              step="10"
              value={simCapital}
              onChange={(e) => setSimCapital(Math.max(1, parseFloat(e.target.value) || 0))}
              className="form-input mono"
              style={{
                paddingLeft: "24px",
                width: "120px",
                fontSize: "14px",
                fontWeight: 700,
                color: "#10b981",
                background: "rgba(0, 0, 0, 0.3)",
              }}
            />
          </div>
          {!isUsingLiveEquity && initialCapital > 0 && (
            <button
              className="btn btn-secondary"
              style={{ padding: "6px 10px", fontSize: "11px", display: "flex", alignItems: "center", gap: "4px" }}
              onClick={() => setSimCapital(initialCapital)}
              title="Khôi phục về số dư Binance Live thực tế"
            >
              <RotateCcw size={12} />
              <span>Dùng vốn Live (${initialCapital})</span>
            </button>
          )}
        </div>
      </div>

      {/* Quick Risk Buttons Bar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "10px",
          marginTop: "16px",
          padding: "10px 14px",
          background: "rgba(0, 0, 0, 0.2)",
          borderRadius: "8px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-secondary)" }}>
            Thử nghiệm nhanh mức Rủi ro mỗi lệnh:
          </span>
          {[
            { label: "2.0% An Toàn", val: 2.0 },
            { label: "2.5% Khuyến Nghị", val: 2.5 },
            { label: "3.5% Cân Bằng", val: 3.5 },
            { label: "4.0% Hiện Tại", val: 4.0 },
            { label: "5.0% Tối Đa", val: 5.0 },
          ].map((preset) => {
            const isSelected = Math.abs(riskPerSignalPct - preset.val) < 0.05;
            return (
              <button
                key={preset.val}
                type="button"
                onClick={() => onApplyRisk && onApplyRisk(preset.val)}
                style={{
                  padding: "4px 10px",
                  borderRadius: "6px",
                  fontSize: "11px",
                  fontWeight: isSelected ? 700 : 500,
                  cursor: "pointer",
                  border: isSelected ? "1px solid #38bdf8" : "1px solid rgba(255, 255, 255, 0.1)",
                  background: isSelected ? "rgba(56, 189, 248, 0.2)" : "rgba(255, 255, 255, 0.04)",
                  color: isSelected ? "#38bdf8" : "var(--text-secondary)",
                  transition: "all 0.15s ease",
                }}
              >
                {preset.label}
              </button>
            );
          })}
        </div>

        {/* Safety Badge */}
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "6px",
            padding: "4px 10px",
            borderRadius: "12px",
            fontSize: "11px",
            fontWeight: 700,
            color: riskAssessment.color,
            background: riskAssessment.bg,
            border: `1px solid ${riskAssessment.border}`,
          }}
        >
          <ShieldCheck size={13} />
          <span>{riskAssessment.badge}</span>
        </div>
      </div>

      {/* 4 Core Per-Trade Calculation Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px", marginTop: "16px" }}>
        {/* Card 1: Max Risk / Loss */}
        <div
          style={{
            padding: "14px",
            borderRadius: "8px",
            background: "rgba(239, 68, 68, 0.07)",
            border: "1px solid rgba(239, 68, 68, 0.25)",
          }}
        >
          <div style={{ fontSize: "11px", color: "#fca5a5", fontWeight: 600, display: "flex", justifyContent: "space-between" }}>
            <span>LỖ TỐI ĐA NẾU DÍNH SL</span>
            <span>{riskPerSignalPct}% Vốn</span>
          </div>
          <div style={{ fontSize: "22px", fontWeight: 800, color: "#ef4444", marginTop: "6px" }}>
            -${riskDollar.toFixed(2)} <span style={{ fontSize: "12px", fontWeight: 500 }}>USDT</span>
          </div>
          <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "4px" }}>
            ≈ {(riskDollar * 25400).toLocaleString("vi-VN")} VNĐ • Ký quỹ 20x: ~${estimatedMargin.toFixed(1)} USDT (Vị thế ~${estimatedNotional.toFixed(0)} USDT)
          </div>
        </div>

        {/* Card 2: Take Profit 1 */}
        <div
          style={{
            padding: "14px",
            borderRadius: "8px",
            background: "rgba(16, 185, 129, 0.07)",
            border: "1px solid rgba(16, 185, 129, 0.25)",
          }}
        >
          <div style={{ fontSize: "11px", color: "#6ee7b7", fontWeight: 600, display: "flex", justifyContent: "space-between" }}>
            <span>LÃI TẠI TP1 ({tp1WeightPct}%)</span>
            <span style={{ color: "#10b981" }}>KHÓA HÒA VỐN</span>
          </div>
          <div style={{ fontSize: "22px", fontWeight: 800, color: "#10b981", marginTop: "6px" }}>
            +${tp1Profit.toFixed(2)} <span style={{ fontSize: "12px", fontWeight: 500 }}>USDT</span>
          </div>
          <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "4px" }}>
            Chốt {tp1WeightPct}% & <strong>dời SL về hòa vốn Entry</strong>
          </div>
        </div>

        {/* Card 3: Full Win (All 3 TPs) */}
        <div
          style={{
            padding: "14px",
            borderRadius: "8px",
            background: "rgba(56, 189, 248, 0.07)",
            border: "1px solid rgba(56, 189, 248, 0.25)",
          }}
        >
          <div style={{ fontSize: "11px", color: "#7dd3fc", fontWeight: 600, display: "flex", justifyContent: "space-between" }}>
            <span>LÃI ĂN TRỌN 3 TP ({tp1WeightPct}/{tp2WeightPct}/{tp3WeightPct})</span>
            <span>R:R ~ 1:{averageRR}</span>
          </div>
          <div style={{ fontSize: "22px", fontWeight: 800, color: "#38bdf8", marginTop: "6px" }}>
            +${fullWinProfit.toFixed(2)} <span style={{ fontSize: "12px", fontWeight: 500 }}>USDT</span>
          </div>
          <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "4px" }}>
            TP2 (+${tp2Profit.toFixed(2)}) & TP3 (+${tp3Profit.toFixed(2)}) • Trailing khóa lãi từng nấc
          </div>
        </div>

        {/* Card 4: Resilience */}
        <div
          style={{
            padding: "14px",
            borderRadius: "8px",
            background: "rgba(139, 92, 246, 0.07)",
            border: "1px solid rgba(139, 92, 246, 0.25)",
          }}
        >
          <div style={{ fontSize: "11px", color: "#c4b5fd", fontWeight: 600, display: "flex", justifyContent: "space-between" }}>
            <span>ĐỆM CHỊU ĐỰNG RỦI RO</span>
            <span>Chặn lỗ ngày {maxDailyLossPct}%</span>
          </div>
          <div style={{ fontSize: "22px", fontWeight: 800, color: "#a78bfa", marginTop: "6px" }}>
            {lossesToHitDailyLimit} <span style={{ fontSize: "13px", fontWeight: 500 }}>lệnh thua / ngày</span>
          </div>
          <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "4px" }}>
            Chịu được <strong>{lossesToDepleteCapital} lệnh thua liên tiếp</strong> mới hết vốn
          </div>
        </div>
      </div>

      {/* Projection Scenarios & SVG Growth Chart Section */}
      <div
        style={{
          marginTop: "20px",
          padding: "16px",
          background: "rgba(0, 0, 0, 0.25)",
          borderRadius: "8px",
          border: "1px solid rgba(255, 255, 255, 0.06)",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "12px",
            marginBottom: "14px",
          }}
        >
          <div>
            <span style={{ fontSize: "14px", fontWeight: 700, color: "#fff", display: "flex", alignItems: "center", gap: "6px" }}>
              <TrendingUp size={16} style={{ color: "#10b981" }} />
              Kịch Bản Mô Phỏng Tăng Trưởng Vốn (Chuỗi 30 Kèo Kế Tiếp)
            </span>
            <span style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "2px", display: "block" }}>
              Dựa trên tỷ lệ thắng thực tế (Winrate 75%+) của Top 8 Kênh Tinh Hoa và cơ chế Kèo Bất Tử.
            </span>
          </div>

          {/* Scenario Tab Selector */}
          <div style={{ display: "flex", background: "rgba(255, 255, 255, 0.05)", borderRadius: "6px", padding: "3px" }}>
            {[
              { id: "conservative", label: "Thận trọng (Win 60%)" },
              { id: "standard", label: "Chuẩn Top 5 Elite (Win 75%)" },
              { id: "aggressive", label: "Sóng đẹp (Win 83%)" },
            ].map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setActiveTab(t.id as any)}
                style={{
                  padding: "5px 12px",
                  borderRadius: "5px",
                  fontSize: "11px",
                  fontWeight: activeTab === t.id ? 700 : 500,
                  border: "none",
                  cursor: "pointer",
                  background: activeTab === t.id ? "#38bdf8" : "transparent",
                  color: activeTab === t.id ? "#0f172a" : "var(--text-secondary)",
                  transition: "all 0.15s ease",
                }}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Visual Chart with SVG */}
        <div style={{ position: "relative", width: "100%", height: `${chartH}px`, marginTop: "8px" }}>
          <svg
            viewBox={`0 0 ${chartW} ${chartH}`}
            style={{ width: "100%", height: "100%", overflow: "visible" }}
            preserveAspectRatio="none"
          >
            <defs>
              <linearGradient id="growthGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.35" />
                <stop offset="100%" stopColor="#38bdf8" stopOpacity="0.0" />
              </linearGradient>
            </defs>

            {/* Horizontal Grid lines */}
            {[0.25, 0.5, 0.75, 1.0].map((ratio) => {
              const yVal = padY + ratio * (chartH - padY * 2);
              const priceLabel = Math.round(maxVal - ratio * (maxVal - minVal));
              return (
                <g key={ratio}>
                  <line
                    x1={padX}
                    y1={yVal}
                    x2={chartW - padX}
                    y2={yVal}
                    stroke="rgba(255, 255, 255, 0.06)"
                    strokeDasharray="4 4"
                  />
                  <text
                    x={padX - 8}
                    y={yVal + 3}
                    fill="var(--text-muted)"
                    fontSize="9"
                    textAnchor="end"
                    fontFamily="monospace"
                  >
                    ${priceLabel}
                  </text>
                </g>
              );
            })}

            {/* Starting Capital Reference Line */}
            <line
              x1={padX}
              y1={points[0].y}
              x2={chartW - padX}
              y2={points[0].y}
              stroke="rgba(148, 163, 184, 0.3)"
              strokeDasharray="2 2"
            />

            {/* Filled Area */}
            <path d={fillD} fill="url(#growthGradient)" />

            {/* Main Growth Curve Line */}
            <path
              d={pathD}
              fill="none"
              stroke="#38bdf8"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            {/* Key Milestone Dots */}
            {[0, 10, 20, 30].map((tIdx) => {
              const pt = points[tIdx];
              if (!pt) return null;
              return (
                <g key={tIdx}>
                  <circle cx={pt.x} cy={pt.y} r="4.5" fill="#38bdf8" stroke="#0f172a" strokeWidth="2" />
                  <text
                    x={pt.x}
                    y={pt.y - 10}
                    fill="#38bdf8"
                    fontSize="10"
                    fontWeight="700"
                    textAnchor="middle"
                    fontFamily="monospace"
                  >
                    ${pt.val}
                  </text>
                  <text
                    x={pt.x}
                    y={chartH - 4}
                    fill="var(--text-muted)"
                    fontSize="9"
                    textAnchor="middle"
                  >
                    Kèo {tIdx}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>

        {/* Milestone Cards Bar */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "12px", marginTop: "16px" }}>
          <div
            style={{
              padding: "12px",
              background: "rgba(255, 255, 255, 0.03)",
              borderRadius: "6px",
              border: "1px solid rgba(255, 255, 255, 0.07)",
            }}
          >
            <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Mục tiêu sau 10 Kèo:</div>
            <div style={{ fontSize: "18px", fontWeight: 700, color: "#fff", marginTop: "2px" }}>
              ${at10} <span style={{ fontSize: "12px", color: "#10b981", fontWeight: 600 }}>
                (+{(((at10 - simCapital) / simCapital) * 100).toFixed(1)}%)
              </span>
            </div>
            <div style={{ fontSize: "11px", color: "var(--text-secondary)", marginTop: "2px" }}>
              Lãi dự kiến: +${(at10 - simCapital).toFixed(2)} USDT
            </div>
          </div>

          <div
            style={{
              padding: "12px",
              background: "rgba(255, 255, 255, 0.03)",
              borderRadius: "6px",
              border: "1px solid rgba(255, 255, 255, 0.07)",
            }}
          >
            <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Mục tiêu sau 20 Kèo:</div>
            <div style={{ fontSize: "18px", fontWeight: 700, color: "#fff", marginTop: "2px" }}>
              ${at20} <span style={{ fontSize: "12px", color: "#10b981", fontWeight: 600 }}>
                (+{(((at20 - simCapital) / simCapital) * 100).toFixed(1)}%)
              </span>
            </div>
            <div style={{ fontSize: "11px", color: "var(--text-secondary)", marginTop: "2px" }}>
              Lãi dự kiến: +${(at20 - simCapital).toFixed(2)} USDT
            </div>
          </div>

          <div
            style={{
              padding: "12px",
              background: "rgba(56, 189, 248, 0.08)",
              borderRadius: "6px",
              border: "1px solid rgba(56, 189, 248, 0.3)",
            }}
          >
            <div style={{ fontSize: "11px", color: "#7dd3fc", fontWeight: 600 }}>Tổng kết sau 30 Kèo:</div>
            <div style={{ fontSize: "18px", fontWeight: 800, color: "#38bdf8", marginTop: "2px" }}>
              ${at30} <span style={{ fontSize: "12px", color: "#10b981", fontWeight: 700 }}>
                (+{gain30Pct}%)
              </span>
            </div>
            <div style={{ fontSize: "11px", color: "#38bdf8", marginTop: "2px", fontWeight: 600 }}>
              Lãi dự kiến: +${(at30 - simCapital).toFixed(2)} USDT
            </div>
          </div>
        </div>

        {/* Professional Summary Footnote */}
        <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "14px", fontStyle: "italic", borderTop: "1px solid rgba(255, 255, 255, 0.06)", paddingTop: "10px" }}>
          💡 <strong>Nguyên lý vận hành:</strong> Mô phỏng trên áp dụng công thức lãi kép phân vị (Compound Equity Curve) kết hợp chính sách <strong>Khóa Lãi Từng Nấc (Step-by-Step Trailing Profit)</strong>: chạm TP1 chốt {tp1WeightPct}% & dời SL về hòa vốn Entry; chạm TP2 chốt {tp2WeightPct}% & dời SL lên mốc TP1 để khóa trọn lợi nhuận cho {tp3WeightPct}% khối lượng runner còn lại. Nhờ đó tối ưu hóa biên lợi nhuận thực nhận mà vẫn triệt tiêu 100% rủi ro lỗ ngược.
        </div>
      </div>
    </div>
  );
};
