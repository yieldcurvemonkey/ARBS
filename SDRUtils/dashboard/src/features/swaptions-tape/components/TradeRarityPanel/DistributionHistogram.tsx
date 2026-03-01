import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type {
  DistributionStatistics,
  HistogramResult,
  MetricConfig,
  RarityDistributionBasis,
} from './rarity.types';

const CUSTY_COLOR = '#f59e0b';
const IDB_COLOR = '#38bdf8';

type ChartDataPoint = {
  index: number;
  binStart: number;
  binEnd: number;
  mid: number;
  count: number;
  custyCount: number;
  idbCount: number;
  cumulativePercent: number;
  dominance: 'payer' | 'receiver' | null;
  rawCount?: number;
  rawCustyCount?: number;
  rawIdbCount?: number;
};

const smoothSeries = (values: number[]): number[] => {
  if (values.length <= 2) return [...values];
  const bandwidth = Math.max(1, Math.floor(values.length / 6));
  return values.map((_, index) => {
    let weightedSum = 0;
    let weightTotal = 0;
    values.forEach((value, sampleIndex) => {
      const distance = (index - sampleIndex) / bandwidth;
      const weight = Math.exp(-0.5 * distance * distance);
      weightedSum += value * weight;
      weightTotal += weight;
    });
    return weightTotal > 0 ? weightedSum / weightTotal : values[index];
  });
};

const scaleToPeak = (values: number[], targetPeak: number): number[] => {
  if (!values.length) return values;
  const sourcePeak = Math.max(...values, 0);
  if (sourcePeak <= 0 || targetPeak <= 0) return values.map((value) => Math.max(0, value));
  const ratio = targetPeak / sourcePeak;
  return values.map((value) => Math.max(0, value * ratio));
};

const expandSingleBin = (
  points: ChartDataPoint[],
  binWidth: number,
): ChartDataPoint[] => {
  if (points.length !== 1) return points;
  const center = points[0];
  const halfWidth = binWidth > 0 ? binWidth / 2 : 0.5;
  return [
    {
      ...center,
      index: -1,
      mid: center.mid - halfWidth,
      count: 0,
      custyCount: 0,
      idbCount: 0,
      cumulativePercent: 0,
    },
    center,
    {
      ...center,
      index: 1,
      mid: center.mid + halfWidth,
      count: 0,
      custyCount: 0,
      idbCount: 0,
      cumulativePercent: 100,
    },
  ];
};

const buildCurveData = (
  points: ChartDataPoint[],
  binWidth: number,
  preserveSplitShape: boolean,
): ChartDataPoint[] => {
  const expanded = expandSingleBin(points, binWidth);
  if (!expanded.length) return [];

  const countSeries = expanded.map((point) => point.count);
  const custySeries = expanded.map((point) => point.custyCount);
  const idbSeries = expanded.map((point) => point.idbCount);

  const smoothCount = scaleToPeak(
    smoothSeries(countSeries),
    Math.max(...countSeries, 0),
  );

  let smoothCusty = scaleToPeak(
    smoothSeries(custySeries),
    Math.max(...custySeries, 0),
  );
  let smoothIdb = scaleToPeak(
    smoothSeries(idbSeries),
    Math.max(...idbSeries, 0),
  );

  if (preserveSplitShape) {
    const adjustedCusty: number[] = [];
    const adjustedIdb: number[] = [];

    smoothCount.forEach((totalValue, index) => {
      const splitSum = Math.max(0, (smoothCusty[index] ?? 0) + (smoothIdb[index] ?? 0));
      if (splitSum <= 0 || totalValue <= 0) {
        adjustedCusty.push(0);
        adjustedIdb.push(0);
        return;
      }
      const custyShare = (smoothCusty[index] ?? 0) / splitSum;
      const custyValue = Math.max(0, Math.min(totalValue, totalValue * custyShare));
      adjustedCusty.push(custyValue);
      adjustedIdb.push(Math.max(0, totalValue - custyValue));
    });

    smoothCusty = adjustedCusty;
    smoothIdb = adjustedIdb;
  }

  return expanded.map((point, index) => ({
    ...point,
    rawCount: point.count,
    rawCustyCount: point.custyCount,
    rawIdbCount: point.idbCount,
    count: smoothCount[index] ?? point.count,
    custyCount: smoothCusty[index] ?? point.custyCount,
    idbCount: smoothIdb[index] ?? point.idbCount,
  }));
};

