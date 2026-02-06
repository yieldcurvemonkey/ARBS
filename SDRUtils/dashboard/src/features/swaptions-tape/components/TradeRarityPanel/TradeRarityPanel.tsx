import { memo, useEffect, useMemo, useState } from 'react';
import type { TapeRow } from '../../types/trade.types';
import type {
  MetricConfig,
  MetricDisplayValue,
  RarityDistributionBasis,
  RarityZone,
} from './rarity.types';
import {
  buildMoneynessLabel,
  buildNetPremiumSignLabel,
  buildNotionalProfileLabel,
  buildPercentileDescriptor,
  percentileRank,
  computeHistogram,
  distributionStats,
  ensurePremiumMetric,
  getMetricValue,
  getMetricValueByKey,
  isCustyPlatform,
  resolvePlatformIdentifier,
  resolveStructureConfig,
  splitRowsByPlatform,
} from './rarity.utils';
import { PercentileRankBadges } from './PercentileRankBadges';
import { DistributionHistogram } from './DistributionHistogram';
import { RecencyScorecard } from './RecencyScorecard';

export type TradeRarityPanelFormatters = {
  formatNotional: (value: number | null | undefined) => string;
  formatMetricValue: (value: number | null | undefined, decimals?: number) => string;
  formatRate: (value: number | null | undefined, decimals?: number) => string;
  formatCount: (value: number | null | undefined) => string;
  formatDurationMs: (value: number | null | undefined) => string;
};

export type TradeRarityPanelProps = {
  selectedRow: TapeRow;
  timeseriesRows: TapeRow[];
  formatters: TradeRarityPanelFormatters;
};

const DEFAULT_SAMPLE_WARNING = 20;

const basisOptions: Array<{ key: RarityDistributionBasis; label: string }> = [
  { key: 'combined', label: 'Combined' },
  { key: 'custy', label: 'Custy' },
  { key: 'idb', label: 'IDB' },
];

