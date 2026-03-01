import { memo, useEffect, useMemo, useRef, useState } from 'react';
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
const DEFAULT_VISIBLE_METRIC_COUNT = 3;

const basisOptions: Array<{ key: RarityDistributionBasis; label: string }> = [
  { key: 'combined', label: 'Combined' },
  { key: 'custy', label: 'Custy' },
  { key: 'idb', label: 'IDB' },
];

type DistributionChartStyle = 'bar' | 'curve';
type RecencyMetricMode = 'vega01' | 'gamma01' | 'notional';

const RECENCY_THRESHOLD_DEFAULTS: Record<RecencyMetricMode, number> = {
  vega01: 5000,
  gamma01: 5000,
  notional: 50_000_000,
};

const METRIC_TOKEN_OVERRIDES: Record<string, string> = {
  bpvol: 'BPVol',
  yr: 'Yr',
  dv01: 'DV01',
  vega01: 'Vega01',
  gamma01: 'Gamma01',
  theta01: 'Theta01',
  atmf: 'ATMF',
  atm: 'ATM',
  rr: 'RR',
  vs: 'VS',
  fwd: 'Fwd',
  bps: 'bps',
  usd: 'USD',
};

const DEFAULT_METRIC_PREFERENCES: Array<(metric: MetricConfig) => boolean> = [
  (metric) => metric.key === 'premium_bps' || metric.label === 'Premium (bps)',
  (metric) => metric.key === 'total_notional' || metric.label === 'Notional',
  (metric) => /vega01/i.test(metric.key) || metric.label === 'Vega01',
];

function humanizeMetricKey(key: string): string {
  return key
    .split('_')
    .map((token) => {
      const lower = token.toLowerCase();
      if (METRIC_TOKEN_OVERRIDES[lower]) return METRIC_TOKEN_OVERRIDES[lower];
      if (!token.length) return token;
      return token[0].toUpperCase() + token.slice(1);
    })
    .join(' ');
}

function inferMetricConfig(key: string, packageType: string | null): MetricConfig {
  const normalized = key.toLowerCase();
  const isNotional = normalized.includes('notional');
  const isPremium = normalized.includes('premium');
  const isBps = normalized.includes('bps');
  const isRatio = normalized.includes('ratio') || normalized.includes('delta');
  const isCount = normalized.includes('count') || normalized.includes('seconds');
  const isDuration = normalized.includes('years') || normalized.includes('tenor');
  const isGreekMetric =
    normalized.includes('dv01') ||
    normalized.includes('vega01') ||
    normalized.includes('gamma01') ||
    normalized.includes('theta01');

  const formatKind: MetricConfig['formatKind'] = isNotional
    ? 'notional'
    : isPremium
      ? 'premium'
      : isBps
        ? 'bps'
        : isCount
          ? 'count'
          : isRatio
            ? 'ratio'
            : 'metric';

  const unit = isNotional || isPremium
    ? 'USD'
    : isBps
      ? 'bps'
      : isGreekMetric
        ? 'USD/bp'
        : isDuration
          ? 'years'
          : undefined;

  const decimals = isNotional || isCount ? 0 : isRatio ? 3 : 2;

  return {
    key,
    label: humanizeMetricKey(key),
    unit,
    decimals,
    showFor: packageType ? [packageType] : [],
    formatKind,
    absolute: isNotional || isPremium || isGreekMetric,
  };
}

