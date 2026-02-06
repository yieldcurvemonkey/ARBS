// Types for trade rarity analytics
import type { TapeRow } from '../../types/trade.types';

export type MetricFormatKind =
  | 'notional'
  | 'premium'
  | 'metric'
  | 'bps'
  | 'rate'
  | 'ratio'
  | 'count'
  | 'raw';

export type MetricConfig = {
  key: string;
  label: string;
  unit?: string;
  decimals?: number;
  primary?: boolean;
  derived?: boolean;
  derivedFrom?: (row: TapeRow) => number | null;
  showFor: string[];
  formatKind?: MetricFormatKind;
  formula?: string;
  percentile?: boolean;
  absolute?: boolean;
};

export type SimilarityCriteria = {
  metric: string;
  mode: 'absolute_range' | 'percentage_of';
  threshold: number;
  requireDirection?: boolean;
  requireOptionType?: boolean;
};

export type StructureAnalyticsConfig = {
  packageType: string;
  primaryMetric: MetricConfig;
  secondaryMetrics: MetricConfig[];
  similarityCriteria: SimilarityCriteria;
  histogramDefault: string;
  histogramOverlay?: 'breakeven' | 'skew_direction' | 'ratio_reference' | 'iqr_band';
};

export type HistogramBin = {
  binStart: number;
  binEnd: number;
  count: number;
  custyCount: number;
  idbCount: number;
  cumulativePercent: number;
};

export type HistogramResult = {
  bins: HistogramBin[];
  binWidth: number;
  totalCount: number;
};

export type DistributionStatistics = {
  mean: number;
  median: number;
  stddev: number;
  min: number;
  max: number;
  p5: number;
  p25: number;
  p75: number;
  p95: number;
  iqr: number;
  count: number;
};

export type RecencyStat = {
  daysAgo: number;
  date: string;
  value: number;
  tradeId?: string;
};

export type FrequencyStat = {
  count: number;
  avgIntervalDays: number;
  lookbackDays: number;
  trades: RecencyStat[];
};

export type RarityZone = 'typical' | 'notable' | 'rare' | 'extreme';

export type PercentileResult = {
  value: number;
  percentile: number;
  zone: RarityZone;
  descriptor: string;
  sampleSize: number;
};

export type MetricDisplayValue = {
  key: string;
  label: string;
  value: number | null;
  displayValue: string;
  percentile: number | null;
  zone: RarityZone | null;
  descriptor: string;
  sampleSize: number;
  derived?: boolean;
  primary?: boolean;
  unit?: string;
  formula?: string;
  showPercentile: boolean;
  warning?: string | null;
};

export type MetricDistribution = {
  key: string;
  values: number[];
  stats: DistributionStatistics | null;
};

export type SimilarityResult = {
  lastSimilarPrimary: RecencyStat | null;
  lastSimilarSize: RecencyStat | null;
  frequencyPrimary: FrequencyStat | null;
  frequencySize: FrequencyStat | null;
  largestRecord: RecencyStat | null;
  primaryRecord: RecencyStat | null;
  bucketRank: { rank: number; total: number } | null;
  daysSinceSize: number | null;
};

export type DerivedMetricSummary = {
  key: string;
  formula: string;
};

export type RarityDistributionBasis = 'combined' | 'custy' | 'idb';
