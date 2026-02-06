import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ReferenceArea,
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
  formatValue,
  formatCount,
}: HistogramProps) {
  const chartData = histogram.bins.map((bin, index) => {
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

  const showSplit = basis === 'combined';
  const hasOverlayScatter = overlayType === 'breakeven' && overlayScatter?.length;
  const showReference = overlayType === 'ratio_reference';
  const showIqrBand = stats && stats.count > 0;

  const markerData = skewDominance
    ? chartData
        .filter((item) => item.dominance)
        .map((item) => ({
          mid: item.mid,
          y: item.count + 0.5,
          dominance: item.dominance,
        }))
    : [];

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
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis
              dataKey="mid"
              type="number"
              tick={{ fill: '#94a3b8', fontSize: 10 }}
              tickFormatter={formatValue}
              domain={['dataMin', 'dataMax']}
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
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const data = payload[0]?.payload;
                if (!data) return null;
                return (
                  <div className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200">
                    <div className="font-semibold text-slate-100">
                      {formatValue(data.binStart)} - {formatValue(data.binEnd)}
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span>Count</span>
                      <span className="font-mono">{formatCount(data.count)}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span>Cumulative</span>
                      <span className="font-mono">
                        {data.cumulativePercent.toFixed(1)}%
                      </span>
                    </div>
                    {showSplit && (
                      <>
                        <div className="flex items-center justify-between gap-3">
                          <span>Custy</span>
                          <span className="font-mono">
                            {formatCount(data.custyCount)}
                          </span>
                        </div>
                        <div className="flex items-center justify-between gap-3">
                          <span>IDB</span>
                          <span className="font-mono">
                            {formatCount(data.idbCount)}
                          </span>
                        </div>
                      </>
                    )}
                  </div>
                );
              }}
            />
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
                    currentPercentile !== null
                      ? ` (P${Math.round(currentPercentile)})`
                      : ''
                  }`,
                  fill: '#e2e8f0',
                  fontSize: 10,
                }}
              />
            )}
            {showSplit ? (
              <>
                <Bar
                  dataKey="custyCount"
                  name="Custy"
                  fill={CUSTY_COLOR}
                  stackId="a"
                  radius={[3, 3, 0, 0]}
                />
                <Bar
                  dataKey="idbCount"
                  name="IDB"
                  fill={IDB_COLOR}
                  stackId="a"
                  radius={[3, 3, 0, 0]}
                />
              </>
            ) : (
              <Bar
                dataKey="count"
                name={basis === 'custy' ? 'Custy' : 'IDB'}
                fill={basis === 'custy' ? CUSTY_COLOR : IDB_COLOR}
                radius={[3, 3, 0, 0]}
              />
            )}
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
                data={markerData}
                shape={(props: any) => {
                  const { cx, cy, payload } = props;
                  const color =
                    payload?.dominance === 'payer' ? '#60a5fa' : '#fb923c';
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
        </ResponsiveContainer>
      </div>
    </div>
  );
}
