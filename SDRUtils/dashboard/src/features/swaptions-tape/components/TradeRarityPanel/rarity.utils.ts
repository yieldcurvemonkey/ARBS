import type {
  DistributionStatistics,
  FrequencyStat,
  HistogramResult,
  MetricConfig,
  PercentileResult,
  RecencyStat,
  SimilarityCriteria,
  StructureAnalyticsConfig,
} from './rarity.types';
import type { TapeLeg, TapeRow } from '../../types/trade.types';
import type { StraddleTimeseriesPoint, TimeseriesMetricKey } from '../../types/chart.types';
import { STRUCTURE_ANALYTICS } from './rarity.config';

const DAY_MS = 24 * 60 * 60 * 1000;
const DEFAULT_LOOKBACK_DAYS = 90;
const HISTOGRAM_CLIP_MIN_SAMPLES = 50;
const HISTOGRAM_CLIP_LOWER_Q = 0.01;
const HISTOGRAM_CLIP_UPPER_Q = 0.99;
const HISTOGRAM_CLIP_SPAN_RATIO = 3;

const IDB_MIC_SET = new Set(['BGCD', 'ISWV', 'TPSE']);
const CUSTY_MIC_SET = new Set(['BILT', 'XXXX', 'TWSF', 'BBSF', 'XOFF']);

const PRIMARY_METRIC_FALLBACK: MetricConfig = {
  key: 'total_premium',
  label: 'Premium',
  unit: 'USD',
  showFor: [],
  formatKind: 'premium',
  absolute: true,
};

const UNKNOWN_STRUCTURE_FALLBACK: StructureAnalyticsConfig = {
  packageType: 'UNKNOWN',
  primaryMetric: {
    key: 'total_notional',
    label: 'Notional',
    unit: 'USD',
    showFor: [],
    formatKind: 'notional',
    absolute: true,
    primary: true,
  },
  secondaryMetrics: [PRIMARY_METRIC_FALLBACK],
  similarityCriteria: {
    metric: 'total_notional',
    mode: 'percentage_of',
    threshold: 0.2,
  },
  histogramDefault: 'total_notional',
};

const unknownStructureWarnings = new Set<string>();

export function normalizePackageType(value: string | null | undefined): string {
  if (!value) return '';
  return String(value).trim().toUpperCase();
}

export function isValid(value: any): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === 'number' && Number.isNaN(value)) return false;
  if (typeof value === 'string' && value.trim() === '') return false;
  return true;
}

export function parseMetricNumber(value: any): number | null {
  if (!isValid(value)) return null;
  const numericValue = Number(value);
  return Number.isNaN(numericValue) ? null : numericValue;
}

export function parseMetricSeries(value: any): number | null {
  if (!isValid(value)) return null;
  if (Array.isArray(value)) {
    const numbers = value
      .map((entry) => parseMetricNumber(entry))
      .filter((entry): entry is number => entry !== null);
    if (!numbers.length) return null;
    return numbers.reduce((sum, entry) => sum + entry, 0);
  }
  if (typeof value === 'string') {
    const normalized = value.trim();
    if (!normalized) return null;
    if (/[\\/|,]/.test(normalized)) {
      const parts = normalized
        .split(/[\\/|,]+/)
        .map((entry) => entry.trim())
        .filter(Boolean);
      const numbers = parts
        .map((entry) => parseMetricNumber(entry))
        .filter((entry): entry is number => entry !== null);
      if (numbers.length) {
        return numbers.reduce((sum, entry) => sum + entry, 0);
      }
    }
  }
  return parseMetricNumber(value);
}

