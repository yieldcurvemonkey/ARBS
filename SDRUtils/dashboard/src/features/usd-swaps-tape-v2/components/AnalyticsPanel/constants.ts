// Analytics-dock-local constants: option lists for the segmented controls
// + rarity-zone → Tailwind class maps.
import type {
  AnalyticsMetricConfig,
  AnalyticsRangeKey,
  AnalyticsViewKey,
  RarityZone,
} from './analytics-types'

export const ANALYTICS_METRICS: AnalyticsMetricConfig[] = [
  { key: 'fixed_rate',    label: 'Fixed Rate',    unit: 'bps',     accessor: 'fixed_rate_bps' },
  { key: 'dv01',          label: 'DV01',          unit: 'USD/bp',  accessor: 'dv01_usd_per_bp' },
  { key: 'notional',      label: 'Notional',      unit: 'USD mm',  accessor: 'notional_usd' },
  { key: 'spread_to_mid', label: 'Spread to Mid', unit: 'bps',     accessor: null },
  { key: 'tenor_years',   label: 'Tenor',         unit: 'years',   accessor: 'tenor_years' },
]

export const ANALYTICS_VIEWS: Array<{ key: AnalyticsViewKey; label: string }> = [
  { key: 'INTRADAY',    label: 'Intraday' },
  { key: 'DAILY_CLOSE', label: 'Daily Close' },
  { key: 'DAILY_OHLC',  label: 'Daily OHLC' },
  { key: 'VOLUME',      label: 'Volume' },
]

export const ANALYTICS_RANGES: Array<{ key: AnalyticsRangeKey; label: string }> = [
  { key: '1D',     label: '1D' },
  { key: '1W',     label: '1W' },
  { key: '1M',     label: '1M' },
  { key: '3M',     label: '3M' },
  { key: '6M',     label: '6M' },
  { key: '1Y',     label: '1Y' },
  { key: 'CUSTOM', label: 'Custom' },
]

export const RANGE_DAYS: Record<AnalyticsRangeKey, number> = {
  '1D': 2, '1W': 7, '1M': 30, '3M': 90, '6M': 180, '1Y': 365, CUSTOM: 365,
}

// Phase 3 contrast pass: bumped saturation + lightness on dark theme so
// the rarity zones read distinctly even at small font sizes. Each zone
// now also carries an explicit ring color used by the percentile bars
// for a 4.5:1+ contrast ratio against the slate-950 dock backdrop.
export const ZONE_BG: Record<RarityZone, string> = {
  typical: 'bg-emerald-400',
  notable: 'bg-amber-400',
  rare: 'bg-rose-500',
  extreme: 'bg-rose-600',
}

export const ZONE_TEXT: Record<RarityZone, string> = {
  typical: 'text-emerald-200',
  notable: 'text-amber-200',
  rare: 'text-rose-200',
  extreme: 'text-rose-100',
}

export const ZONE_BORDER: Record<RarityZone, string> = {
  typical: 'border-emerald-400',
  notable: 'border-amber-400',
  rare: 'border-rose-500',
  extreme: 'border-rose-600',
}

// Dock chrome defaults.
export const DOCK_DEFAULT_VH = 62
export const DOCK_MIN_PX = 220
// Viewport - this much reserved for table above the dock.
export const DOCK_MAX_RESERVE_PX = 160

export const TIMESERIES_DEFAULT_STATE = {
  view: 'DAILY_CLOSE' as AnalyticsViewKey,
  metric: 'fixed_rate' as const,
  range: '1Y' as AnalyticsRangeKey,
  showCusty: true,
  showIdb: true,
  showSigmaBands: false,
  showIqrBand: true,
  showDots: false,
  useGrossDv01: false,
  excludeComicallyLargeCusty: true,
  yMin: '',
  yMax: '',
  // Phase 4: bucket selector defaults to tape_label so existing flows
  // are unchanged. See risk note 3 in the implementation plan — flip
  // the default in a follow-up after a week of co-existence.
  groupBy: 'tape_label' as const,
  canonicalKey: null as string | null,
}

export const RARITY_DEFAULT_STATE = {
  basis: 'combined' as const,
  histogramMetric: 'dv01' as const,
  settingsOpen: false,
  primaryTol: 2.0,
  sizeTol: 0.25,
}

export const LEVELS_DEFAULT_STATE = {
  platform: 'all' as const,
  scope: 'all' as const,
  sortBy: 'relevance' as const,
  recentSortBy: 'newest' as const,
  primaryTol: '2.0',
  sizeTolPct: '25',
}

// localStorage key for the rarity tab's per-trader preferences. Bumped
// on incompatible shape changes so old payloads parse cleanly to the
// default state instead of crashing the dock.
export const RARITY_PREFS_STORAGE_KEY = 'usd-swaps-tape-v2/rarity-prefs/v2'
