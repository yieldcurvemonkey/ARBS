"use client";

import { memo, useCallback, useMemo } from "react";
import {
  Area,
  AreaChart,
  Customized,
  LabelList,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";

import {
  buildQuadrantSparklineData,
  computeSparklineDomain,
  findPeakImbalance,
} from "./quadrantSparkline.utils";
import type { QuadrantTrade, SparklinePoint } from "./quadrantSparkline.types";

const DIRECTION_COLORS: Record<
  "receiver" | "payer" | "balanced",
  string
> = {
  receiver: "#22d3ee",
  payer: "#4ade80",
  balanced: "#94a3b8",
};

const BASELINE_COLOR = "#64748b";

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
  const tradePoint = points[points.length - 1];
  if (!tradePoint || !Number.isFinite(tradePoint.timestamp)) return null;
  const xAxis = xAxisMap ? Object.values(xAxisMap)[0] : null;
  const yAxis = yAxisMap ? Object.values(yAxisMap)[0] : null;
  const xScale = xAxis?.scale;
  const yScale = yAxis?.scale;
  if (!xScale || !yScale) return null;
  const x = xScale(tradePoint.timestamp);
  const y = yScale(tradePoint.cumulativeNet);
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
  trades: QuadrantTrade[];
  directionColor: "receiver" | "payer" | "balanced";
  width?: number;
  height?: number;
  showPeakMarker?: boolean;
  showFill?: boolean;
  showEndLabel?: boolean;
  formatValue?: (value: number | null | undefined) => string;
  onPointClick?: (tradeId: string) => void;
};

const renderBaselinePlaceholder = (height: number) => (
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

export const QuadrantSparkline = memo(function QuadrantSparkline({
  trades,
  directionColor,
  height = 34,
  showPeakMarker = true,
  showFill = true,
  showEndLabel = true,
  formatValue = (value: number | null | undefined) => `${value ?? 0}`,
  onPointClick,
}: QuadrantSparklineProps) {
  const lineColor = DIRECTION_COLORS[directionColor];
  const points = useMemo(() => buildQuadrantSparklineData(trades), [trades]);
  const tradeCount = Math.max(points.length - 1, 0);
  const showLine = tradeCount > 1;
  const showDots = tradeCount > 0;
  const showSingleTradeStem = tradeCount === 1;
  const rightMargin = showEndLabel ? 30 : 6;

  const yDomain = useMemo(() => computeSparklineDomain(points), [points]);
  const xDomain = useMemo((): [number, number] => {
    if (!points.length) return [0, 1];
    const timestamps = points.map((point) => point.timestamp);
    const minValue = Math.min(...timestamps);
    const maxValue = Math.max(...timestamps);
    const pad = minValue === maxValue ? 1 : 0;
    return [minValue - pad, maxValue + pad];
  }, [points]);

  const peakPoint = useMemo(() => {
    if (!showPeakMarker) return null;
    return findPeakImbalance(points);
  }, [points, showPeakMarker]);

  const renderDot = useCallback(
    (props: any) => {
      const { cx, cy, payload } = props;
      if (!payload || payload.tradeIndex < 0 || cx === null || cy === null) {
        return null;
      }
      const handleClick = () => {
        if (!onPointClick || !payload.tradeId) return;
        onPointClick(payload.tradeId as string);
      };
      const dotKey =
        payload.tradeId ??
        payload.tradeIndex ??
        props.index ??
        `${cx}-${cy}`;
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

  if (!points.length) {
    return (
      <div style={{ height }} className="w-full">
        {renderBaselinePlaceholder(height)}
      </div>
    );
  }

  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart
          data={points}
          margin={{ top: 2, right: rightMargin, bottom: 2, left: 0 }}
        >
          <XAxis
            dataKey="timestamp"
            type="number"
            scale="time"
            domain={xDomain}
            hide
          />
          <YAxis type="number" domain={yDomain} hide />
          <ReferenceLine
            y={0}
            stroke={BASELINE_COLOR}
            strokeDasharray="2 2"
            strokeWidth={1}
          />
          {showSingleTradeStem && (
            <Customized
              component={(props: any) => (
                <SingleTradeStem
                  {...props}
                  points={points}
                  stroke={lineColor}
                />
              )}
            />
          )}
          <Area
            type="stepAfter"
            dataKey="cumulativeNet"
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
                dataKey="cumulativeNet"
                content={(props: any) => {
                  if (props.index !== points.length - 1) return null;
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
          {peakPoint && showPeakMarker && (
            <ReferenceDot
              x={peakPoint.timestamp}
              y={peakPoint.cumulativeNet}
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
                  {formatValue(peakPoint.cumulativeNet)}
                </text>
              )}
            />
          )}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
});