export function percentileRank(value: number, distribution: number[]): number {
  if (!distribution.length || Number.isNaN(value)) return NaN;
  const sorted = [...distribution].sort((a, b) => a - b);
  const min = sorted[0];
  const max = sorted[sorted.length - 1];
  if (value <= min) return 0;
  if (value >= max) return 100;
  let low = 0;
  let high = sorted.length - 1;
  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    const midValue = sorted[mid];
    if (midValue === value) {
      return (mid / (sorted.length - 1)) * 100;
    }
    if (midValue < value) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  const upperIndex = Math.min(low, sorted.length - 1);
  const lowerIndex = Math.max(upperIndex - 1, 0);
  const lowerValue = sorted[lowerIndex];
  const upperValue = sorted[upperIndex];
  if (upperValue === lowerValue) {
    return (lowerIndex / (sorted.length - 1)) * 100;
  }
  const fraction = (value - lowerValue) / (upperValue - lowerValue);
  const rank = lowerIndex + fraction;
  return (rank / (sorted.length - 1)) * 100;
}

export function computeHistogram(
  values: number[],
  binCount = 20,
  custyMask?: boolean[],
): HistogramResult {
  const samples = values
    .map((value, index) => ({
      value,
      isCusty: custyMask ? Boolean(custyMask[index]) : false,
    }))
    .filter((sample) => Number.isFinite(sample.value));
  if (!samples.length) {
    return { bins: [], binWidth: 0, totalCount: 0 };
  }

  const cleanValues = samples.map((sample) => sample.value as number);
  const min = Math.min(...cleanValues);
  const max = Math.max(...cleanValues);
  const safeBinCount = Math.max(1, binCount);
  const span = max - min;
  const sortedValues = [...cleanValues].sort((a, b) => a - b);
  let rangeMin = min;
  let rangeMax = max;

  if (span > 0 && sortedValues.length >= HISTOGRAM_CLIP_MIN_SAMPLES) {
    const clippedMin = quantile(sortedValues, HISTOGRAM_CLIP_LOWER_Q);
    const clippedMax = quantile(sortedValues, HISTOGRAM_CLIP_UPPER_Q);
    const clippedSpan = clippedMax - clippedMin;
    if (
      Number.isFinite(clippedMin) &&
      Number.isFinite(clippedMax) &&
      clippedSpan > 0 &&
      span / clippedSpan >= HISTOGRAM_CLIP_SPAN_RATIO
    ) {
      rangeMin = clippedMin;
      rangeMax = clippedMax;
    }
  }

  let effectiveSpan = rangeMax - rangeMin;
  if (effectiveSpan <= 0) {
    rangeMin = min;
    rangeMax = max;
    effectiveSpan = span;
  }

  if (effectiveSpan === 0) {
    const singleBin = {
      binStart: rangeMin - 0.5,
      binEnd: rangeMin + 0.5,
      count: samples.length,
      custyCount: 0,
      idbCount: 0,
      cumulativePercent: 100,
    };

    if (custyMask) {
      samples.forEach((sample) => {
        if (sample.isCusty) {
          singleBin.custyCount += 1;
        } else {
          singleBin.idbCount += 1;
        }
      });
    }

    return {
      bins: [singleBin],
      binWidth: 1,
      totalCount: samples.length,
    };
  }

  const binWidth = effectiveSpan / safeBinCount;
  const bins = Array.from({ length: safeBinCount }, (_, index) => {
    const start = rangeMin + index * binWidth;
    return {
      binStart: start,
      binEnd: start + binWidth,
      count: 0,
      custyCount: 0,
      idbCount: 0,
      cumulativePercent: 0,
    };
  });

  samples.forEach((sample) => {
    const value = sample.value as number;
    const clampedValue = Math.min(Math.max(value, rangeMin), rangeMax);
    const rawIndex = Math.floor((clampedValue - rangeMin) / binWidth);
    const binIndex = Math.min(Math.max(rawIndex, 0), bins.length - 1);
    const bin = bins[binIndex];
    bin.count += 1;
    if (custyMask) {
      if (sample.isCusty) {
        bin.custyCount += 1;
      } else {
        bin.idbCount += 1;
      }
    }
  });

  let cumulative = 0;
  bins.forEach((bin) => {
    cumulative += bin.count;
    bin.cumulativePercent = (cumulative / samples.length) * 100;
  });

  return {
    bins,
    binWidth,
    totalCount: samples.length,
  };
}
const quantile = (sorted: number[], q: number): number => {
  if (!sorted.length) return NaN;
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  if (sorted[base + 1] !== undefined) {
    return sorted[base] + rest * (sorted[base + 1] - sorted[base]);
  }
  return sorted[base];
};

