"use client";

import { memo, useCallback, useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Customized,
  LabelList,
  ReferenceArea,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  buildDirectionalSparklineData,
  buildVolFlowSparklineData,
  computeDirectionalDomain,
  computeVolFlowDomain,
  formatCompactNotional,
  findPeakImbalance,
  findSteepestSegment,
} from "./quadrantSparkline.utils";
import type {
  QuadrantTradeFlows,
  SparklineMode,
  SparklinePoint,
  SteepestSegment,
  VolFlowAxisMetric,
} from "./quadrantSparkline.types";

const DIRECTION_COLORS: Record<
  "receiver" | "payer" | "balanced",
  string
> = {
  receiver: "#22d3ee",
  payer: "#4ade80",
  balanced: "#94a3b8",
};

const BASELINE_COLOR = "#64748b";
const VOL_FLOW_COLOR = "#fbbf24";
const VOL_FLOW_COMPARISON_COLOR = "#fef3c7";
const AS_OF_LINE_COLOR = "#ef4444";
const SPARKLINE_TIME_TICK_MS = 30 * 60 * 1000;

function formatYAxisTick(value: number): string {
  if (!Number.isFinite(value)) return "";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) {
    return `${(value / 1_000_000_000).toFixed(1)}b`;
  }
  if (abs >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}m`;
  }
  if (abs >= 1_000) {
    return `${(value / 1_000).toFixed(1)}k`;
  }
  if (abs >= 100) {
    return value.toFixed(0);
  }
  if (abs >= 10) {
    return value.toFixed(1);
  }
  return value.toFixed(2);
}

function cumulativeValueAt(
  points: SparklinePoint[],
  timestamp: number,
): number {
  if (!points.length || !Number.isFinite(timestamp)) return 0;
  let cumulative = 0;
  for (let index = 0; index < points.length; index += 1) {
    const point = points[index];
    if (!Number.isFinite(point.timestamp)) continue;
    if (point.timestamp > timestamp) break;
    if (Number.isFinite(point.cumulativeValue)) {
      cumulative = Number(point.cumulativeValue);
    }
  }
  return cumulative;
}

function sliceSeriesToDomain(
  points: SparklinePoint[],
  domain: [number, number],
  seriesPrefix: string,
): SparklinePoint[] {
  if (!points.length) return [];
  const [start, end] = domain;
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    return points;
  }

  const startValue = cumulativeValueAt(points, start);
  const endValue = cumulativeValueAt(points, end);
  const inRangePoints = points.filter(
    (point) =>
      Number.isFinite(point.timestamp) &&
      point.timestamp >= start &&
      point.timestamp <= end,
  );

  const windowedPoints: SparklinePoint[] = [
    {
      timestamp: start,
      cumulativeValue: startValue,
      tradeIndex: -1,
      tradeValue: 0,
      tradeId: `${seriesPrefix}-window-start`,
      isBaseline: true,
    },
    ...inRangePoints,
  ];

  const lastPoint = windowedPoints[windowedPoints.length - 1];
  if (!lastPoint || lastPoint.timestamp < end) {
    windowedPoints.push({
      timestamp: end,
      cumulativeValue: endValue,
      tradeIndex: -1,
      tradeValue: 0,
      tradeId: `${seriesPrefix}-window-end`,
    });
  }

  return windowedPoints;
}

type SingleTradeStemProps = {
  points: SparklinePoint[];
  xAxisMap?: Record<string, any>;
  yAxisMap?: Record<string, any>;
  stroke: string;
};

function SingleTradeStem({
  points,
  xAxisMap,
  yAxisMap,
  stroke,
}: SingleTradeStemProps) {
  if (points.length < 2) return null;
  const tradePoint =
    [...points].reverse().find((point) => point.tradeIndex >= 0) ?? null;
  if (!tradePoint || !Number.isFinite(tradePoint.timestamp)) return null;
  const xAxis = xAxisMap ? Object.values(xAxisMap)[0] : null;
  const yAxis = yAxisMap ? Object.values(yAxisMap)[0] : null;
  const xScale = xAxis?.scale;
  const yScale = yAxis?.scale;
  if (!xScale || !yScale) return null;
  const x = xScale(tradePoint.timestamp);
  const y = yScale(tradePoint.cumulativeValue);
  const yZero = yScale(0);
  if (
    [x, y, yZero].some(
      (value) => typeof value !== "number" || Number.isNaN(value),
    )
  ) {
    return null;
  }
  return (
    <line
      x1={x}
      x2={x}
      y1={yZero}
      y2={y}
      stroke={stroke}
      strokeWidth={2}
    />
  );
}

export type QuadrantSparklineProps = {
  trades: QuadrantTradeFlows[];
  mode: SparklineMode;
  directionColor: "receiver" | "payer" | "balanced";
  volFlowMetric?: VolFlowAxisMetric;
  comparisonPoints?: SparklinePoint[];
  xDomainOverride?: [number, number] | null;
  asOfTimestamp?: number | null;
  width?: number;
  height?: number;
  showMarker?: boolean;
  showFill?: boolean;
  showEndLabel?: boolean;
  formatValue?: (value: number | null | undefined) => string;
  onPointClick?: (tradeId: string) => void;
};

const renderBaselinePlaceholder = (
  height: number,
  mode: SparklineMode,
) => {
  if (mode === "vol_flow") {
    return <div className="h-full w-full" />;
  }
  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 100 ${height}`}
      preserveAspectRatio="none"
    >
      <line
        x1="0"
        x2="100"
        y1={height / 2}
        y2={height / 2}
        stroke={BASELINE_COLOR}
        strokeDasharray="2 2"
        strokeWidth={1}
      />
    </svg>
  );
};