export const TradeRarityPanel = memo(function TradeRarityPanel({
  selectedRow,
  timeseriesRows,
  formatters,
}: TradeRarityPanelProps) {
  const config = useMemo(
    () => resolveStructureConfig(selectedRow.package_type),
    [selectedRow.package_type],
  );
  const baseMetrics = useMemo(
    () => ensurePremiumMetric([config.primaryMetric, ...config.secondaryMetrics]),
    [config.primaryMetric, config.secondaryMetrics],
  );

  const [basis, setBasis] = useState<RarityDistributionBasis>('combined');
  const [histogramMetricKey, setHistogramMetricKey] = useState(
    config.primaryMetric.key,
  );
  const [primaryThreshold, setPrimaryThreshold] = useState(
    config.similarityCriteria.threshold,
  );
  const [sizeThresholdPct, setSizeThresholdPct] = useState(80);

  useEffect(() => {
    setBasis('combined');
    setHistogramMetricKey(config.primaryMetric.key);
    setPrimaryThreshold(config.similarityCriteria.threshold);
  }, [config.primaryMetric.key, config.similarityCriteria.threshold]);

  const rowsByBasis = useMemo(() => splitRowsByPlatform(timeseriesRows), [
    timeseriesRows,
  ]);

  const activeRows = useMemo(() => {
    if (basis === 'custy') return rowsByBasis.custy;
    if (basis === 'idb') return rowsByBasis.idb;
    return rowsByBasis.combined;
  }, [basis, rowsByBasis]);

  const distributions = useMemo(() => {
    const map: Record<
      string,
      { values: number[]; stats: ReturnType<typeof distributionStats> }
    > = {};
    baseMetrics.forEach((metric) => {
      const values: number[] = [];
      activeRows.forEach((row) => {
        const value = getMetricValue(row, metric);
        if (value === null || Number.isNaN(value)) return;
        values.push(value);
      });
      map[metric.key] = {
        values,
        stats: distributionStats(values),
      };
    });
    return map;
  }, [activeRows, baseMetrics]);

  const primaryMetric = config.primaryMetric;
  const primaryDistribution = distributions[primaryMetric.key];
  const primaryValue = getMetricValue(selectedRow, primaryMetric);

  let primaryKey = primaryMetric.key;
  let primaryFallbackNote: string | null = null;
  if (primaryValue === null || (primaryDistribution?.values.length ?? 0) < DEFAULT_SAMPLE_WARNING) {
    primaryKey = 'total_premium';
    primaryFallbackNote =
      'Primary metric unavailable or small sample; defaulted to Premium.';
  }

  useEffect(() => {
    setHistogramMetricKey(primaryKey);
  }, [primaryKey]);

  const orderedMetrics = useMemo(() => {
    if (!baseMetrics.length) return baseMetrics;
    if (baseMetrics[0]?.key === primaryKey) return baseMetrics;
    const primaryMetric = baseMetrics.find((metric) => metric.key === primaryKey);
    if (!primaryMetric) return baseMetrics;
    return [
      primaryMetric,
      ...baseMetrics.filter((metric) => metric.key !== primaryKey),
    ];
  }, [baseMetrics, primaryKey]);

  const metricDisplayValues: MetricDisplayValue[] = useMemo(() => {
    const fallbackDescriptor: { zone: RarityZone; descriptor: string } = {
      zone: 'typical',
      descriptor: 'context',
    };
    return orderedMetrics.map((metric) => {
      const distribution = distributions[metric.key];
      const stats = distribution?.stats ?? null;
      const value = getMetricValue(selectedRow, metric);
      const sampleSize = distribution?.values.length ?? 0;
      let showPercentile =
        metric.percentile !== false && value !== null && sampleSize > 0;
      let percentValue = showPercentile
        ? percentileRank(value as number, distribution.values)
        : null;
      let percentileDescriptor = showPercentile
        ? buildPercentileDescriptor(percentValue as number, stats, value)
        : fallbackDescriptor;
      let descriptor = showPercentile
        ? percentileDescriptor.descriptor
        : metric.percentile === false
          ? 'context'
          : 'no data';
      let zone = showPercentile ? percentileDescriptor.zone : null;
      const warning =
        sampleSize > 0 && sampleSize < DEFAULT_SAMPLE_WARNING
          ? `Small sample (N=${sampleSize})`
          : null;
      let displayValue = formatMetricDisplay(metric, value, selectedRow, formatters);

      if (metric.key === 'straddle_dv01' && value !== null && Math.abs(value) < 1e-6) {
        displayValue = '--';
        showPercentile = false;
        percentValue = null;
        zone = 'typical';
        descriptor = 'straddle (net zero)';
      }

      return {
        key: metric.key,
        label: metric.label,
        value,
        displayValue,
        percentile: percentValue,
        zone,
        descriptor,
        sampleSize,
        derived: metric.derived,
        primary: metric.key === primaryKey,
        unit: metric.unit,
        formula: metric.formula,
        showPercentile,
        warning,
      };
    });
  }, [distributions, formatters, orderedMetrics, primaryKey, selectedRow]);

  const histogramMetric =
    baseMetrics.find((metric) => metric.key === histogramMetricKey) ||
    primaryMetric;

  const histogramValues = useMemo(() => {
    const values: number[] = [];
    const custyMask: boolean[] = [];
    const sourceRows =
      basis === 'custy'
        ? rowsByBasis.custy
        : basis === 'idb'
          ? rowsByBasis.idb
          : rowsByBasis.combined;
    sourceRows.forEach((row) => {
      const value = getMetricValue(row, histogramMetric);
      if (value === null || Number.isNaN(value)) return;
      values.push(value);
      if (basis === 'combined') {
        const platform = resolvePlatformIdentifier(row);
        custyMask.push(isCustyPlatform(platform));
      }
    });
    return { values, custyMask };
  }, [basis, histogramMetric, rowsByBasis]);

  const histogram = useMemo(() => {
    return computeHistogram(
      histogramValues.values,
      20,
      basis === 'combined' ? histogramValues.custyMask : undefined,
    );
  }, [basis, histogramValues]);

  const histogramStats = useMemo(
    () => distributionStats(histogramValues.values),
    [histogramValues.values],
  );

  const currentHistogramValue = getMetricValue(selectedRow, histogramMetric);
  const currentHistogramPercentile =
    currentHistogramValue !== null && histogramValues.values.length
      ? percentileRank(currentHistogramValue, histogramValues.values)
      : null;

  const overlayScatter = useMemo(() => {
    if (config.histogramOverlay !== 'breakeven') return undefined;
    if (histogramMetric.key !== 'straddle_bpvol_yr') return undefined;
    return activeRows
      .map((row) => {
        const x = getMetricValueByKey(row, 'straddle_bpvol_yr');
        const y = getMetricValueByKey(row, 'breakeven_width_bps');
        if (x === null || y === null) return null;
        return { x, y };
      })
      .filter((entry): entry is { x: number; y: number } => entry !== null);
  }, [activeRows, config.histogramOverlay, histogramMetric.key]);

  const skewDominance = useMemo(() => {
    if (config.histogramOverlay !== 'skew_direction') return undefined;
    if (histogramMetric.key !== 'rr_skew_bpvol') return undefined;
    if (!histogram.bins.length) return undefined;
    const dominance = histogram.bins.map(() => ({ payer: 0, receiver: 0 }));
    const min = histogram.bins[0].binStart;
    const max = histogram.bins[histogram.bins.length - 1].binEnd;
    const span = max - min;
    const binWidth = histogram.binWidth || (span === 0 ? 1 : span / histogram.bins.length);

    activeRows.forEach((row) => {
      const value = getMetricValueByKey(row, 'rr_skew_bpvol');
      const payer = getMetricValueByKey(row, 'rr_payer_skew');
      const receiver = getMetricValueByKey(row, 'rr_receiver_skew');
      if (value === null || payer === null || receiver === null) return;
      const rawIndex = span === 0 ? 0 : Math.floor((value - min) / binWidth);
      const binIndex = Math.min(Math.max(rawIndex, 0), dominance.length - 1);
      if (payer >= receiver) {
        dominance[binIndex].payer += 1;
      } else {
        dominance[binIndex].receiver += 1;
      }
    });

    return dominance.map((entry) => {
      if (entry.payer === 0 && entry.receiver === 0) return null;
      return entry.payer >= entry.receiver ? 'payer' : 'receiver';
    });
  }, [activeRows, config.histogramOverlay, histogram, histogramMetric.key]);

  const derivedFootnotes = metricDisplayValues
    .filter((metric) => metric.derived && metric.formula)
    .map((metric) => `(derived) ${metric.label} = ${metric.formula}`);

  const sampleWarnings = Array.from(
    new Set(
      metricDisplayValues
        .filter((metric) => metric.warning)
        .map((metric) => metric.warning as string),
    ),
  );

  const dateRangeLabel = useMemo(() => {
    if (!timeseriesRows.length) return '--';
    const timestamps = timeseriesRows
      .map((row) => new Date(row.execution_start).getTime())
      .filter((value) => !Number.isNaN(value))
      .sort((a, b) => a - b);
    if (!timestamps.length) return '--';
    const start = new Date(timestamps[0]);
    const end = new Date(timestamps[timestamps.length - 1]);
    const startLabel = start.toLocaleDateString('en-US', {
      month: 'short',
      year: 'numeric',
    });
    const endLabel = end.toLocaleDateString('en-US', {
      month: 'short',
      year: 'numeric',
    });
    return `${startLabel} - ${endLabel}`;
  }, [timeseriesRows]);

  const similarityLabel = useMemo(() => {
    const unitLabel = primaryMetric.unit ? ` ${primaryMetric.unit}` : '';
    const thresholdLabel =
      config.similarityCriteria.mode === 'percentage_of'
        ? `+/-${(primaryThreshold * 100).toFixed(0)}%`
        : `+/-${primaryThreshold}${unitLabel}`;
    return `Similar defined as: same bucket, ${primaryMetric.label} within ${thresholdLabel}`;
  }, [
    config.similarityCriteria.mode,
    primaryMetric.label,
    primaryMetric.unit,
    primaryThreshold,
  ]);

  const metricOptions = baseMetrics.filter((metric) => {
    if (metric.percentile === false) return false;
    if (metric.formatKind === 'raw') return false;
    const distribution = distributions[metric.key];
    return (distribution?.values.length ?? 0) > 0;
  });

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3 text-xs text-slate-300">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-slate-400">
            Trade Rarity
          </div>
          <div className="text-[11px] text-slate-500">
            Based on {activeRows.length} trades ({dateRangeLabel})
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-wide text-slate-500">
            Distribution
          </span>
          <div className="inline-flex overflow-hidden rounded border border-slate-700">
            {basisOptions.map((option) => (
              <button
                key={option.key}
                type="button"
                onClick={() => setBasis(option.key)}
                className={`px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                  basis === option.key
                    ? 'bg-slate-700 text-slate-100'
                    : 'text-slate-300 hover:bg-slate-800'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      {primaryFallbackNote && (
        <div className="mt-2 text-[11px] text-amber-300">{primaryFallbackNote}</div>
      )}
      <div className="mt-3">
        <PercentileRankBadges
          metrics={metricDisplayValues}
          primaryKey={primaryKey}
        />
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-[2fr_1fr]">
        <DistributionHistogram
          metricKey={histogramMetric.key}
          metricLabel={histogramMetric.label}
          metricUnit={histogramMetric.unit}
          histogram={histogram}
          stats={histogramStats}
          currentValue={currentHistogramValue}
          currentPercentile={currentHistogramPercentile}
          basis={basis}
          overlayType={config.histogramOverlay}
          overlayScatter={overlayScatter}
          skewDominance={skewDominance}
          metricOptions={metricOptions}
          onMetricChange={setHistogramMetricKey}
          formatValue={(value) =>
            formatMetricDisplay(histogramMetric, value, selectedRow, formatters)
          }
          formatCount={formatters.formatCount}
        />
        <RecencyScorecard
          selectedRow={selectedRow}
          rows={activeRows}
          config={config}
          primaryMetric={primaryMetric}
          primaryValue={primaryValue}
          formatters={formatters}
          primaryThreshold={primaryThreshold}
          sizeThresholdPct={sizeThresholdPct}
          onPrimaryThresholdChange={setPrimaryThreshold}
          onSizeThresholdChange={setSizeThresholdPct}
        />
      </div>
      <div className="mt-3 space-y-1 text-[10px] text-slate-500">
        <div>
          Distribution basis:{' '}
          {basisOptions.find((option) => option.key === basis)?.label || basis}{' '}
          trades
        </div>
        <div>{similarityLabel}</div>
        {derivedFootnotes.map((note) => (
          <div key={note}>{note}</div>
        ))}
        {sampleWarnings.map((warning) => (
          <div key={warning} className="text-amber-300">
            Warning: {warning} - percentiles may be noisy.
          </div>
        ))}
      </div>
    </div>
  );
});

function formatMetricDisplay(
  metric: MetricConfig,
  value: number | null,
  row: TapeRow,
  formatters: TradeRarityPanelFormatters,
): string {
  if (value === null || Number.isNaN(value)) return '--';
  if (metric.key === 'net_premium_sign') {
    return buildNetPremiumSignLabel(value);
  }
  if (metric.key === 'outright_moneyness') {
    const offset = getMetricValueByKey(row, 'outright_strike_offset_bps');
    return buildMoneynessLabel(offset);
  }
  if (metric.key === 'notional_profile') {
    return buildNotionalProfileLabel(row);
  }

  switch (metric.formatKind) {
    case 'notional':
      return formatters.formatNotional(value);
    case 'premium':
      return formatters.formatMetricValue(value, metric.decimals ?? 2);
    case 'metric':
      return formatters.formatMetricValue(value, metric.decimals ?? 2);
    case 'bps':
      return `${formatters.formatMetricValue(value, metric.decimals ?? 2)}bps`;
    case 'ratio':
      return formatters.formatRate(value, metric.decimals ?? 2);
    case 'count':
      return formatters.formatCount(value);
    case 'raw':
      return formatters.formatMetricValue(value, metric.decimals ?? 2);
    default:
      return formatters.formatMetricValue(value, metric.decimals ?? 2);
  }
}