export function distributionStats(values: number[]): DistributionStatistics {
  const clean = values.filter((value) => Number.isFinite(value));
  if (!clean.length) {
    return {
      mean: 0,
      median: 0,
      stddev: 0,
      min: 0,
      max: 0,
      p5: 0,
      p25: 0,
      p75: 0,
      p95: 0,
      iqr: 0,
      count: 0,
    };
  }
  const sorted = [...clean].sort((a, b) => a - b);
  const count = sorted.length;
  const mean = sorted.reduce((sum, value) => sum + value, 0) / count;
  const variance =
    sorted.reduce((sum, value) => sum + Math.pow(value - mean, 2), 0) / count;
  const stddev = Math.sqrt(variance);
  const median = quantile(sorted, 0.5);
  const p5 = quantile(sorted, 0.05);
  const p25 = quantile(sorted, 0.25);
  const p75 = quantile(sorted, 0.75);
  const p95 = quantile(sorted, 0.95);
  return {
    mean,
    median,
    stddev,
    min: sorted[0],
    max: sorted[sorted.length - 1],
    p5,
    p25,
    p75,
    p95,
    iqr: p75 - p25,
    count,
  };
}

export function computeRank(
  value: number,
  distribution: number[],
  direction: 'asc' | 'desc' = 'desc',
): { rank: number; total: number } {
  const clean = distribution.filter((entry) => Number.isFinite(entry));
  if (!clean.length || Number.isNaN(value)) {
    return { rank: 0, total: 0 };
  }
  if (direction === 'asc') {
    const higherCount = clean.filter((entry) => entry < value).length;
    return { rank: higherCount + 1, total: clean.length };
  }
  const higherCount = clean.filter((entry) => entry > value).length;
  return { rank: higherCount + 1, total: clean.length };
}

export function zScore(value: number, mean: number, stddev: number): number {
  if (!Number.isFinite(value) || !Number.isFinite(mean) || !Number.isFinite(stddev)) {
    return 0;
  }
  if (stddev === 0) return 0;
  return (value - mean) / stddev;
}

export function getMetricsForStructure(packageType: string | null): MetricConfig[] {
  const normalized = normalizePackageType(packageType);
  const config = STRUCTURE_ANALYTICS[normalized] || UNKNOWN_STRUCTURE_FALLBACK;
  const primary = config.primaryMetric;
  const secondary = config.secondaryMetrics || [];
  return [primary, ...secondary];
}

export function getPrimaryMetricValue(row: TapeRow): number | null {
  const normalized = normalizePackageType(row.package_type);
  const config = STRUCTURE_ANALYTICS[normalized];
  if (!config) return getMetricValue(row, PRIMARY_METRIC_FALLBACK);
  return getMetricValue(row, config.primaryMetric);
}

