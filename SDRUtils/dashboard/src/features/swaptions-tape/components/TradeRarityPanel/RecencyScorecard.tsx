import { useEffect, useMemo, useState } from 'react';
import { Settings } from 'lucide-react';
import type { MetricConfig, SimilarityCriteria, StructureAnalyticsConfig } from './rarity.types';
import type { TapeRow } from '../../types/trade.types';
import {
  computeRank,
  computeFrequencyByPredicate,
  findLastSimilarByStructure,
  getMetricValue,
  getMetricValueByKey,
  isSimilarTrade,
} from './rarity.utils';

type Formatters = {
  formatNotional: (value: number | null | undefined) => string;
  formatMetricValue: (value: number | null | undefined, decimals?: number) => string;
  formatRate: (value: number | null | undefined, decimals?: number) => string;
  formatDurationMs: (value: number | null | undefined) => string;
  formatCount: (value: number | null | undefined) => string;
};

type RecencyScorecardProps = {
  selectedRow: TapeRow;
  rows: TapeRow[];
  config: StructureAnalyticsConfig;
  primaryMetric: MetricConfig;
  primaryValue: number | null;
  formatters: Formatters;
  primaryThreshold: number;
  sizeThresholdPct: number;
  onPrimaryThresholdChange: (value: number) => void;
  onSizeThresholdChange: (value: number) => void;
};

const LOOKBACK_DAYS = 90;