type HistogramProps = {
  metricKey: string;
  metricLabel: string;
  metricUnit?: string;
  histogram: HistogramResult;
  stats: DistributionStatistics | null;
  currentValue: number | null;
  currentPercentile: number | null;
  basis: RarityDistributionBasis;
  overlayType?: string;
  overlayScatter?: Array<{ x: number; y: number }>;
  skewDominance?: Array<'payer' | 'receiver' | null>;
  metricOptions: MetricConfig[];
  onMetricChange: (key: string) => void;
  chartStyle: 'bar' | 'curve';
  onChartStyleChange: (style: 'bar' | 'curve') => void;
  formatValue: (value: number) => string;
  formatCount: (value: number | null) => string;
};

export function DistributionHistogram({
  metricKey,
  metricLabel,
  metricUnit,
  histogram,
  stats,
  currentValue,
  currentPercentile,
  basis,
  overlayType,
  overlayScatter,
  skewDominance,
  metricOptions,
  onMetricChange,
  chartStyle,
  onChartStyleChange,
  formatValue,
  formatCount,
}: HistogramProps) {
  const chartData: ChartDataPoint[] = histogram.bins.map((bin, index) => {
    const mid = (bin.binStart + bin.binEnd) / 2;
    return {
      index,
      binStart: bin.binStart,
      binEnd: bin.binEnd,
      mid,
      count: bin.count,
      custyCount: bin.custyCount,
      idbCount: bin.idbCount,
      cumulativePercent: bin.cumulativePercent,
      dominance: skewDominance ? skewDominance[index] : null,
    };
  });

  const hasCusty = chartData.some((point) => point.custyCount > 0);
  const hasIdb = chartData.some((point) => point.idbCount > 0);
  const showSplit = basis === 'combined' && hasCusty && hasIdb;
  const singleSeriesLabel =
    basis === 'combined'
      ? hasCusty
        ? 'Custy'
        : 'IDB'
      : basis === 'custy'
        ? 'Custy'
        : 'IDB';
  const singleSeriesColor =
    basis === 'combined'
      ? hasCusty
        ? CUSTY_COLOR
        : IDB_COLOR
      : basis === 'custy'
        ? CUSTY_COLOR
        : IDB_COLOR;
  const curveChartData = buildCurveData(chartData, histogram.binWidth, showSplit);

  const hasOverlayScatter =
    overlayType === 'breakeven' && Boolean(overlayScatter?.length);
  const showReference = overlayType === 'ratio_reference';
  const showIqrBand = stats && stats.count > 0;
  const xDomain: [number, number] | ['auto', 'auto'] = histogram.bins.length
    ? [
        histogram.bins[0].binStart,
        histogram.bins[histogram.bins.length - 1].binEnd,
      ]
    : ['auto', 'auto'];

  const indexByValue = (value: number): number | null => {
    if (!histogram.bins.length || !Number.isFinite(value)) return null;
    const lastIndex = histogram.bins.length - 1;
    for (let i = 0; i < histogram.bins.length; i += 1) {
      const bin = histogram.bins[i];
      if (!bin) continue;
      const isLast = i === lastIndex;
      if (value >= bin.binStart && (value < bin.binEnd || (isLast && value <= bin.binEnd))) {
        return i;
      }
    }
    if (value < histogram.bins[0].binStart) return 0;
    return lastIndex;
  };

  const currentBinIndex =
    currentValue !== null ? indexByValue(currentValue) : null;
  const currentMarkerY =
    currentBinIndex !== null && chartData[currentBinIndex]
      ? Math.max(0, chartData[currentBinIndex].count)
      : null;
  const iqrStartIndex = stats ? indexByValue(stats.p25) : null;
  const iqrEndIndex = stats ? indexByValue(stats.p75) : null;
  const referenceIndex = showReference ? indexByValue(2) : null;

  const markerData = skewDominance
    ? chartData
        .filter((item) => item.dominance)
        .map((item) => ({
          xBar: item.index,
          xCurve: item.mid,
          y: item.count + 0.5,
          dominance: item.dominance,
        }))
    : [];

  const overlayScatterByBin = hasOverlayScatter && overlayScatter
    ? overlayScatter
        .map((point) => {
          const index = indexByValue(point.x);
          if (index === null) return null;
          return { x: index, y: point.y };
        })
        .filter((point): point is { x: number; y: number } => point !== null)
    : [];

  const renderSeries = (style: 'bar' | 'curve') => {
    if (style === 'bar') {
      if (showSplit) {
        return (
          <>
            <Bar
              dataKey="custyCount"
              name="Custy"
              fill={CUSTY_COLOR}
              stackId="distribution"
              isAnimationActive={false}
            />
            <Bar
              dataKey="idbCount"
              name="IDB"
              fill={IDB_COLOR}
              stackId="distribution"
              isAnimationActive={false}
            />
          </>
        );
      }
      return (
        <Bar
          dataKey="count"
          name={singleSeriesLabel}
          fill={singleSeriesColor}
          isAnimationActive={false}
        />
      );
    }

    if (showSplit) {
      return (
        <>
          <Area
            type="monotone"
            dataKey="custyCount"
            name="Custy"
            fill={CUSTY_COLOR}
            fillOpacity={0.35}
            stroke={CUSTY_COLOR}
            strokeWidth={1.3}
            stackId="distribution"
            isAnimationActive={false}
          />
          <Area
            type="monotone"
            dataKey="idbCount"
            name="IDB"
            fill={IDB_COLOR}
            fillOpacity={0.35}
            stroke={IDB_COLOR}
            strokeWidth={1.3}
            stackId="distribution"
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="count"
            name="Combined"
            stroke="#cbd5e1"
            strokeWidth={1.2}
            dot={false}
            isAnimationActive={false}
          />
        </>
      );
    }

    return (
      <Area
        type="monotone"
        dataKey="count"
        name={singleSeriesLabel}
        fill={singleSeriesColor}
        fillOpacity={0.3}
        stroke={singleSeriesColor}
        strokeWidth={1.5}
        isAnimationActive={false}
      />
    );
  };

  const tooltipRenderer = ({ active, payload }: any) => {
    if (!active || !payload?.length) return null;
    const data = payload[0]?.payload;
    if (!data) return null;
    const countValue = Number.isFinite(data.rawCount) ? data.rawCount : data.count;
    const custyCount = Number.isFinite(data.rawCustyCount)
      ? data.rawCustyCount
      : data.custyCount;
    const idbCount = Number.isFinite(data.rawIdbCount) ? data.rawIdbCount : data.idbCount;
    return (
      <div className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200">
        <div className="font-semibold text-slate-100">
          {formatValue(data.binStart)} - {formatValue(data.binEnd)}
        </div>
        <div className="flex items-center justify-between gap-3">
          <span>Count</span>
          <span className="font-mono">{formatCount(countValue)}</span>
        </div>
        <div className="flex items-center justify-between gap-3">
          <span>Cumulative</span>
          <span className="font-mono">{data.cumulativePercent.toFixed(1)}%</span>
        </div>
        {showSplit && (
          <>
            <div className="flex items-center justify-between gap-3">
              <span>Custy</span>
              <span className="font-mono">{formatCount(custyCount)}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span>IDB</span>
              <span className="font-mono">{formatCount(idbCount)}</span>
            </div>
          </>
        )}
      </div>
    );
  };

  const formatBinTick = (value: number | string) => {
    const index = Number(value);
    if (!Number.isFinite(index)) return '';
    const mid = chartData[index]?.mid;
    if (!Number.isFinite(mid)) return '';
    return formatValue(mid as number);
  };

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-slate-400">
            Distribution: {metricLabel}
          </div>
          <div className="text-[10px] text-slate-500">
            {metricUnit ? `Units: ${metricUnit}` : ' '}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex overflow-hidden rounded border border-slate-700">
            {(['curve', 'bar'] as const).map((style) => {
              const isActive = style === chartStyle;
              return (
                <button
                  key={style}
                  type="button"
                  onClick={() => onChartStyleChange(style)}
                  className={`px-2 py-1 text-[10px] font-semibold uppercase tracking-wide transition ${
                    isActive
                      ? 'bg-slate-700 text-slate-100'
                      : 'text-slate-300 hover:bg-slate-800'
                  }`}
                >
                  {style}
                </button>
              );
            })}
          </div>
          <div className="inline-flex overflow-hidden rounded border border-slate-700">
            {metricOptions.map((option) => {
              const isActive = option.key === metricKey;
              return (
                <button
                  key={option.key}
                  type="button"
                  onClick={() => onMetricChange(option.key)}
                  className={`px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                    isActive
                      ? 'bg-slate-700 text-slate-100'
                      : 'text-slate-300 hover:bg-slate-800'
                  }`}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>
      <div className="mt-3 h-56 md:h-64 lg:h-72">
        <ResponsiveContainer width="100%" height="100%">
          {chartStyle === 'bar' ? (
            <BarChart data={chartData} barCategoryGap={0}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis
                dataKey="index"
                tick={{ fill: '#94a3b8', fontSize: 10 }}
                tickFormatter={formatBinTick}
                minTickGap={20}
              />
              <YAxis
                tick={{ fill: '#94a3b8', fontSize: 10 }}
                allowDecimals={false}
                tickFormatter={(value) => formatCount(value)}
              />
              {hasOverlayScatter && (
                <YAxis
                  yAxisId="overlay"
                  orientation="right"
                  tick={{ fill: '#94a3b8', fontSize: 10 }}
                  tickFormatter={(value) => formatValue(value)}
                />
              )}
              <Tooltip content={tooltipRenderer} />
              {showIqrBand && iqrStartIndex !== null && iqrEndIndex !== null && (
                <ReferenceArea
                  x1={iqrStartIndex}
                  x2={iqrEndIndex}
                  fill="#38bdf8"
                  fillOpacity={0.1}
                  strokeOpacity={0}
                />
              )}
              {referenceIndex !== null && (
                <ReferenceLine x={referenceIndex} stroke="#f472b6" strokeDasharray="4 4" />
              )}
              {currentBinIndex !== null && currentValue !== null && (
                <ReferenceLine
                  x={currentBinIndex}
                  stroke="#22d3ee"
                  strokeDasharray="3 3"
                  label={{
                    position: 'top',
                    value: `${formatValue(currentValue)}${
                      currentPercentile !== null ? ` (P${Math.round(currentPercentile)})` : ''
                    }`,
                    fill: '#e2e8f0',
                    fontSize: 10,
                  }}
                />
              )}
              {currentBinIndex !== null && currentMarkerY !== null && (
                <ReferenceDot
                  x={currentBinIndex}
                  y={currentMarkerY}
                  r={4}
                  fill="#22d3ee"
                  stroke="#e2e8f0"
                  strokeWidth={1}
                  label={{
                    value: 'current',
                    position: 'top',
                    fill: '#22d3ee',
                    fontSize: 10,
                  }}
                />
              )}
              {renderSeries('bar')}
              {hasOverlayScatter && overlayScatterByBin.length > 0 && (
                <Scatter
                  data={overlayScatterByBin}
                  yAxisId="overlay"
                  fill="#f472b6"
                  shape={(props: any) => {
                    const { cx, cy } = props;
                    return <circle cx={cx} cy={cy} r={2} fill="#f472b6" />;
                  }}
                />
              )}
              {markerData.length > 0 && (
                <Scatter
                  data={markerData.map((item) => ({
                    x: item.xBar,
                    y: item.y,
                    dominance: item.dominance,
                  }))}
                  shape={(props: any) => {
                    const { cx, cy, payload } = props;
                    const color = payload?.dominance === 'payer' ? '#60a5fa' : '#fb923c';
                    return <circle cx={cx} cy={cy} r={3} fill={color} />;
                  }}
                />
              )}
              <Legend
                verticalAlign="top"
                align="right"
                iconType="square"
                wrapperStyle={{ fontSize: '10px', color: '#94a3b8' }}
              />
            </BarChart>
          ) : (
            <ComposedChart data={curveChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis
                dataKey="mid"
                type="number"
                tick={{ fill: '#94a3b8', fontSize: 10 }}
                tickFormatter={formatValue}
                domain={xDomain}
                minTickGap={20}
              />
              <YAxis
                tick={{ fill: '#94a3b8', fontSize: 10 }}
                allowDecimals={false}
                tickFormatter={(value) => formatCount(value)}
              />
              {hasOverlayScatter && (
                <YAxis
                  yAxisId="overlay"
                  orientation="right"
                  tick={{ fill: '#94a3b8', fontSize: 10 }}
                  tickFormatter={(value) => formatValue(value)}
                />
              )}
              <Tooltip content={tooltipRenderer} />
              {showIqrBand && stats && (
                <ReferenceArea
                  x1={stats.p25}
                  x2={stats.p75}
                  fill="#38bdf8"
                  fillOpacity={0.1}
                  strokeOpacity={0}
                />
              )}
              {showReference && <ReferenceLine x={2} stroke="#f472b6" strokeDasharray="4 4" />}
              {currentValue !== null && (
                <ReferenceLine
                  x={currentValue}
                  stroke="#22d3ee"
                  strokeDasharray="3 3"
                  label={{
                    position: 'top',
                    value: `${formatValue(currentValue)}${
                      currentPercentile !== null ? ` (P${Math.round(currentPercentile)})` : ''
                    }`,
                    fill: '#e2e8f0',
                    fontSize: 10,
                  }}
                />
              )}
              {currentValue !== null && currentMarkerY !== null && (
                <ReferenceDot
                  x={currentValue}
                  y={currentMarkerY}
                  r={4}
                  fill="#22d3ee"
                  stroke="#e2e8f0"
                  strokeWidth={1}
                  label={{
                    value: 'current',
                    position: 'top',
                    fill: '#22d3ee',
                    fontSize: 10,
                  }}
                />
              )}
              {renderSeries('curve')}
              {hasOverlayScatter && overlayScatter && (
                <Scatter
                  data={overlayScatter}
                  yAxisId="overlay"
                  fill="#f472b6"
                  shape={(props: any) => {
                    const { cx, cy } = props;
                    return <circle cx={cx} cy={cy} r={2} fill="#f472b6" />;
                  }}
                />
              )}
              {markerData.length > 0 && (
                <Scatter
                  data={markerData.map((item) => ({
                    x: item.xCurve,
                    y: item.y,
                    dominance: item.dominance,
                  }))}
                  shape={(props: any) => {
                    const { cx, cy, payload } = props;
                    const color = payload?.dominance === 'payer' ? '#60a5fa' : '#fb923c';
                    return <circle cx={cx} cy={cy} r={3} fill={color} />;
                  }}
                />
              )}
              <Legend
                verticalAlign="top"
                align="right"
                iconType="square"
                wrapperStyle={{ fontSize: '10px', color: '#94a3b8' }}
              />
            </ComposedChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