export function computeDerivedMetrics(row: TapeRow): Record<string, number | null> {
  const metrics: Record<string, number | null> = {};
  const notional = getRawMetricValue(row, 'total_notional');
  const premium = getRawMetricValue(row, 'total_premium');
  if (notional !== null && notional !== 0 && premium !== null) {
    const absNotional = Math.abs(notional);
    const absPremium = Math.abs(premium);
    metrics.breakeven_width_bps = (absPremium / absNotional) * 10000;
    metrics.premium_bps = (absPremium / absNotional) * 10000;
    const straddleVega = getRawMetricValue(row, 'straddle_vega01');
    metrics.vega_per_notional =
      straddleVega !== null ? straddleVega / absNotional : null;
  } else {
    metrics.breakeven_width_bps = null;
    metrics.premium_bps = null;
    metrics.vega_per_notional = null;
  }

  const theta = getRawMetricValue(row, 'straddle_theta1d');
  const vega = getRawMetricValue(row, 'straddle_vega01');
  metrics.theta_vega_ratio =
    theta !== null && vega !== null && vega !== 0 ? theta / vega : null;

  const fwdPremium = getRawMetricValue(row, 'straddle_fwd_premium');
  metrics.fwd_premium_ratio =
    fwdPremium !== null && premium !== null && premium !== 0
      ? fwdPremium / premium
      : null;

  const skew = getRawMetricValue(row, 'rr_skew_bpvol');
  const atm = getRawMetricValue(row, 'rr_atm_bpvol');
  metrics.skew_atm_ratio =
    skew !== null && atm !== null && atm !== 0 ? skew / atm : null;

  const rrDv01 = getRawMetricValue(row, 'rr_dv01');
  const rrVega = getRawMetricValue(row, 'rr_vega01');
  metrics.net_dv01_vega_ratio =
    rrDv01 !== null && rrVega !== null && rrVega !== 0 ? rrDv01 / rrVega : null;

  const outStrike = getRawMetricValue(row, 'rr_out_strike');
  const atmf = getRawMetricValue(row, 'rr_atmf');
  if (outStrike !== null && atmf !== null) {
    const normalizedOut = normalizeStrikeValue(outStrike);
    const normalizedAtm = normalizeStrikeValue(atmf);
    metrics.wing_distance_bps = normalizedOut - normalizedAtm;
  } else {
    metrics.wing_distance_bps = null;
  }

  const ratio = getRawMetricValue(row, 'vs_notional_ratio');
  metrics.notional_ratio_deviation = ratio !== null ? Math.abs(ratio - 2) : null;

  const netPremium = getRawMetricValue(row, 'vs_net_premium');
  metrics.net_premium_sign =
    netPremium === null ? null : netPremium === 0 ? 0 : netPremium > 0 ? 1 : -1;

  const atmPremium = getRawMetricValue(row, 'vs_atm_premium');
  metrics.premium_offset_ratio =
    netPremium !== null && atmPremium !== null && atmPremium !== 0
      ? netPremium / atmPremium
      : null;

  const vsDv01 = getRawMetricValue(row, 'vs_dv01');
  const vsAtmDv01 = getRawMetricValue(row, 'vs_atm_dv01');
  metrics.net_dv01_ratio =
    vsDv01 !== null && vsAtmDv01 !== null && vsAtmDv01 !== 0
      ? vsDv01 / vsAtmDv01
      : null;

  const spacing = computeSpacingUniformity(row);
  metrics.spacing_uniformity = spacing;

  const notionalProfile = computeNotionalProfileSkew(row);
  metrics.notional_profile = notionalProfile;

  const strikeOffset = getRawMetricValue(row, 'outright_strike_offset_bps');
  metrics.outright_moneyness = deriveMoneynessScore(strikeOffset);

  return metrics;
}

export function getMetricValue(row: TapeRow, metricConfig: MetricConfig): number | null {
  const { key, derivedFrom, derived, absolute } = metricConfig;
  let value: number | null = null;
  if (derivedFrom) {
    value = derivedFrom(row);
  } else if (derived) {
    const derivedValues = computeDerivedMetrics(row);
    value = derivedValues[key] ?? null;
  } else {
    value = getRawMetricValue(row, key);
  }
  if (value === null || !Number.isFinite(value)) return null;
  if (absolute) return Math.abs(value);
  return value;
}

export function getMetricValueByKey(row: TapeRow, key: string): number | null {
  const config = getMetricsForStructure(row.package_type).find(
    (metricItem) => metricItem.key === key,
  );
  if (config) return getMetricValue(row, config);
  return getRawMetricValue(row, key);
}

function sumLegMetricSeries(row: TapeRow, metricKey: string): number | null {
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  let total: number | null = null;
  legs.forEach((leg) => {
    const legMetrics = (leg as any)?.leg_metrics || {};
    const value = parseMetricSeries((legMetrics as any)[metricKey]);
    if (value === null) return;
    total = total === null ? value : total + value;
  });
  return total;
}