export function RecencyScorecard({
  selectedRow,
  rows,
  config,
  primaryMetric,
  primaryValue,
  formatters,
  primaryThreshold,
  sizeThresholdPct,
  onPrimaryThresholdChange,
  onSizeThresholdChange,
}: RecencyScorecardProps) {
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    setSettingsOpen(false);
  }, [config.packageType]);

  const currentNotional = getMetricValueByKey(selectedRow, 'total_notional');
  const sizeThreshold =
    currentNotional !== null
      ? (Math.abs(currentNotional) * sizeThresholdPct) / 100
      : null;

  const primaryCriteria: SimilarityCriteria = useMemo(
    () => ({
      ...config.similarityCriteria,
      threshold: primaryThreshold,
    }),
    [config.similarityCriteria, primaryThreshold],
  );

  const primaryMetricDecimals = primaryMetric.decimals ?? 2;
  const primaryThresholdLabel =
    primaryCriteria.mode === 'percentage_of'
      ? `+/-${(primaryThreshold * 100).toFixed(0)}%`
      : `+/-${primaryThreshold}${primaryMetric.unit ? ` ${primaryMetric.unit}` : ''}`;

  const { lastSimilarPrimary, lastSimilarSize, frequencyPrimary, frequencySize, largestRecord, primaryRecord, bucketRank, daysSinceSize } =
    useMemo(() => {
      const lastPrimary = findLastSimilarByStructure(
        selectedRow,
        rows,
        primaryCriteria,
      );
      const lastSize = sizeThreshold
        ? findLastByPredicate(
            selectedRow,
            rows,
            (candidate) => {
              const notional = getMetricValueByKey(candidate, 'total_notional');
              return notional !== null && Math.abs(notional) >= sizeThreshold;
            },
          )
        : null;

      const frequencyPrimary = computeFrequencyByPredicate(
        selectedRow,
        rows,
        (candidate) => isSimilarTrade(selectedRow, candidate, primaryCriteria),
        LOOKBACK_DAYS,
      );

      const frequencySize = sizeThreshold
        ? computeFrequencyByPredicate(
            selectedRow,
            rows,
            (candidate) => {
              const notional = getMetricValueByKey(candidate, 'total_notional');
              return notional !== null && Math.abs(notional) >= sizeThreshold;
            },
            LOOKBACK_DAYS,
          )
        : null;

      const notionalValues = rows
        .map((row) => ({ row, value: getMetricValueByKey(row, 'total_notional') }))
        .filter((entry) => entry.value !== null) as Array<{ row: TapeRow; value: number }>;

      const largestRecord = notionalValues.length
        ? notionalValues.reduce((max, entry) =>
            entry.value > max.value ? entry : max,
          )
        : null;

      const primaryValues = rows
        .map((row) => ({ row, value: getMetricValue(row, primaryMetric) }))
        .filter((entry) => entry.value !== null) as Array<{ row: TapeRow; value: number }>;

      const primaryRecord = primaryValues.length
        ? primaryValues.reduce((max, entry) =>
            entry.value > max.value ? entry : max,
          )
        : null;

      const bucketRank = currentNotional !== null && notionalValues.length
        ? computeRank(Math.abs(currentNotional), notionalValues.map((entry) => Math.abs(entry.value)))
        : null;

      const lastSizeRow = sizeThreshold
        ? notionalValues
            .filter((entry) => Math.abs(entry.value) >= sizeThreshold)
            .sort(
              (a, b) =>
                new Date(b.row.execution_start).getTime() -
                new Date(a.row.execution_start).getTime(),
            )[0]
        : null;

      const daysSinceSize = lastSizeRow
        ? Math.round(
            (new Date(selectedRow.execution_start).getTime() -
              new Date(lastSizeRow.row.execution_start).getTime()) /
              (24 * 60 * 60 * 1000),
          )
        : null;

      return {
        lastSimilarPrimary: lastPrimary,
        lastSimilarSize: lastSize,
        frequencyPrimary,
        frequencySize,
        largestRecord: largestRecord
          ? {
              daysAgo: 0,
              date: largestRecord.row.execution_start,
              value: largestRecord.value,
              tradeId: largestRecord.row.package_id,
            }
          : null,
        primaryRecord: primaryRecord
          ? {
              daysAgo: 0,
              date: primaryRecord.row.execution_start,
              value: primaryRecord.value,
              tradeId: primaryRecord.row.package_id,
            }
          : null,
        bucketRank,
        daysSinceSize,
      };
    }, [
      selectedRow,
      rows,
      primaryCriteria,
      sizeThreshold,
      primaryMetric,
      currentNotional,
    ]);

  const formatDate = (value?: string | null) => {
    if (!value) return '--';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '--';
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const formatDaysAgo = (days?: number | null) => {
    if (days === null || days === undefined) return '--';
    return `${days}d ago`;
  };

  const renderLastSimilar = (
    label: string,
    stat: typeof lastSimilarPrimary,
    formatValue: (value: number) => string,
  ) => (
    <div className="space-y-1">
      <div className="text-[10px] uppercase tracking-wide text-slate-400">
        {label}
      </div>
      <div className="text-[11px] text-slate-100 font-mono">
        {stat
          ? `${formatDaysAgo(stat.daysAgo)} (${formatDate(stat.date)}) - ${formatValue(
              stat.value,
            )}`
          : '--'}
      </div>
    </div>
  );

  const renderFrequency = (label: string, stat: typeof frequencyPrimary) => (
    <div className="space-y-1">
      <div className="text-[10px] uppercase tracking-wide text-slate-400">
        {label}
      </div>
      <div className="text-[11px] text-slate-100 font-mono">
        {stat
          ? `${formatters.formatCount(stat.count)} in ${stat.lookbackDays}d - avg 1 per ${stat.avgIntervalDays.toFixed(1)}d`
          : '--'}
      </div>
    </div>
  );

  const largestRatio =
    largestRecord && currentNotional !== null
      ? Math.abs(currentNotional) / Math.abs(largestRecord.value)
      : null;

  const primaryRatio =
    primaryRecord && primaryValue !== null
      ? primaryValue / primaryRecord.value
      : null;

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
      <div className="flex items-center justify-between">
        <div className="uppercase tracking-wide text-slate-400">Recency & Frequency</div>
        <button
          type="button"
          onClick={() => setSettingsOpen((open) => !open)}
          className="rounded border border-slate-700 p-1 text-slate-300 transition hover:border-slate-500 hover:text-slate-100"
          aria-label="Adjust similarity thresholds"
        >
          <Settings className="h-4 w-4" />
        </button>
      </div>
      {settingsOpen && (
        <div className="mt-2 grid gap-2 rounded border border-slate-800 bg-slate-950 p-2 text-[10px] text-slate-300">
          <label className="flex items-center justify-between gap-2">
            <span>Primary threshold</span>
            <input
              type="number"
              value={primaryThreshold}
              onChange={(event) =>
                onPrimaryThresholdChange(Number(event.target.value))
              }
              className="w-24 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[10px] text-slate-100"
            />
          </label>
          <label className="flex items-center justify-between gap-2">
            <span>Size threshold (%)</span>
            <input
              type="number"
              value={sizeThresholdPct}
              onChange={(event) =>
                onSizeThresholdChange(Number(event.target.value))
              }
              className="w-24 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[10px] text-slate-100"
            />
          </label>
        </div>
      )}
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div className="space-y-2">
          {renderLastSimilar(
            `Last similar by ${primaryMetric.label} (${primaryThresholdLabel})`,
            lastSimilarPrimary,
            (value) => formatters.formatMetricValue(value, primaryMetricDecimals),
          )}
          {renderFrequency(`Frequency (${primaryMetric.label})`, frequencyPrimary)}
        </div>
        <div className="space-y-2">
          {renderLastSimilar(
            `Last similar by size (>= ${sizeThresholdPct}%)`,
            lastSimilarSize,
            (value) => formatters.formatNotional(value),
          )}
          {renderFrequency(`Frequency (size >= ${sizeThresholdPct}%)`, frequencySize)}
        </div>
      </div>
      <div className="mt-3 grid gap-2 border-t border-slate-800/70 pt-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[10px] uppercase tracking-wide text-slate-400">
            Largest ever
          </span>
          <span className="font-mono text-slate-100">
            {largestRecord
              ? `${formatters.formatNotional(largestRecord.value)} on ${formatDate(
                  largestRecord.date,
                )}`
              : '--'}
          </span>
        </div>
        {largestRatio !== null && (
          <div className="text-[11px] text-slate-500">
            This trade is {(largestRatio * 100).toFixed(0)}% of record
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[10px] uppercase tracking-wide text-slate-400">
            {primaryMetric.label} record
          </span>
          <span className="font-mono text-slate-100">
            {primaryRecord
              ? `${formatters.formatMetricValue(
                  primaryRecord.value,
                  primaryMetricDecimals,
                )} on ${formatDate(primaryRecord.date)}`
              : '--'}
          </span>
        </div>
        {primaryRatio !== null && (
          <div className="text-[11px] text-slate-500">
            Current print is {(primaryRatio * 100).toFixed(0)}% of record
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[10px] uppercase tracking-wide text-slate-400">
            Bucket rank (size)
          </span>
          <span className="font-mono text-slate-100">
            {bucketRank && bucketRank.total > 0
              ? `#${bucketRank.rank} of ${bucketRank.total}`
              : '--'}
          </span>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[10px] uppercase tracking-wide text-slate-400">
            Days since &ge; size
          </span>
          <span className="font-mono text-slate-100">
            {daysSinceSize !== null ? `${daysSinceSize} days` : '--'}
          </span>
        </div>
      </div>
    </div>
  );
}

function findLastByPredicate(
  currentRow: TapeRow,
  rows: TapeRow[],
  predicate: (row: TapeRow) => boolean,
) {
  const currentTime = new Date(currentRow.execution_start).getTime();
  if (Number.isNaN(currentTime)) return null;
  let best: TapeRow | null = null;
  rows.forEach((candidate) => {
    if (!candidate.execution_start) return;
    if (candidate.package_id === currentRow.package_id) return;
    const candidateTime = new Date(candidate.execution_start).getTime();
    if (Number.isNaN(candidateTime)) return;
    if (candidateTime >= currentTime) return;
    if (!predicate(candidate)) return;
    if (!best || candidateTime > new Date(best.execution_start).getTime()) {
      best = candidate;
    }
  });
  if (!best) return null;
  const bestRow: TapeRow = best;
  const bestTime = new Date(bestRow.execution_start).getTime();
  return {
    daysAgo: Math.max(0, Math.round((currentTime - bestTime) / (24 * 60 * 60 * 1000))),
    date: bestRow.execution_start,
    value: getMetricValueByKey(bestRow, 'total_notional') ?? 0,
    tradeId: bestRow.package_id,
  };
}
