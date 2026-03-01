import { useEffect, useMemo, useState } from 'react';
import { Settings } from 'lucide-react';
import type {
  SimilarityCriteria,
  StructureAnalyticsConfig,
} from './rarity.types';
import type { TapeRow } from '../../types/trade.types';
import {
  computeRank,
  computeFrequencyByPredicate,
  findLastSimilarByStructure,
  getMetricValueByKey,
  isSimilarTrade,
  getMetricsForStructure,
} from './rarity.utils';

type Formatters = {
  formatNotional: (value: number | null | undefined) => string;
  formatMetricValue: (value: number | null | undefined, decimals?: number) => string;
  formatRate: (value: number | null | undefined, decimals?: number) => string;
  formatDurationMs: (value: number | null | undefined) => string;
  formatCount: (value: number | null | undefined) => string;
};

export type RecencyMetricMode = 'vega01' | 'gamma01' | 'notional';

type RecencyScorecardProps = {
  selectedRow: TapeRow;
  rows: TapeRow[];
  config: StructureAnalyticsConfig;
  recencyMetricMode: RecencyMetricMode;
  formatters: Formatters;
  primaryThreshold: number;
  sizeThresholdPct: number;
  onRecencyMetricModeChange: (value: RecencyMetricMode) => void;
  onPrimaryThresholdChange: (value: number) => void;
  onSizeThresholdChange: (value: number) => void;
};

const LOOKBACK_DAYS = 90;
const VEGA_KEYS = [
  'straddle_vega01',
  'rr_vega01',
  'vs_vega01',
  'outright_vega01',
  'vega01',
] as const;
const GAMMA_KEYS = [
  'straddle_gamma01',
  'rr_gamma01',
  'vs_gamma01',
  'outright_gamma01',
  'gamma01',
] as const;
const NOTIONAL_KEYS = ['total_notional', 'notional'] as const;

export function RecencyScorecard({
  selectedRow,
  rows,
  config,
  recencyMetricMode,
  formatters,
  primaryThreshold,
  sizeThresholdPct,
  onRecencyMetricModeChange,
  onPrimaryThresholdChange,
  onSizeThresholdChange,
}: RecencyScorecardProps) {
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    setSettingsOpen(false);
  }, [config.packageType]);

  const recencyMetric = useMemo(() => {
    const candidateKeys: readonly string[] =
      recencyMetricMode === 'vega01'
        ? VEGA_KEYS
        : recencyMetricMode === 'gamma01'
          ? GAMMA_KEYS
          : NOTIONAL_KEYS;
    const structureMetrics = getMetricsForStructure(selectedRow.package_type);
    const structureMetric = structureMetrics.find((metric) =>
      candidateKeys.includes(metric.key),
    );

    const rowMatch = candidateKeys.find(
      (key) => getMetricValueByKey(selectedRow, key) !== null,
    );
    const populationMatch = candidateKeys.find((key) =>
      rows.some((row) => getMetricValueByKey(row, key) !== null),
    );

    const resolvedKey = structureMetric?.key || rowMatch || populationMatch || candidateKeys[0];

    return {
      key: resolvedKey,
      label:
        recencyMetricMode === 'vega01'
          ? 'Vega01'
          : recencyMetricMode === 'gamma01'
            ? 'Gamma01'
            : 'Notional',
      decimals: structureMetric?.decimals ?? 2,
      unit:
        structureMetric?.unit ||
        (recencyMetricMode === 'notional' ? 'USD' : 'USD/bp'),
    };
  }, [recencyMetricMode, rows, selectedRow]);

  const recencyValue = getMetricValueByKey(selectedRow, recencyMetric.key);
  const currentNotional = getMetricValueByKey(selectedRow, 'total_notional');
  const sizeThreshold =
    currentNotional !== null
      ? (Math.abs(currentNotional) * sizeThresholdPct) / 100
      : null;

  const primaryCriteria: SimilarityCriteria = useMemo(
    () => ({
      ...config.similarityCriteria,
      metric: recencyMetric.key,
      mode: 'absolute_range',
      threshold: primaryThreshold,
    }),
    [config.similarityCriteria, primaryThreshold, recencyMetric.key],
  );

  const recencyMetricDecimals = recencyMetric.decimals ?? 2;
  const primaryThresholdLabel = `+/-${primaryThreshold}${
    recencyMetric.unit ? ` ${recencyMetric.unit}` : ''
  }`;
  const formatRecencyValue = (value: number) =>
    recencyMetricMode === 'notional'
      ? formatters.formatNotional(value)
      : formatters.formatMetricValue(value, recencyMetricDecimals);

  const {
    lastSimilarPrimary,
    lastSimilarSize,
    frequencyPrimary,
    frequencySize,
    largestRecord,
    recencyMetricRecord,
    bucketRank,
    daysSinceSize,
  } = useMemo(() => {
    const lastPrimary = findLastSimilarByStructure(selectedRow, rows, primaryCriteria);
    const lastSize = sizeThreshold
      ? findLastByPredicate(selectedRow, rows, (candidate) => {
          const notional = getMetricValueByKey(candidate, 'total_notional');
          return notional !== null && Math.abs(notional) >= sizeThreshold;
        })
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

    const recencyMetricValues = rows
      .map((row) => ({ row, value: getMetricValueByKey(row, recencyMetric.key) }))
      .filter((entry) => entry.value !== null) as Array<{ row: TapeRow; value: number }>;

    const recencyMetricRecord = recencyMetricValues.length
      ? recencyMetricValues.reduce((max, entry) =>
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
      recencyMetricRecord: recencyMetricRecord
        ? {
            daysAgo: 0,
            date: recencyMetricRecord.row.execution_start,
            value: recencyMetricRecord.value,
            tradeId: recencyMetricRecord.row.package_id,
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
    recencyMetric.key,
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

  const recencyMetricRatio =
    recencyMetricRecord && recencyValue !== null
      ? recencyValue / recencyMetricRecord.value
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
            <span>Recency metric</span>
            <select
              value={recencyMetricMode}
              onChange={(event) =>
                onRecencyMetricModeChange(event.target.value as RecencyMetricMode)
              }
              className="w-24 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[10px] text-slate-100"
            >
              <option value="vega01">Vega01</option>
              <option value="gamma01">Gamma01</option>
              <option value="notional">Notional</option>
            </select>
          </label>
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
            `Last similar by ${recencyMetric.label} (${primaryThresholdLabel})`,
            lastSimilarPrimary,
            formatRecencyValue,
          )}
          {renderFrequency(`Frequency (${recencyMetric.label})`, frequencyPrimary)}
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
            {recencyMetric.label} record
          </span>
          <span className="font-mono text-slate-100">
            {recencyMetricRecord
              ? `${formatRecencyValue(recencyMetricRecord.value)} on ${formatDate(
                  recencyMetricRecord.date,
                )}`
              : '--'}
          </span>
        </div>
        {recencyMetricRatio !== null && (
          <div className="text-[11px] text-slate-500">
            Current print is {(recencyMetricRatio * 100).toFixed(0)}% of record
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