function resolveStraddleFallbackMetricValue(row: TapeRow, key: string): number | null {
  if (normalizePackageType(row.package_type) !== 'STRADDLE') return null;
  if (key !== 'straddle_vega01') return null;

  const metrics = row.package_metrics || {};
  const isAssumedIncomplete = Boolean((row as any)?.assumed_incomplete_straddle);
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  const firstLegMetrics = (legs[0] as any)?.leg_metrics || {};

  const vegaCurveValue = parseMetricSeries((metrics as any).vega_curve_vega01);
  if (vegaCurveValue !== null) return vegaCurveValue;

  const summedOutrightVega = sumLegMetricSeries(row, 'outright_vega01');
  if (summedOutrightVega !== null) {
    if (isAssumedIncomplete && legs.length <= 1) return summedOutrightVega * 2;
    return summedOutrightVega;
  }

  if (isAssumedIncomplete) {
    const outrightVega = parseMetricSeries((firstLegMetrics as any).outright_vega01);
    if (outrightVega !== null) return outrightVega * 2;
  }

  return null;
}

function getRawMetricValue(row: TapeRow, key: string): number | null {
  if (!row) return null;
  if (key === 'total_notional' || key === 'notional') {
    return parseMetricNumber(row.total_notional);
  }
  if (key === 'total_premium' || key === 'premium') {
    return parseMetricNumber(row.total_premium);
  }
  const metrics = row.package_metrics || {};
  if (Object.prototype.hasOwnProperty.call(metrics, key)) {
    return parseMetricSeries((metrics as any)[key]);
  }
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  const firstLeg = legs[0] as TapeLeg | undefined;
  const legMetrics = (firstLeg as any)?.leg_metrics || {};
  if (Object.prototype.hasOwnProperty.call(legMetrics, key)) {
    return parseMetricSeries((legMetrics as any)[key]);
  }
  const fallbackValue = resolveStraddleFallbackMetricValue(row, key);
  if (fallbackValue !== null) return fallbackValue;
  return null;
}

function normalizeStrikeValue(value: number): number {
  if (!Number.isFinite(value)) return value;
  if (Math.abs(value) <= 1) return value * 10000;
  return value;
}

function computeSpacingUniformity(row: TapeRow): number | null {
  const metrics = row.package_metrics || {};
  const strikes = Array.isArray(metrics.ladder_strikes)
    ? metrics.ladder_strikes
    : (row.legs_json || []).map((leg) => leg.strike).filter((v) => v != null);
  if (!strikes || strikes.length < 3) return null;
  const numeric = strikes
    .map((strike: any) => (strike == null ? null : Number(strike)))
    .filter((value: any): value is number => Number.isFinite(value))
    .map((value) => normalizeStrikeValue(value));
  if (numeric.length < 3) return null;
  const sorted = [...numeric].sort((a, b) => a - b);
  const gaps = sorted.slice(1).map((value, index) => value - sorted[index]);
  if (!gaps.length) return null;
  const mean = gaps.reduce((sum, value) => sum + value, 0) / gaps.length;
  if (mean === 0) return null;
  const variance = gaps.reduce((sum, value) => sum + Math.pow(value - mean, 2), 0) / gaps.length;
  return Math.sqrt(variance) / mean;
}

function computeNotionalProfileSkew(row: TapeRow): number | null {
  const metrics = row.package_metrics || {};
  const notionals = Array.isArray(metrics.ladder_notionals)
    ? metrics.ladder_notionals
    : (row.legs_json || []).map((leg) => leg.notional).filter((v) => v != null);
  if (!notionals || notionals.length < 2) return null;
  const numeric = notionals
    .map((value: any) => (value == null ? null : Number(value)))
    .filter((value: any): value is number => Number.isFinite(value));
  if (numeric.length < 2) return null;
  const mean = numeric.reduce((sum, value) => sum + value, 0) / numeric.length;
  if (mean === 0) return null;
  const variance =
    numeric.reduce((sum, value) => sum + Math.pow(value - mean, 2), 0) /
    numeric.length;
  return Math.sqrt(variance) / mean;
}

