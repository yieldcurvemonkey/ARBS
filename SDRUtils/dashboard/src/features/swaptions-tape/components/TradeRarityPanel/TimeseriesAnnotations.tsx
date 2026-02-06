import { ReferenceArea, ReferenceDot, ReferenceLine } from 'recharts';
import { distributionStats, percentileRank } from './rarity.utils';

type TimeseriesAnnotationsProps = {
  distributionValues: number[];
  currentValue: number | null;
  currentTimeLabel: string | null;
  showSigmaBands: boolean;
  formatValue: (value: number) => string;
  showHighlight: boolean;
};

export function TimeseriesAnnotations({
  distributionValues,
  currentValue,
  currentTimeLabel,
  showSigmaBands,
  formatValue,
  showHighlight,
}: TimeseriesAnnotationsProps) {
  if (!distributionValues.length || currentValue === null) return null;
  const stats = distributionStats(distributionValues);
  if (!stats.count) return null;
  const percentile = percentileRank(currentValue, distributionValues);

  return (
    <>
      <ReferenceArea
        y1={stats.p25}
        y2={stats.p75}
        fill="#22d3ee"
        fillOpacity={0.1}
        strokeOpacity={0}
      />
      {showSigmaBands && (
        <>
          <ReferenceArea
            y1={stats.mean - stats.stddev}
            y2={stats.mean + stats.stddev}
            fill="#38bdf8"
            fillOpacity={0.05}
            strokeOpacity={0}
          />
          <ReferenceArea
            y1={stats.mean - stats.stddev * 2}
            y2={stats.mean + stats.stddev * 2}
            fill="#38bdf8"
            fillOpacity={0.03}
            strokeOpacity={0}
          />
        </>
      )}
      <ReferenceLine
        y={currentValue}
        stroke="#22d3ee"
        strokeDasharray="3 3"
        label={{
          position: 'right',
          value: `${formatValue(currentValue)} (P${Math.round(percentile)})`,
          fill: '#e2e8f0',
          fontSize: 10,
        }}
      />
      {showHighlight && currentTimeLabel && (
        <ReferenceDot
          x={currentTimeLabel}
          y={currentValue}
          r={6}
          fill="#22d3ee"
          stroke="#e2e8f0"
          className="animate-pulse"
        />
      )}
    </>
  );
}