type SteepestSegmentLabelProps = {
  segment: SteepestSegment;
  label: string;
  color: string;
  xAxisMap?: Record<string, any>;
  yAxisMap?: Record<string, any>;
};

function SteepestSegmentLabel({
  segment,
  label,
  color,
  xAxisMap,
  yAxisMap,
}: SteepestSegmentLabelProps) {
  const xAxis = xAxisMap ? Object.values(xAxisMap)[0] : null;
  const yAxis = yAxisMap ? Object.values(yAxisMap)[0] : null;
  const xScale = xAxis?.scale;
  const yScale = yAxis?.scale;
  if (!xScale || !yScale) return null;
  const x1 = xScale(segment.startTimestamp);
  const x2 = xScale(segment.endTimestamp);
  const y = yScale(segment.endCumulative);
  if (
    [x1, x2, y].some(
      (value) => typeof value !== "number" || Number.isNaN(value),
    )
  ) {
    return null;
  }
  const xMid = (x1 + x2) / 2;
  let yLabel = y - 6;
  if (yLabel < 8) yLabel = y + 12;
  return (
    <text
      x={xMid}
      y={yLabel}
      textAnchor="middle"
      fill={color}
      fontSize={9}
      fontFamily="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, Courier New, monospace"
    >
      {label}
    </text>
  );
}

function formatSegmentTime(value: number): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
  });
}

type SparklineTooltipProps = {
  active?: boolean;
  payload?: Array<{ payload?: SparklinePoint }>;
  mode: SparklineMode;
  volFlowMetric: VolFlowAxisMetric;
  formatValue: (value: number | null | undefined) => string;
  onSelect?: (tradeId: string) => void;
};

