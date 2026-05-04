// Types for the per-trade analytics dock.
import type { UsdSwapTapeRow } from '../../types'

// Multi-trade dock workstream — selection-size-derived render mode.
// Mirrors the union exported by `hooks/useFocusedTrade.ts` so tab
// components and the orchestrator can branch on the same vocabulary
// without a circular import.
export type AnalyticsMode = 'empty' | 'single' | 'sequence'

export type AnalyticsTab = 'timeseries' | 'rarity' | 'levels' | 'sequence'

// Phase 4 contract: matches the groupBy whitelist documented on every
// /api/usd-swaps-tape-v2 analytics route. `canonical` routes through
// `l.canonical_underlier_key` (see SDRUtils/core/underlier_canonical.py
// for the canonicalisation source of truth).
export type AnalyticsGroupBy = 'tape_label' | 'trade_type' | 'tenor' | 'canonical'

export type AnalyticsMetricKey =
  | 'fixed_rate'
  | 'dv01'
  | 'notional'
  | 'spread_to_mid'
  | 'tenor_years'

export type AnalyticsViewKey = 'INTRADAY' | 'DAILY_CLOSE' | 'DAILY_OHLC' | 'VOLUME'

export type AnalyticsRangeKey = '1D' | '1W' | '1M' | '3M' | '6M' | '1Y' | 'CUSTOM'

export type RarityBasis = 'combined' | 'custy' | 'idb'

export type PlatformKind = 'CUSTY' | 'IDB'

export type RarityZone = 'typical' | 'notable' | 'rare' | 'extreme'

// Canonical focused-trade shape the analytics surface consumes.
// Flattened / normalized off a UsdSwapTapeRow by useFocusedTrade.
export type FocusedTrade = {
  id: string
  tape_label: string
  package_structure: string
  package_tenors: string | null
  trade_type: string
  tenor_years: number
  // Headline-level fixed rate in basis points (e.g. 384.2 = 3.842%).
  fixed_rate_bps: number
  weighted_fixed_rate: number | null
  dv01_usd_per_bp: number
  notional_usd: number
  // 'PAY' or 'RCV' derived from leg direction aggregate.
  side: 'PAY' | 'RCV'
  platform: PlatformKind
  venue: string
  execution_start: string | null
  execution_session: string | null
  lifecycle_type: string | null
  is_block: boolean
  // Back-reference to the underlying row in case tabs want richer fields.
  source?: UsdSwapTapeRow
}

export type AnalyticsMetricConfig = {
  key: AnalyticsMetricKey
  label: string
  unit: string
  accessor: keyof FocusedTrade | null
}

export type TimeseriesPointAug = {
  ts: string
  idbClose: number | null
  custyClose: number | null
  idbDv01?: number | null
  custyDv01?: number | null
  idbNotional?: number | null
  custyNotional?: number | null
  idbPrints?: number | null
  custyPrints?: number | null
  // High/Low for OHLC — populated when view === 'DAILY_OHLC'.
  high?: number | null
  low?: number | null
  open?: number | null
  close?: number | null
}

export type HistogramBin = {
  binStart: number
  binEnd: number
  mid: number
  custy: number
  idb: number
  total: number
  cumPct: number
  kdeScaled: number
}

export type DistributionStats = {
  count: number
  mean: number
  stddev: number
  median: number
  p5: number
  p25: number
  p75: number
  p95: number
  iqr: number
  min: number
  max: number
}

export type MetricRow = {
  key: AnalyticsMetricKey
  label: string
  value: number
  displayValue: string
  percentile: number | null
  zone: RarityZone | null
  descriptor: string
  sampleSize: number
  primary?: boolean
  showPercentile: boolean
}

export type RecencyEntry = {
  daysAgo: number
  date: string
  value: number
  venue: string
  platform: PlatformKind
  tradeId?: string
}

// All sub-records may come back null when the focused bucket has no
// qualifying data (e.g. no similar print in the lookback, or notional
// missing on every leg making bucket-rank meaningless). The Rarity tab
// renders a per-card empty state in those cases.
export type AllTimeExtreme = {
  value: number
  displayValue: string
  date: string
  platform: PlatformKind
  venue: string
}

export type RecencyBucket = {
  lastSimilar: RecencyEntry | null
  frequency90d: { count: number; avgIntervalDays: number; lookbackDays: number } | null
  allTimeRecord: {
    largestNotional: AllTimeExtreme | null
    highestRate: AllTimeExtreme | null
    lowestRate: AllTimeExtreme | null
  } | null
  bucketRank: { rank: number; total: number; by: string } | null
}

export type ExtremeScope = 'All-time' | '52 weeks' | '30 days'

export type ExtremeRow = {
  label: string
  scope: ExtremeScope
  rate: number
  dv01: number
  notional: number
  ts: string
  venue: string
  platform: PlatformKind
}

export type RecentSimilarRow = {
  daysAgo: number
  date: string
  rate: number
  dv01: number
  notional: number
  platform: PlatformKind
  venue: string
}

export type LevelsPlatformFilter = 'all' | 'custy' | 'idb'

export type LevelsScopeFilter = 'all' | 'all-time' | '52w' | '30d'

export type LevelsSortKey = 'relevance' | 'closest' | 'rate' | 'dv01' | 'notional' | 'time'

export type LevelsRecentSortKey = 'newest' | 'closest' | 'largest'

export type LevelsState = {
  platform: LevelsPlatformFilter
  scope: LevelsScopeFilter
  sortBy: LevelsSortKey
  recentSortBy: LevelsRecentSortKey
  primaryTol: string
  sizeTolPct: string
}

// UI state for Tab 1 (Timeseries).
export type TimeseriesState = {
  view: AnalyticsViewKey
  metric: AnalyticsMetricKey
  range: AnalyticsRangeKey
  showCusty: boolean
  showIdb: boolean
  showSigmaBands: boolean
  showIqrBand: boolean
  showDots: boolean
  useGrossDv01: boolean
  // Trader-requested: exclude absurd custy prints (> 5× median notional)
  // from the chart so outliers don't dominate the y-axis scale.
  excludeComicallyLargeCusty: boolean
  yMin: string
  yMax: string
  // Phase 4: bucket selector. Default 'tape_label' preserves existing
  // behaviour; switching to 'canonical' pivots the chart to a canonical
  // underlier key (USD/SOFR-OIS/COMPOUND etc.) so analysts see Term-SOFR
  // / Compounded-SOFR / Fed-Funds OIS at one click instead of unioning
  // ad-hoc tape labels.
  groupBy: AnalyticsGroupBy
  canonicalKey: string | null
}

// Multi-trade dock workstream — sequence-level summary fields the
// SequenceBar + SequenceTab renders against. All numeric fields are
// in the same units as their FocusedTrade counterparts (DV01 in
// USD/bp, weighted rate in basis points, notional in USD).
export interface SequenceAggregate {
  count: number
  totalDv01Usd: number
  weightedFixedRateBps: number
  totalNotionalUsd: number
  // Span between the earliest and latest execution_start in the
  // sequence. Null when any element has a missing execution_start
  // (which would otherwise produce a misleading span value).
  timeSpanMs: number | null
  startTs: string | null
  endTs: string | null
  sideMix: { pay: number; rcv: number }
  // Venue → count map. Order is insertion-order matching iteration
  // through the sequence so the SequenceBar can render chips in a
  // stable order without re-sorting.
  venueMix: Record<string, number>
}

// UI state for Tab 2 (Rarity).
export type RarityState = {
  basis: RarityBasis
  histogramMetric: AnalyticsMetricKey
  settingsOpen: boolean
  primaryTol: number
  sizeTol: number
}