function resolveDefaultMetricKeys(metrics: MetricConfig[]): string[] {
  const selected: string[] = [];
  DEFAULT_METRIC_PREFERENCES.forEach((matcher) => {
    const match = metrics.find((metric) => matcher(metric));
    if (!match || selected.includes(match.key)) return;
    selected.push(match.key);
  });
  metrics.forEach((metric) => {
    if (selected.length >= DEFAULT_VISIBLE_METRIC_COUNT) return;
    if (selected.includes(metric.key)) return;
    selected.push(metric.key);
  });
  return selected;
}

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
  const selectedRowBasis = useMemo<RarityDistributionBasis>(() => {
    const platform = resolvePlatformIdentifier(selectedRow);
    return isCustyPlatform(platform) ? 'custy' : 'idb';
  }, [selectedRow]);

  const [basis, setBasis] = useState<RarityDistributionBasis>(selectedRowBasis);
  const [histogramMetricKey, setHistogramMetricKey] = useState(
    config.primaryMetric.key,
  );
  const [primaryThreshold, setPrimaryThreshold] = useState(
    RECENCY_THRESHOLD_DEFAULTS.vega01,
  );
  const [sizeThresholdPct, setSizeThresholdPct] = useState(80);
  const [distributionChartStyle, setDistributionChartStyle] =
    useState<DistributionChartStyle>('curve');
  const [recencyMetricMode, setRecencyMetricMode] = useState<RecencyMetricMode>('vega01');
  const [visibleMetricKeys, setVisibleMetricKeys] = useState<string[]>([]);
  const previousPackageTypeRef = useRef<string>('');

  useEffect(() => {
    setBasis(selectedRowBasis);
    setHistogramMetricKey(config.primaryMetric.key);
    setRecencyMetricMode('vega01');
    setPrimaryThreshold(RECENCY_THRESHOLD_DEFAULTS.vega01);
  }, [config.primaryMetric.key, selectedRow.package_id, selectedRowBasis]);

  useEffect(() => {
    setPrimaryThreshold(RECENCY_THRESHOLD_DEFAULTS[recencyMetricMode]);
  }, [recencyMetricMode]);

  const rowsByBasis = useMemo(() => splitRowsByPlatform(timeseriesRows), [
    timeseriesRows,
  ]);

  const discoveredMetrics = useMemo(() => {
    const baseMetricKeys = new Set(baseMetrics.map((metric) => metric.key));
    const discoveredKeys = new Set<string>();

    [selectedRow, ...timeseriesRows].forEach((row) => {
      const packageMetrics = row.package_metrics || {};
      Object.keys(packageMetrics).forEach((key) => {
        if (!baseMetricKeys.has(key)) discoveredKeys.add(key);
      });

      const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
      legs.forEach((leg) => {
        const legMetrics = (leg as any)?.leg_metrics || {};
        Object.keys(legMetrics).forEach((key) => {
          if (!baseMetricKeys.has(key)) discoveredKeys.add(key);
        });
      });
    });

    return Array.from(discoveredKeys)
      .sort((left, right) => left.localeCompare(right))
      .map((key) => inferMetricConfig(key, config.packageType));
  }, [baseMetrics, config.packageType, selectedRow, timeseriesRows]);

  const allMetrics = useMemo(() => {
    if (!discoveredMetrics.length) return baseMetrics;
    return [...baseMetrics, ...discoveredMetrics];
  }, [baseMetrics, discoveredMetrics]);

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
    allMetrics.forEach((metric) => {
      const values: number[] = [];
      activeRows.forEach((row) => {
        const value = getMetricValue(row, metric);
        if (value === null || !Number.isFinite(value)) return;
        values.push(value);
      });
      map[metric.key] = {
        values,
        stats: distributionStats(values),
      };
    });
    return map;
  }, [activeRows, allMetrics]);

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
    if (!allMetrics.length) return allMetrics;
    if (allMetrics[0]?.key === primaryKey) return allMetrics;
    const nextPrimaryMetric = allMetrics.find((metric) => metric.key === primaryKey);
    if (!nextPrimaryMetric) return allMetrics;
    return [
      nextPrimaryMetric,
      ...allMetrics.filter((metric) => metric.key !== primaryKey),
    ];
  }, [allMetrics, primaryKey]);

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

  const percentileMetricOptions = useMemo(
    () =>
      orderedMetrics.filter((metric) => {
        if (metric.percentile === false) return false;
        const distribution = distributions[metric.key];
        return (distribution?.values.length ?? 0) > 0;
      }),
    [distributions, orderedMetrics],
  );

  useEffect(() => {
    const availableKeys = new Set(percentileMetricOptions.map((metric) => metric.key));
    const defaults = resolveDefaultMetricKeys(percentileMetricOptions);
    setVisibleMetricKeys((current) => {
      if (previousPackageTypeRef.current !== config.packageType) {
        previousPackageTypeRef.current = config.packageType;
        return defaults;
      }
      const retained = current.filter((key) => availableKeys.has(key));
      return retained.length ? retained : defaults;
    });
  }, [config.packageType, percentileMetricOptions]);

  const visibleMetricDisplayValues = useMemo(() => {
    if (!metricDisplayValues.length) return [];
    const byKey = new Map(metricDisplayValues.map((metric) => [metric.key, metric]));
    return visibleMetricKeys
      .map((key) => byKey.get(key))
      .filter((metric): metric is MetricDisplayValue => Boolean(metric));
  }, [metricDisplayValues, visibleMetricKeys]);

  const toggleVisibleMetric = (metricKey: string) => {
    setVisibleMetricKeys((current) => {
      const isSelected = current.includes(metricKey);
      if (isSelected) {
        if (current.length <= 1) return current;
        return current.filter((key) => key !== metricKey);
      }
      return [...current, metricKey];
    });
  };

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
      if (value === null || !Number.isFinite(value)) return;
      values.push(value);
      if (basis === 'combined') {
        const platform = resolvePlatformIdentifier(row);
        custyMask.push(isCustyPlatform(platform));
      }
    });
    return { values, custyMask };
  }, [basis, histogramMetric, rowsByBasis]);

  const histogramBinCount = useMemo(() => {
    const sampleSize = histogramValues.values.length;
    if (sampleSize <= 1) return 1;
    const precisionBuckets = new Set(
      histogramValues.values.map((value) => value.toPrecision(10)),
    );
    const uniqueCount = precisionBuckets.size;
    if (uniqueCount <= 1) return 1;
    const sqrtBins = Math.round(Math.sqrt(sampleSize));
    const target = Math.max(8, Math.min(32, sqrtBins * 2));
    return Math.max(1, Math.min(target, uniqueCount));
  }, [histogramValues.values]);

  const histogram = useMemo(() => {
    return computeHistogram(
      histogramValues.values,
      histogramBinCount,
      basis === 'combined' ? histogramValues.custyMask : undefined,
    );
  }, [basis, histogramBinCount, histogramValues]);

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

  const derivedFootnotes = visibleMetricDisplayValues
    .filter((metric) => metric.derived && metric.formula)
    .map((metric) => `(derived) ${metric.label} = ${metric.formula}`);

  const sampleWarnings = Array.from(
    new Set(
      visibleMetricDisplayValues
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

  const recencyMetricLabel =
    recencyMetricMode === 'vega01'
      ? 'Vega01'
      : recencyMetricMode === 'gamma01'
        ? 'Gamma01'
        : 'Notional';

  const similarityLabel = useMemo(() => {
    const unitLabel = recencyMetricMode === 'notional' ? ' USD' : ' USD/bp';
    const thresholdLabel = `+/-${primaryThreshold}${unitLabel}`;
    return `Similar defined as: same bucket, ${recencyMetricLabel} within ${thresholdLabel}`;
  }, [
    primaryThreshold,
    recencyMetricLabel,
    recencyMetricMode,
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
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="text-[10px] uppercase tracking-wide text-slate-500">
          Percentile metrics
        </span>
        <div className="flex flex-wrap items-center gap-1">
          {percentileMetricOptions.map((metric) => {
            const isSelected = visibleMetricKeys.includes(metric.key);
            const disableDeselect = isSelected && visibleMetricKeys.length <= 1;
            return (
              <button
                key={metric.key}
                type="button"
                onClick={() => toggleVisibleMetric(metric.key)}
                disabled={disableDeselect}
                className={`rounded border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide transition ${
                  isSelected
                    ? 'border-slate-500 bg-slate-700 text-slate-100'
                    : 'border-slate-700 text-slate-300 hover:bg-slate-800'
                } ${disableDeselect ? 'cursor-not-allowed opacity-60' : ''}`}
              >
                {metric.label}
              </button>
            );
          })}
        </div>
      </div>
      <div className="mt-3">
        <PercentileRankBadges
          metrics={visibleMetricDisplayValues}
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
          chartStyle={distributionChartStyle}
          onChartStyleChange={setDistributionChartStyle}
          formatValue={(value) =>
            formatMetricDisplay(histogramMetric, value, selectedRow, formatters)
          }
          formatCount={formatters.formatCount}
        />
        <RecencyScorecard
          selectedRow={selectedRow}
          rows={activeRows}
          config={config}
          recencyMetricMode={recencyMetricMode}
          formatters={formatters}
          primaryThreshold={primaryThreshold}
          sizeThresholdPct={sizeThresholdPct}
          onRecencyMetricModeChange={setRecencyMetricMode}
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
  if (value === null || !Number.isFinite(value)) return '--';
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
