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

export const ZONE_BG: Record<RarityZone, string> = {
  typical: 'bg-emerald-500',
  notable: 'bg-amber-500',
  rare: 'bg-red-500',
  extreme: 'bg-red-600',
}

export const ZONE_TEXT: Record<RarityZone, string> = {
  typical: 'text-emerald-300',
  notable: 'text-amber-300',
  rare: 'text-red-300',
  extreme: 'text-red-200',
}

export const ZONE_BORDER: Record<RarityZone, string> = {
  typical: 'border-emerald-500',
  notable: 'border-amber-500',
  rare: 'border-red-500',
  extreme: 'border-red-600',
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
}

export const RARITY_DEFAULT_STATE = {
  basis: 'combined' as const,
  histogramMetric: 'fixed_rate' as const,
  settingsOpen: false,
  primaryTol: 2.0,
  sizeTol: 0.25,
}