function SparklineTooltip({
  active,
  payload,
  mode,
  volFlowMetric,
  formatValue,
  onSelect,
}: SparklineTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const point =
    payload
      .map((entry) => entry?.payload)
      .find((entry) => entry && entry.tradeIndex >= 0) || payload[0]?.payload;
  if (!point || point.tradeIndex < 0) return null;
  const handleClick = () => {
    if (!onSelect || !point.tradeId) return;
    onSelect(point.tradeId);
  };
  const tradeLabel = point.packageType ? point.packageType : "Trade";
  const timeLabel = formatSegmentTime(point.timestamp);
  const platform =
    point.platform === "idb" ? "IDB" : point.platform === "custy" ? "Custy" : "--";
  const flowMetricLabel =
    volFlowMetric === "gamma"
      ? "gamma01"
      : volFlowMetric === "notional"
        ? "notional"
        : "vega01";
  const tradeValueLabel =
    mode === "vol_flow"
      ? `Trade ${flowMetricLabel}: ${formatValue(point.tradeValue)}`
      : `Trade net: ${formatValue(point.tradeValue)}`;
  const cumulativeLabel =
    mode === "vol_flow"
      ? `Cumulative: ${formatValue(point.cumulativeValue)}`
      : `Cumulative: ${formatValue(point.cumulativeValue)}`;
  const economicLabel =
    mode === "net_directional" && Number.isFinite(point.economicNotional as number)
      ? `Econ: ${formatCompactNotional(point.economicNotional)}`
      : null;
  const deltaNeutralLabel =
    mode === "vol_flow" && point.isDeltaNeutral ? "Delta-neutral" : null;

  return (
    <div
      className="rounded border border-slate-700 bg-slate-950/95 px-2 py-1 text-[10px] text-slate-100 shadow"
      style={{ cursor: onSelect ? "pointer" : "default" }}
      onClick={onSelect ? handleClick : undefined}
    >
      <div className="flex items-center justify-between gap-2 text-[9px] text-slate-400">
        <span>{timeLabel}</span>
        <span>{platform}</span>
      </div>
      <div className="mt-0.5 text-[10px] font-semibold text-slate-100">
        {tradeLabel}
      </div>
      <div className="mt-0.5 font-mono text-[10px] text-slate-100">
        {tradeValueLabel}
      </div>
      <div className="font-mono text-[10px] text-slate-300">
        {cumulativeLabel}
      </div>
      {economicLabel && (
        <div className="text-[9px] text-slate-400">{economicLabel}</div>
      )}
      {deltaNeutralLabel && (
        <div className="text-[9px] text-amber-300">{deltaNeutralLabel}</div>
      )}
      {onSelect && (
        <div className="mt-0.5 text-[9px] text-slate-400">
          Click to select trade
        </div>
      )}
    </div>
  );
}