export function buildNotionalProfileLabel(row: TapeRow): string {
  const metrics = row.package_metrics || {};
  const notionals = Array.isArray(metrics.ladder_notionals)
    ? metrics.ladder_notionals
    : (row.legs_json || []).map((leg) => leg.notional).filter((v) => v != null);
  if (!notionals || notionals.length < 2) return '--';
  const numeric = notionals
    .map((value: any) => (value == null ? null : Number(value)))
    .filter((value: any): value is number => Number.isFinite(value));
  if (numeric.length < 2) return '--';
  const min = Math.min(...numeric.filter((value) => value > 0));
  if (!Number.isFinite(min) || min === 0) return '--';
  const ratios = numeric.map((value) => Math.round(value / min));
  return ratios.join(':');
}

function deriveMoneynessScore(offset: number | null): number | null {
  if (offset === null || !Number.isFinite(offset)) return null;
  if (Math.abs(offset) <= 10) return 0;
  return offset > 0 ? 1 : -1;
}

export function buildMoneynessLabel(offset: number | null): string {
  if (offset === null || !Number.isFinite(offset)) return '--';
  if (Math.abs(offset) <= 10) return 'ATM';
  return offset > 0 ? 'OTM' : 'ITM';
}

export function buildNetPremiumSignLabel(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '--';
  if (value === 0) return 'Flat';
  return value > 0 ? 'Pay' : 'Collect';
}

export function buildPercentileDescriptor(
  percentile: number,
  stats: DistributionStatistics | null,
  value: number | null,
): { zone: PercentileResult['zone']; descriptor: string } {
  if (value === null || percentile === null || Number.isNaN(percentile)) {
    return { zone: 'typical', descriptor: 'no data' };
  }
  if (stats && stats.count > 0) {
    if (value === stats.max) {
      return { zone: 'extreme', descriptor: 'extreme - largest ever' };
    }
    if (value === stats.min) {
      return { zone: 'extreme', descriptor: 'extreme - smallest ever' };
    }
  }
  if (percentile >= 99 || percentile <= 1) {
    return { zone: 'extreme', descriptor: 'extreme - top 1%' };
  }
  if (percentile >= 95) {
    return { zone: 'rare', descriptor: 'rare - top 5%' };
  }
  if (percentile <= 5) {
    return { zone: 'rare', descriptor: 'rare - bottom 5%' };
  }
  if (percentile >= 80) {
    return { zone: 'notable', descriptor: 'above average' };
  }
  if (percentile <= 20) {
    return { zone: 'notable', descriptor: 'below average' };
  }
  return { zone: 'typical', descriptor: 'typical' };
}

export function computePercentileResult(
  value: number,
  distribution: number[],
  stats: DistributionStatistics | null,
): PercentileResult {
  const percentile = percentileRank(value, distribution);
  const { zone, descriptor } = buildPercentileDescriptor(percentile, stats, value);
  return {
    value,
    percentile,
    zone,
    descriptor,
    sampleSize: distribution.length,
  };
}

export function resolvePlatformIdentifier(row: TapeRow): string | null {
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  const firstLeg = legs[0] as any;
  const metrics = firstLeg?.leg_metrics || {};
  const packageMetrics = row.package_metrics || {};
  const platform =
    metrics.platform_identifier ||
    metrics.platform ||
    metrics.mic ||
    firstLeg?.platform ||
    firstLeg?.platform_identifier ||
    (row as any).platform ||
    row.platform_identifier ||
    packageMetrics.platform_identifier ||
    packageMetrics.platform ||
    packageMetrics.mic;
  return platform ? String(platform) : null;
}

