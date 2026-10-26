import React, { useState, useEffect, useMemo } from "react";
import { BarChart3, LineChart as LineChartIcon, RefreshCw } from "lucide-react";
import { api } from "../services/api";
import type { PnLChartResponse, PnLChartItem } from "../types/api";

type TimeframeType = "daily" | "weekly" | "monthly";
type ChartStyleType = "bar" | "line";

export const PnLChart: React.FC = () => {
  const [chartData, setChartData] = useState<PnLChartResponse | null>(null);
  const [timeframe, setTimeframe] = useState<TimeframeType>("daily");
  const [chartStyle, setChartStyle] = useState<ChartStyleType>("bar");
  const [loading, setLoading] = useState<boolean>(false);
  const [hoveredItem, setHoveredItem] = useState<PnLChartItem | null>(null);

  const fetchChart = async () => {
    setLoading(true);
    try {
      const res = await api.getPnLChart();
      if (res && res.success) {
        setChartData(res);
      }
    } catch {
      // Ignored
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchChart();
  }, []);

  const currentSeries: PnLChartItem[] = useMemo(() => {
    if (!chartData) return [];
    if (timeframe === "weekly") return chartData.weekly || [];
    if (timeframe === "monthly") return chartData.monthly || [];
    return chartData.daily || [];
  }, [chartData, timeframe]);

  // Calculations for SVGs
  const svgWidth = 720;
  const svgHeight = 260;
  const padding = { top: 36, right: 30, bottom: 44, left: 50 };
  const innerW = svgWidth - padding.left - padding.right;
  const innerH = svgHeight - padding.top - padding.bottom;

  const { minVal, maxVal, zeroY } = useMemo(() => {
    if (currentSeries.length === 0) return { minVal: -10, maxVal: 10, zeroY: innerH / 2 };
    
    let vals: number[] = [];
    if (chartStyle === "bar") {
      vals = currentSeries.map((d) => d.net_pnl);
    } else {
      vals = currentSeries.map((d) => d.cumulative_pnl);
    }

    let min = Math.min(...vals, 0);
    let max = Math.max(...vals, 0);

    // Add 15% margin
    const span = Math.max(Math.abs(max - min), 1);
    min = min - span * 0.15;
    max = max + span * 0.15;

    const zeroRatio = (0 - min) / (max - min);
    const zY = padding.top + innerH * (1 - zeroRatio);

    return { minVal: min, maxVal: max, zeroY: zY };
  }, [currentSeries, chartStyle, innerH, padding.top]);

  const getY = (val: number) => {
    const ratio = (val - minVal) / (maxVal - minVal);
    return padding.top + innerH * (1 - ratio);
  };

  // KPI Quick Stats
  const todayItem = chartData?.daily?.[chartData.daily.length - 1];
  const thisWeekItem = chartData?.weekly?.[chartData.weekly.length - 1];
  const thisMonthItem = chartData?.monthly?.[chartData.monthly.length - 1];
  const allTimeNet = currentSeries.length > 0 ? currentSeries[currentSeries.length - 1].cumulative_pnl : 0;

  return (
    <div
      style={{
        background: "rgba(15, 23, 42, 0.75)",
        border: "1px solid rgba(255, 255, 255, 0.08)",
        borderRadius: "12px",
        padding: "20px",
        marginBottom: "24px",
        boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.3)",
      }}
    >
      {/* Header & Controls */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "12px",
          marginBottom: "16px",
          borderBottom: "1px solid rgba(255, 255, 255, 0.06)",
          paddingBottom: "14px",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <h3 style={{ fontSize: "16px", fontWeight: 700, color: "#fff", margin: 0 }}>
              Biểu Đồ Lãi / Lỗ Vị Thế (PnL Analysis)
            </h3>
            <span
              style={{
                fontSize: "11px",
                background: "rgba(56, 189, 248, 0.15)",
                color: "#38bdf8",
                border: "1px solid rgba(56, 189, 248, 0.3)",
                padding: "2px 8px",
                borderRadius: "12px",
                fontWeight: 600,
              }}
            >
              Chuẩn Kế Toán Binance
            </span>
          </div>
          <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "4px" }}>
            Ghi nhận biến động lợi nhuận thực nhận (đã trừ phí hoa hồng & funding) theo thời gian.
          </div>
        </div>

        {/* Toggles */}
        <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
          {/* Timeframe Selector */}
          <div
            style={{
              display: "flex",
              background: "rgba(0, 0, 0, 0.35)",
              padding: "3px",
              borderRadius: "8px",
              border: "1px solid rgba(255, 255, 255, 0.06)",
            }}
          >
            <button
              onClick={() => setTimeframe("daily")}
              style={{
                background: timeframe === "daily" ? "var(--color-primary)" : "transparent",
                color: timeframe === "daily" ? "#fff" : "var(--text-muted)",
                border: "none",
                borderRadius: "6px",
                padding: "4px 10px",
                fontSize: "12px",
                fontWeight: 600,
                cursor: "pointer",
                transition: "all 0.15s ease",
              }}
            >
              Theo Ngày
            </button>
            <button
              onClick={() => setTimeframe("weekly")}
              style={{
                background: timeframe === "weekly" ? "var(--color-primary)" : "transparent",
                color: timeframe === "weekly" ? "#fff" : "var(--text-muted)",
                border: "none",
                borderRadius: "6px",
                padding: "4px 10px",
                fontSize: "12px",
                fontWeight: 600,
                cursor: "pointer",
                transition: "all 0.15s ease",
              }}
            >
              Theo Tuần
            </button>
            <button
              onClick={() => setTimeframe("monthly")}
              style={{
                background: timeframe === "monthly" ? "var(--color-primary)" : "transparent",
                color: timeframe === "monthly" ? "#fff" : "var(--text-muted)",
                border: "none",
                borderRadius: "6px",
                padding: "4px 10px",
                fontSize: "12px",
                fontWeight: 600,
                cursor: "pointer",
                transition: "all 0.15s ease",
              }}
            >
              Theo Tháng
            </button>
          </div>

          {/* Chart Style Selector */}
          <div
            style={{
              display: "flex",
              background: "rgba(0, 0, 0, 0.35)",
              padding: "3px",
              borderRadius: "8px",
              border: "1px solid rgba(255, 255, 255, 0.06)",
            }}
          >
            <button
              onClick={() => setChartStyle("bar")}
              title="Biểu đồ Cột (PnL kỳ)"
              style={{
                background: chartStyle === "bar" ? "rgba(255, 255, 255, 0.15)" : "transparent",
                color: chartStyle === "bar" ? "#38bdf8" : "var(--text-muted)",
                border: "none",
                borderRadius: "6px",
                padding: "4px 8px",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: "4px",
                fontSize: "12px",
                fontWeight: 600,
              }}
            >
              <BarChart3 size={14} />
              <span>Cột PnL</span>
            </button>
            <button
              onClick={() => setChartStyle("line")}
              title="Biểu đồ Đường (Lũy kế vốn)"
              style={{
                background: chartStyle === "line" ? "rgba(255, 255, 255, 0.15)" : "transparent",
                color: chartStyle === "line" ? "#34d399" : "var(--text-muted)",
                border: "none",
                borderRadius: "6px",
                padding: "4px 8px",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: "4px",
                fontSize: "12px",
                fontWeight: 600,
              }}
            >
              <LineChartIcon size={14} />
              <span>Đường Lũy Kế</span>
            </button>
          </div>

          {/* Refresh Button */}
          <button
            className="btn btn-secondary btn-sm"
            onClick={fetchChart}
            disabled={loading}
            title="Đồng bộ lại dữ liệu"
          >
            <RefreshCw size={13} className={loading ? "spin" : ""} />
          </button>
        </div>
      </div>

      {/* KPI Cards Row */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          gap: "12px",
          marginBottom: "20px",
        }}
      >
        <div style={{ background: "rgba(0, 0, 0, 0.25)", padding: "10px 14px", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
          <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Hôm Nay</div>
          <div style={{ fontSize: "16px", fontWeight: 700, color: (todayItem?.net_pnl || 0) >= 0 ? "#10b981" : "#ef4444", marginTop: "2px" }}>
            {todayItem ? (todayItem.net_pnl >= 0 ? `+$${todayItem.net_pnl.toFixed(2)}` : `-$${Math.abs(todayItem.net_pnl).toFixed(2)}`) : "$0.00"}
          </div>
          <div style={{ fontSize: "10px", color: "var(--text-muted)" }}>
            WR: {todayItem ? `${todayItem.win_rate}% (${todayItem.win_count}W - ${todayItem.loss_count}L)` : "—"}
          </div>
        </div>

        <div style={{ background: "rgba(0, 0, 0, 0.25)", padding: "10px 14px", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
          <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Tuần Này</div>
          <div style={{ fontSize: "16px", fontWeight: 700, color: (thisWeekItem?.net_pnl || 0) >= 0 ? "#10b981" : "#ef4444", marginTop: "2px" }}>
            {thisWeekItem ? (thisWeekItem.net_pnl >= 0 ? `+$${thisWeekItem.net_pnl.toFixed(2)}` : `-$${Math.abs(thisWeekItem.net_pnl).toFixed(2)}`) : "$0.00"}
          </div>
          <div style={{ fontSize: "10px", color: "var(--text-muted)" }}>
            WR: {thisWeekItem ? `${thisWeekItem.win_rate}% (${thisWeekItem.win_count}W - ${thisWeekItem.loss_count}L)` : "—"}
          </div>
        </div>

        <div style={{ background: "rgba(0, 0, 0, 0.25)", padding: "10px 14px", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
          <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Tháng Này</div>
          <div style={{ fontSize: "16px", fontWeight: 700, color: (thisMonthItem?.net_pnl || 0) >= 0 ? "#10b981" : "#ef4444", marginTop: "2px" }}>
            {thisMonthItem ? (thisMonthItem.net_pnl >= 0 ? `+$${thisMonthItem.net_pnl.toFixed(2)}` : `-$${Math.abs(thisMonthItem.net_pnl).toFixed(2)}`) : "$0.00"}
          </div>
          <div style={{ fontSize: "10px", color: "var(--text-muted)" }}>
            WR: {thisMonthItem ? `${thisMonthItem.win_rate}% (${thisMonthItem.win_count}W - ${thisMonthItem.loss_count}L)` : "—"}
          </div>
        </div>

        <div style={{ background: "rgba(0, 0, 0, 0.25)", padding: "10px 14px", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
          <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Tổng Lũy Kế Toàn Kỳ</div>
          <div style={{ fontSize: "16px", fontWeight: 700, color: allTimeNet >= 0 ? "#10b981" : "#ef4444", marginTop: "2px" }}>
            {allTimeNet >= 0 ? `+$${allTimeNet.toFixed(2)}` : `-$${Math.abs(allTimeNet).toFixed(2)}`}
          </div>
          <div style={{ fontSize: "10px", color: "var(--text-muted)" }}>
            Từ {currentSeries[0]?.label || "—"} đến nay
          </div>
        </div>
      </div>

      {/* Main Interactive Chart Canvas */}
      <div style={{ position: "relative", width: "100%", overflowX: "auto" }}>
        {currentSeries.length === 0 ? (
          <div style={{ textAlign: "center", padding: "60px 20px", color: "var(--text-muted)" }}>
            Chưa có dữ liệu giao dịch đã đóng trong danh mục.
          </div>
        ) : (
          <svg
            viewBox={`0 0 ${svgWidth} ${svgHeight}`}
            style={{ width: "100%", height: "auto", display: "block" }}
            onMouseLeave={() => setHoveredItem(null)}
          >
            <defs>
              {/* Positive Bar Gradient */}
              <linearGradient id="barGradGreen" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#10b981" stopOpacity="0.9" />
                <stop offset="100%" stopColor="#059669" stopOpacity="0.4" />
              </linearGradient>

              {/* Negative Bar Gradient */}
              <linearGradient id="barGradRed" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#dc2626" stopOpacity="0.4" />
                <stop offset="100%" stopColor="#ef4444" stopOpacity="0.9" />
              </linearGradient>

              {/* Cumulative Line Area Gradient */}
              <linearGradient id="lineAreaGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={allTimeNet >= 0 ? "#10b981" : "#ef4444"} stopOpacity="0.35" />
                <stop offset="100%" stopColor={allTimeNet >= 0 ? "#10b981" : "#ef4444"} stopOpacity="0.0" />
              </linearGradient>
            </defs>

            {/* Zero Axis Line */}
            <line
              x1={padding.left}
              y1={zeroY}
              x2={svgWidth - padding.right}
              y2={zeroY}
              stroke="rgba(255, 255, 255, 0.25)"
              strokeDasharray="4 4"
              strokeWidth="1.5"
            />
            <text
              x={padding.left - 8}
              y={zeroY + 4}
              fill="rgba(255, 255, 255, 0.5)"
              fontSize="10"
              textAnchor="end"
              fontFamily="monospace"
            >
              $0
            </text>

            {/* Max / Min Y labels */}
            <text
              x={padding.left - 8}
              y={padding.top + 4}
              fill="rgba(255, 255, 255, 0.35)"
              fontSize="10"
              textAnchor="end"
              fontFamily="monospace"
            >
              {maxVal > 0 ? `+$${maxVal.toFixed(0)}` : `$${maxVal.toFixed(0)}`}
            </text>
            <text
              x={padding.left - 8}
              y={svgHeight - padding.bottom + 4}
              fill="rgba(255, 255, 255, 0.35)"
              fontSize="10"
              textAnchor="end"
              fontFamily="monospace"
            >
              {minVal < 0 ? `-$${Math.abs(minVal).toFixed(0)}` : `$${minVal.toFixed(0)}`}
            </text>

            {/* BAR CHART RENDERING */}
            {chartStyle === "bar" &&
              currentSeries.map((item, idx) => {
                const totalBars = currentSeries.length;
                const slotW = innerW / totalBars;
                const barW = Math.min(Math.max(slotW * 0.65, 8), 36);
                const x = padding.left + idx * slotW + (slotW - barW) / 2;

                const val = item.net_pnl;
                const yVal = getY(val);
                const isPositive = val >= 0;

                const barY = isPositive ? yVal : zeroY;
                const barH = Math.max(Math.abs(yVal - zeroY), 2);

                const isHovered = hoveredItem?.period_key === item.period_key;

                return (
                  <g
                    key={item.period_key}
                    onMouseEnter={() => {
                      setHoveredItem(item);
                    }}
                    style={{ cursor: "pointer" }}
                  >
                    {/* Hover highlight bar track */}
                    <rect
                      x={padding.left + idx * slotW}
                      y={padding.top}
                      width={slotW}
                      height={innerH}
                      fill={isHovered ? "rgba(255, 255, 255, 0.05)" : "transparent"}
                    />

                    {/* Actual PnL Bar */}
                    <rect
                      x={x}
                      y={barY}
                      width={barW}
                      height={barH}
                      rx={3}
                      fill={isPositive ? "url(#barGradGreen)" : "url(#barGradRed)"}
                      stroke={isHovered ? "#fff" : isPositive ? "#34d399" : "#f87171"}
                      strokeWidth={isHovered ? 2 : 1}
                      filter={isHovered ? "drop-shadow(0 0 6px rgba(255,255,255,0.4))" : undefined}
                    />

                    {/* Value text label */}
                    <text
                      x={x + barW / 2}
                      y={isPositive ? barY - 6 : barY + barH + 12}
                      fill={isPositive ? "#34d399" : "#f87171"}
                      fontSize="9"
                      fontWeight={700}
                      textAnchor="middle"
                      fontFamily="monospace"
                    >
                      {val >= 0 ? `+$${val.toFixed(1)}` : `-$${Math.abs(val).toFixed(1)}`}
                    </text>

                    {/* X-axis date label */}
                    <text
                      x={x + barW / 2}
                      y={svgHeight - 12}
                      fill={isHovered ? "#fff" : "rgba(255, 255, 255, 0.5)"}
                      fontSize="10"
                      fontWeight={isHovered ? 700 : 500}
                      textAnchor="middle"
                    >
                      {item.label}
                    </text>
                  </g>
                );
              })}

            {/* LINE CHART RENDERING (Cumulative Equity Curve) */}
            {chartStyle === "line" && (() => {
              const totalPts = currentSeries.length;
              if (totalPts === 0) return null;
              const slotW = innerW / Math.max(totalPts - 1, 1);

              const points = currentSeries.map((item, idx) => {
                const x = padding.left + idx * slotW;
                const y = getY(item.cumulative_pnl);
                return { x, y, item };
              });

              // Create smooth path
              const pathD = points.reduce((acc, pt, i) => {
                return i === 0 ? `M ${pt.x} ${pt.y}` : `${acc} L ${pt.x} ${pt.y}`;
              }, "");

              const areaD = `${pathD} L ${points[points.length - 1].x} ${zeroY} L ${points[0].x} ${zeroY} Z`;

              return (
                <g>
                  {/* Shaded Area Under Curve */}
                  <path d={areaD} fill="url(#lineAreaGrad)" />

                  {/* Cumulative Path Line */}
                  <path
                    d={pathD}
                    fill="none"
                    stroke={allTimeNet >= 0 ? "#10b981" : "#ef4444"}
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />

                  {/* Points & Hover Targets */}
                  {points.map((pt) => {
                    const isHovered = hoveredItem?.period_key === pt.item.period_key;
                    return (
                      <g
                        key={pt.item.period_key}
                        onMouseEnter={() => {
                          setHoveredItem(pt.item);
                        }}
                        style={{ cursor: "pointer" }}
                      >
                        <circle
                          cx={pt.x}
                          cy={pt.y}
                          r={isHovered ? 6 : 4}
                          fill={pt.item.cumulative_pnl >= 0 ? "#10b981" : "#ef4444"}
                          stroke="#fff"
                          strokeWidth={isHovered ? 2.5 : 1.5}
                        />

                        {/* Value text label */}
                        <text
                          x={pt.x}
                          y={pt.y - 10}
                          fill={pt.item.cumulative_pnl >= 0 ? "#34d399" : "#f87171"}
                          fontSize="9"
                          fontWeight={700}
                          textAnchor="middle"
                          fontFamily="monospace"
                        >
                          {pt.item.cumulative_pnl >= 0
                            ? `+$${pt.item.cumulative_pnl.toFixed(1)}`
                            : `-$${Math.abs(pt.item.cumulative_pnl).toFixed(1)}`}
                        </text>

                        {/* X-axis date label */}
                        <text
                          x={pt.x}
                          y={svgHeight - 12}
                          fill={isHovered ? "#fff" : "rgba(255, 255, 255, 0.5)"}
                          fontSize="10"
                          fontWeight={isHovered ? 700 : 500}
                          textAnchor="middle"
                        >
                          {pt.item.label}
                        </text>
                      </g>
                    );
                  })}
                </g>
              );
            })()}
          </svg>
        )}

        {/* Floating Tooltip Box */}
        {hoveredItem && (
          <div
            style={{
              position: "absolute",
              top: "12px",
              right: "16px",
              background: "rgba(15, 23, 42, 0.95)",
              border: "1px solid rgba(255, 255, 255, 0.15)",
              borderRadius: "8px",
              padding: "10px 14px",
              fontSize: "12px",
              boxShadow: "0 8px 20px rgba(0,0,0,0.5)",
              pointerEvents: "none",
              zIndex: 10,
              minWidth: "190px",
            }}
          >
            <div style={{ fontWeight: 700, color: "#fff", borderBottom: "1px solid rgba(255,255,255,0.1)", paddingBottom: "4px", marginBottom: "6px" }}>
              {hoveredItem.full_date || hoveredItem.label}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "3px" }}>
              <span style={{ color: "var(--text-muted)" }}>Lãi ròng kỳ:</span>
              <span
                style={{
                  fontWeight: 700,
                  color: hoveredItem.net_pnl >= 0 ? "#10b981" : "#ef4444",
                }}
              >
                {hoveredItem.net_pnl >= 0 ? `+$${hoveredItem.net_pnl.toFixed(2)}` : `-$${Math.abs(hoveredItem.net_pnl).toFixed(2)}`}
              </span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "3px" }}>
              <span style={{ color: "var(--text-muted)" }}>Lũy kế vốn:</span>
              <span
                style={{
                  fontWeight: 700,
                  color: hoveredItem.cumulative_pnl >= 0 ? "#34d399" : "#f87171",
                }}
              >
                {hoveredItem.cumulative_pnl >= 0 ? `+$${hoveredItem.cumulative_pnl.toFixed(2)}` : `-$${Math.abs(hoveredItem.cumulative_pnl).toFixed(2)}`}
              </span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "3px" }}>
              <span style={{ color: "var(--text-muted)" }}>Phí sàn Binance:</span>
              <span style={{ color: "#94a3b8" }}>-${hoveredItem.fees.toFixed(2)}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--text-muted)" }}>Tỷ lệ thắng (WR):</span>
              <span style={{ color: hoveredItem.win_rate >= 50 ? "#10b981" : "#f59e0b", fontWeight: 600 }}>
                {hoveredItem.win_rate}% ({hoveredItem.win_count}W / {hoveredItem.loss_count}L)
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