export const QuadrantSparkline = memo(function QuadrantSparkline({
  trades,
  mode,
  directionColor,
  volFlowMetric = "vega",
  comparisonPoints,
  xDomainOverride,
  asOfTimestamp,
  height = 120,
  showMarker = true,
  showFill = true,
  showEndLabel = true,
  formatValue = (value: number | null | undefined) => `${value ?? 0}`,
  onPointClick,
}: QuadrantSparklineProps) {
  const lineColor =
    mode === "vol_flow" ? VOL_FLOW_COLOR : DIRECTION_COLORS[directionColor];
  const directionalPoints = useMemo(
    () => buildDirectionalSparklineData(trades),
    [trades],
  );
  const volFlowPoints = useMemo(
    () => buildVolFlowSparklineData(trades, volFlowMetric),
    [trades, volFlowMetric],
  );
  const comparisonSeriesPoints = useMemo(
    () =>
      mode === "vol_flow" && Array.isArray(comparisonPoints)
        ? comparisonPoints
        : [],
    [comparisonPoints, mode],
  );
  const points = mode === "vol_flow" ? volFlowPoints : directionalPoints;
  const showAxisTicks = mode === "vol_flow" && height >= 96;
  const showYAxis = mode === "vol_flow" && height >= 96;
  const showGridLines = mode === "vol_flow" && height >= 96;
  const rightMargin = showEndLabel ? 30 : 6;
  const chartMargin = {
    top: showAxisTicks ? 8 : 4,
    right: rightMargin,
    bottom: showAxisTicks ? 24 : 2,
    left: showYAxis ? 44 : 0,
  };

  const directionalDomain = useMemo(
    () => computeDirectionalDomain(directionalPoints),
    [directionalPoints],
  );
  const volFlowDomain = useMemo(
    () => computeVolFlowDomain(volFlowPoints),
    [volFlowPoints],
  );
  const volFlowDomainWithComparison = useMemo((): [number, number] => {
    if (!comparisonSeriesPoints.length) return volFlowDomain;
    const values = [...volFlowPoints, ...comparisonSeriesPoints]
      .map((point) => point.cumulativeValue)
      .filter((value) => Number.isFinite(value));
    if (!values.length) return volFlowDomain;
    const maxValue = Math.max(...values, 0);
    if (!Number.isFinite(maxValue) || maxValue <= 0) return [0, 1];
    return [0, maxValue * 1.1];
  }, [comparisonSeriesPoints, volFlowDomain, volFlowPoints]);
  const yDomain =
    mode === "vol_flow" ? volFlowDomainWithComparison : directionalDomain;
  const yTicks = useMemo(() => {
    if (!showYAxis) return undefined;
    const [minValue, maxValue] = yDomain;
    if (!Number.isFinite(minValue) || !Number.isFinite(maxValue)) {
      return undefined;
    }
    if (maxValue <= minValue) return [minValue];
    const targetTickCount = height >= 120 ? 7 : 6;
    const step = (maxValue - minValue) / (targetTickCount - 1);
    if (!Number.isFinite(step) || step <= 0) return [minValue, maxValue];
    const ticks = Array.from({ length: targetTickCount }, (_, index) =>
      Number((minValue + step * index).toPrecision(12)),
    );
    return Array.from(new Set(ticks));
  }, [height, showYAxis, yDomain]);
  const defaultXDomain = useMemo((): [number, number] => {
    if (!points.length) return [0, 1];
    const timestamps = points.map((point) => point.timestamp);
    const minValue = Math.min(...timestamps);
    const maxValue = Math.max(...timestamps);
    const pad = minValue === maxValue ? 1 : 0;
    return [minValue - pad, maxValue + pad];
  }, [points]);
  const xDomain = useMemo((): [number, number] => {
    if (
      xDomainOverride &&
      Number.isFinite(xDomainOverride[0]) &&
      Number.isFinite(xDomainOverride[1]) &&
      xDomainOverride[0] < xDomainOverride[1]
    ) {
      return xDomainOverride;
    }
    return defaultXDomain;
  }, [defaultXDomain, xDomainOverride]);
  const asOfX = useMemo(() => {
    if (asOfTimestamp === null || asOfTimestamp === undefined) return null;
    if (!Number.isFinite(asOfTimestamp)) return null;
    const value = Number(asOfTimestamp);
    if (value < xDomain[0] || value > xDomain[1]) return null;
    return value;
  }, [asOfTimestamp, xDomain]);
  const xTicks = useMemo(() => {
    if (!showAxisTicks) return undefined;
    const [minValue, maxValue] = xDomain;
    if (!Number.isFinite(minValue) || !Number.isFinite(maxValue)) {
      return undefined;
    }
    if (minValue === maxValue) return [minValue];
    const alignedStart =
      Math.ceil(minValue / SPARKLINE_TIME_TICK_MS) * SPARKLINE_TIME_TICK_MS;
    const ticks: number[] = [minValue];
    for (
      let timestamp = alignedStart;
      timestamp < maxValue;
      timestamp += SPARKLINE_TIME_TICK_MS
    ) {
      ticks.push(timestamp);
    }
    ticks.push(maxValue);
    const unique = Array.from(new Set(ticks.map((value) => Number(value)))).sort(
      (left, right) => left - right,
    );
    return unique;
  }, [showAxisTicks, xDomain]);
  const displayPoints = useMemo(
    () => sliceSeriesToDomain(points, xDomain, "main"),
    [points, xDomain],
  );
  const displayComparisonPoints = useMemo(
    () => sliceSeriesToDomain(comparisonSeriesPoints, xDomain, "comparison"),
    [comparisonSeriesPoints, xDomain],
  );
  const visibleTradeCount = useMemo(
    () =>
      displayPoints.filter((point) => (point.tradeIndex ?? -1) >= 0).length,
    [displayPoints],
  );
  const tradeCount = visibleTradeCount;
  const showLine = tradeCount > 1;
  const showDots = tradeCount > 0;
  const showSingleTradeStem = tradeCount === 1;

  const peakPoint = useMemo(() => {
    if (!showMarker) return null;
    return findPeakImbalance(directionalPoints);
  }, [directionalPoints, showMarker]);

  const steepestSegment = useMemo(() => {
    if (!showMarker) return null;
    return findSteepestSegment(volFlowPoints);
  }, [showMarker, volFlowPoints]);

  const steepestLabel = useMemo(() => {
    if (!steepestSegment) return null;
    const notional = formatValue(steepestSegment.notionalInWindow);
    const durationMinutes = Math.round(steepestSegment.durationMinutes);
    const durationLabel = durationMinutes <= 0 ? "<1m" : `${durationMinutes}m`;
    const start = formatSegmentTime(steepestSegment.startTimestamp);
    const end = formatSegmentTime(steepestSegment.endTimestamp);
    return `Peak: ${notional} in ${durationLabel} (${start}-${end})`;
  }, [formatValue, steepestSegment]);

  const renderDot = useCallback(
    (props: any) => {
      const { cx, cy, payload } = props;
      const dotKey = `${payload?.tradeId ?? "trade"}-${
        payload?.tradeIndex ?? props.index ?? 0
      }-${payload?.timestamp ?? ""}`;
      if (!payload || payload.tradeIndex < 0 || cx === null || cy === null) {
        return (
          <circle
            key={dotKey}
            cx={0}
            cy={0}
            r={0}
            fill="none"
            stroke="none"
          />
        );
      }
      const handleClick = () => {
        if (!onPointClick || !payload.tradeId) return;
        onPointClick(payload.tradeId as string);
      };
      return (
        <circle
          key={dotKey}
          cx={cx}
          cy={cy}
          r={3}
          fill="#f8fafc"
          stroke={lineColor}
          strokeWidth={1}
          style={{ cursor: onPointClick ? "pointer" : "default" }}
          onClick={onPointClick ? handleClick : undefined}
        />
      );
    },
    [lineColor, onPointClick],
  );

  if (!displayPoints.length) {
    return (
      <div style={{ height }} className="w-full">
        {renderBaselinePlaceholder(height, mode)}
      </div>
    );
  }

  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={displayPoints} margin={chartMargin}>
          <XAxis
            dataKey="timestamp"
            type="number"
            scale="time"
            domain={xDomain}
            allowDataOverflow
            hide={!showAxisTicks}
            axisLine={{ stroke: "#475569", strokeWidth: 1, opacity: 0.9 }}
            tickLine={{ stroke: "#64748b", strokeWidth: 1, opacity: 0.9 }}
            tickMargin={6}
            tick={{
              fill: "#cbd5e1",
              fontSize: 9,
              fontWeight: 600,
              fontFamily:
                "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, Courier New, monospace",
            }}
            tickFormatter={(value) => formatSegmentTime(Number(value))}
            ticks={xTicks}
            interval="preserveStartEnd"
          />
          <YAxis
            type="number"
            domain={yDomain}
            hide={!showYAxis}
            tickCount={yTicks?.length ?? 4}
            ticks={yTicks}
            width={40}
            axisLine={{ stroke: "#475569", strokeWidth: 1, opacity: 0.9 }}
            tickLine={{ stroke: "#64748b", strokeWidth: 1, opacity: 0.9 }}
            tickMargin={4}
            tick={{
              fill: "#cbd5e1",
              fontSize: 9,
              fontWeight: 600,
              fontFamily:
                "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, Courier New, monospace",
            }}
            tickFormatter={(value) => formatYAxisTick(Number(value))}
          />
          {showGridLines && (
            <CartesianGrid
              vertical={false}
              stroke="#1f2937"
              strokeOpacity={0.6}
              strokeWidth={0.5}
            />
          )}
          <Tooltip
            cursor={false}
            wrapperStyle={{
              pointerEvents: onPointClick ? "auto" : "none",
            }}
            content={
              <SparklineTooltip
                mode={mode}
                volFlowMetric={volFlowMetric}
                formatValue={formatValue}
                onSelect={onPointClick}
              />
            }
          />
          {mode === "net_directional" && (
            <ReferenceLine
              y={0}
              stroke={BASELINE_COLOR}
              strokeDasharray="2 2"
              strokeWidth={1}
            />
          )}
          {mode === "vol_flow" && asOfX !== null && (
            <ReferenceLine
              x={asOfX}
              stroke={AS_OF_LINE_COLOR}
              strokeDasharray="4 3"
              strokeWidth={1}
              ifOverflow="hidden"
            />
          )}
          {mode === "vol_flow" && displayComparisonPoints.length > 1 && (
            <Area
              type="stepAfter"
              data={displayComparisonPoints}
              dataKey="cumulativeValue"
              stroke={VOL_FLOW_COMPARISON_COLOR}
              strokeWidth={1.25}
              strokeDasharray="4 3"
              fill="none"
              fillOpacity={0}
              dot={false}
              activeDot={false}
              isAnimationActive={false}
              baseValue={0}
            />
          )}
          {mode === "vol_flow" && steepestSegment && showMarker && (
            <>
              <ReferenceArea
                x1={steepestSegment.startTimestamp}
                x2={steepestSegment.endTimestamp}
                y1={yDomain[0]}
                y2={yDomain[1]}
                fill={VOL_FLOW_COLOR}
                fillOpacity={0.15}
                strokeOpacity={0}
              />
              {steepestLabel && (
                <Customized
                  component={(props: any) => (
                    <SteepestSegmentLabel
                      {...props}
                      segment={steepestSegment}
                      label={steepestLabel}
                      color={VOL_FLOW_COLOR}
                    />
                  )}
                />
              )}
            </>
          )}
          {showSingleTradeStem && (
            <Customized
              component={(props: any) => (
                <SingleTradeStem
                  {...props}
                  points={displayPoints}
                  stroke={lineColor}
                />
              )}
            />
          )}
          <Area
            type="stepAfter"
            dataKey="cumulativeValue"
            stroke={showLine ? lineColor : "none"}
            strokeWidth={1.5}
            fill={showFill && showLine ? lineColor : "none"}
            fillOpacity={showFill && showLine ? 0.1 : 0}
            dot={showDots ? renderDot : false}
            isAnimationActive={false}
            baseValue={0}
          >
            {showEndLabel && tradeCount > 0 && (
              <LabelList
                dataKey="cumulativeValue"
                content={(props: any) => {
                  if (props.index !== displayPoints.length - 1) return null;
                  const x = (props.x ?? 0) + 26;
                  const y = props.y ?? 0;
                  return (
                    <text
                      x={x}
                      y={y}
                      fill={lineColor}
                      fontSize={9}
                      fontFamily="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, Courier New, monospace"
                      textAnchor="end"
                      dominantBaseline="middle"
                    >
                      {formatValue(props.value)}
                    </text>
                  );
                }}
              />
            )}
          </Area>
          {peakPoint && showMarker && mode === "net_directional" && (
            <ReferenceDot
              x={peakPoint.timestamp}
              y={peakPoint.cumulativeValue}
              r={4}
              fill={lineColor}
              stroke="none"
              label={({ x, y }: any) => (
                <text
                  x={x}
                  y={(y ?? 0) - 6}
                  textAnchor="middle"
                  fill={lineColor}
                  fontSize={9}
                  fontFamily="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, Courier New, monospace"
                >
                  {formatValue(peakPoint.cumulativeValue)}
                </text>
              )}
            />
          )}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
});