export function normalizePlatformTokens(platform: string | null | undefined): string[] {
  if (!platform) return [];
  return platform
    .trim()
    .toUpperCase()
    .replace(/[\[\]"']/g, ' ')
    .split(/[\s,;/]+/)
    .filter(Boolean);
}

export function isCustyPlatform(platform: string | null | undefined): boolean {
  const tokens = normalizePlatformTokens(platform);
  if (!tokens.length) return true;
  if (tokens.some((token) => IDB_MIC_SET.has(token))) return false;
  if (tokens.some((token) => CUSTY_MIC_SET.has(token))) return true;
  return true;
}

export function getTradeDirection(row: TapeRow): string {
  const metrics = row.package_metrics || {};
  const spreadType = metrics.vs_spread_type || metrics.vs_direction;
  if (spreadType) {
    const normalized = String(spreadType).toUpperCase();
    if (normalized.includes('RECEIVER')) return 'RECEIVER';
    if (normalized.includes('PAYER')) return 'PAYER';
  }
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  const legType = legs[0]?.product_type;
  if (legType) {
    const normalized = String(legType).toUpperCase();
    if (normalized.includes('RECEIVER')) return 'RECEIVER';
    if (normalized.includes('PAYER')) return 'PAYER';
  }
  return 'UNKNOWN';
}

export function isSimilarTrade(
  current: TapeRow,
  candidate: TapeRow,
  criteria: SimilarityCriteria,
): boolean {
  const currentValue = getMetricValueByKey(current, criteria.metric);
  const candidateValue = getMetricValueByKey(candidate, criteria.metric);
  if (currentValue === null || candidateValue === null) return false;

  let matches = false;
  if (criteria.mode === 'absolute_range') {
    matches = Math.abs(candidateValue - currentValue) <= criteria.threshold;
  } else {
    if (currentValue === 0) return false;
    matches =
      Math.abs(candidateValue - currentValue) / Math.abs(currentValue) <=
      criteria.threshold;
  }

  if (!matches) return false;

  if (criteria.requireDirection) {
    const currentDirection = getTradeDirection(current);
    const candidateDirection = getTradeDirection(candidate);
    if (currentDirection === 'UNKNOWN' || candidateDirection === 'UNKNOWN') {
      return false;
    }
    if (currentDirection !== candidateDirection) return false;
  }

  if (criteria.requireOptionType) {
    const currentDirection = getTradeDirection(current);
    const candidateDirection = getTradeDirection(candidate);
    if (currentDirection === 'UNKNOWN' || candidateDirection === 'UNKNOWN') {
      return false;
    }
    if (currentDirection !== candidateDirection) return false;
  }

  return true;
}

export function findLastSimilarByStructure(
  currentRow: TapeRow,
  points: TapeRow[],
  criteria: SimilarityCriteria,
): RecencyStat | null {
  const currentTime = new Date(currentRow.execution_start).getTime();
  if (Number.isNaN(currentTime)) return null;
  let best: TapeRow | null = null;
  points.forEach((candidate) => {
    if (!candidate.execution_start) return;
    if (candidate.package_id === currentRow.package_id) return;
    const candidateTime = new Date(candidate.execution_start).getTime();
    if (Number.isNaN(candidateTime)) return;
    if (candidateTime >= currentTime) return;
    if (!isSimilarTrade(currentRow, candidate, criteria)) return;
    if (!best || candidateTime > new Date(best.execution_start).getTime()) {
      best = candidate;
    }
  });
  if (!best) return null;
  const bestRow: TapeRow = best;
  const bestTime = new Date(bestRow.execution_start).getTime();
  const daysAgo = Math.max(0, Math.round((currentTime - bestTime) / DAY_MS));
  const value = getMetricValueByKey(bestRow, criteria.metric);
  if (value === null) return null;
  return {
    daysAgo,
    date: bestRow.execution_start,
    value,
    tradeId: bestRow.package_id,
  };
}

export function computeFrequencyByPredicate(
  currentRow: TapeRow,
  points: TapeRow[],
  predicate: (row: TapeRow) => boolean,
  lookbackDays = DEFAULT_LOOKBACK_DAYS,
): FrequencyStat | null {
  const currentTime = new Date(currentRow.execution_start).getTime();
  if (Number.isNaN(currentTime)) return null;
  const cutoff = currentTime - lookbackDays * DAY_MS;
  const trades: RecencyStat[] = [];
  points.forEach((candidate) => {
    if (!candidate.execution_start) return;
    if (candidate.package_id === currentRow.package_id) return;
    const candidateTime = new Date(candidate.execution_start).getTime();
    if (Number.isNaN(candidateTime)) return;
    if (candidateTime < cutoff || candidateTime >= currentTime) return;
    if (!predicate(candidate)) return;
    trades.push({
      daysAgo: Math.max(0, Math.round((currentTime - candidateTime) / DAY_MS)),
      date: candidate.execution_start,
      value: getMetricValueByKey(candidate, 'total_notional') ?? 0,
      tradeId: candidate.package_id,
    });
  });
  const count = trades.length;
  return {
    count,
    avgIntervalDays: count ? lookbackDays / count : 0,
    lookbackDays,
    trades,
  };
}

export function computeFrequency(
  threshold: number,
  points: StraddleTimeseriesPoint[],
  metricKey: TimeseriesMetricKey,
  lookbackDays = DEFAULT_LOOKBACK_DAYS,
): FrequencyStat {
  if (!points.length) {
    return { count: 0, avgIntervalDays: 0, lookbackDays, trades: [] };
  }
  const latest = points[points.length - 1];
  const currentTime = latest.timestamp;
  const cutoff = currentTime - lookbackDays * DAY_MS;
  const trades: RecencyStat[] = [];
  points.forEach((point) => {
    if (point.timestamp < cutoff || point.timestamp >= currentTime) return;
    const value = (point as any)[metricKey];
    if (!Number.isFinite(value)) return;
    if (value < threshold) return;
    trades.push({
      daysAgo: Math.round((currentTime - point.timestamp) / DAY_MS),
      date: new Date(point.timestamp).toISOString(),
      value,
    });
  });
  const count = trades.length;
  return {
    count,
    avgIntervalDays: count ? lookbackDays / count : 0,
    lookbackDays,
    trades,
  };
}

export function findLastSimilar(
  currentValue: number,
  points: StraddleTimeseriesPoint[],
  metricKey: TimeseriesMetricKey,
  thresholdRatio = 0.8,
): RecencyStat | null {
  if (!points.length || !Number.isFinite(currentValue)) return null;
  const threshold = currentValue * thresholdRatio;
  const currentTime = points[points.length - 1].timestamp;
  for (let i = points.length - 1; i >= 0; i -= 1) {
    const point = points[i];
    const value = (point as any)[metricKey];
    if (!Number.isFinite(value)) continue;
    if (value >= threshold && point.timestamp < currentTime) {
      return {
        daysAgo: Math.round((currentTime - point.timestamp) / DAY_MS),
        date: new Date(point.timestamp).toISOString(),
        value,
      };
    }
  }
  return null;
}

export function resolveStructureConfig(packageType: string | null): StructureAnalyticsConfig {
  const normalized = normalizePackageType(packageType);
  const config = STRUCTURE_ANALYTICS[normalized];
  if (!config) {
    if (!unknownStructureWarnings.has(normalized)) {
      unknownStructureWarnings.add(normalized);
      if (normalized) {
        console.warn(
          `TradeRarityPanel: missing config for package_type ${normalized}. Falling back to notional/premium.`,
        );
      }
    }
    return UNKNOWN_STRUCTURE_FALLBACK;
  }
  return config;
}

export function ensurePremiumMetric(metrics: MetricConfig[]): MetricConfig[] {
  if (metrics.some((metricItem) => metricItem.key === 'total_premium')) {
    return metrics;
  }
  return [...metrics, PRIMARY_METRIC_FALLBACK];
}

export function splitRowsByPlatform(rows: TapeRow[]): {
  custy: TapeRow[];
  idb: TapeRow[];
  combined: TapeRow[];
} {
  const custy: TapeRow[] = [];
  const idb: TapeRow[] = [];
  rows.forEach((row) => {
    const platform = resolvePlatformIdentifier(row);
    if (isCustyPlatform(platform)) {
      custy.push(row);
    } else {
      idb.push(row);
    }
  });
  return { custy, idb, combined: rows };
}

