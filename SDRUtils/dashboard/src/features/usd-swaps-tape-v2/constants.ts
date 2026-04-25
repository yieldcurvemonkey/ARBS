// Tokens and defaults for the USD swap tape v2 feature.
import type {
  LifecycleType,
  TimeseriesMetricKey,
  TimeseriesRangeKey,
  TimeseriesViewKey,
} from './types'

export const POLL_INTERVAL_MS = 30_000
export const ROW_ESTIMATE_PX = 40
export const EMPTY_VALUE = '—'

export const TAPE_V2_API_BASE = '/api/usd-swaps-tape-v2'

export const LIFECYCLE_ORDER: LifecycleType[] = [
  'NEW_RISK',
  'UNWIND',
  'COMPRESSION',
  'TERMINATION',
  'NOVATION',
  'RESET_OPT',
  'CORRECTION',
  'CLEARING_TERM',
  'EXERCISE_BORN',
]

export const LIFECYCLE_LABELS: Record<LifecycleType, string> = {
  NEW_RISK: 'NEW',
  UNWIND: 'UNW',
  COMPRESSION: 'CMP',
  TERMINATION: 'TERM',
  NOVATION: 'NOVA',
  RESET_OPT: 'RST',
  CORRECTION: 'CORR',
  CLEARING_TERM: 'CLR',
  EXERCISE_BORN: 'XERC',
  OTHER: 'OTHER',
}

// Unified lifecycle palette — rendered as Tailwind class strings.
// NOTE(feedback-round-1): saturated variant + ring outline so lifecycle
// pills read cleanly against the new package-structure row tints.
export const LIFECYCLE_TONES: Record<LifecycleType, string> = {
  NEW_RISK: 'bg-emerald-500/30 text-emerald-100 ring-1 ring-emerald-400/40',
  UNWIND: 'bg-red-500/30 text-red-100 ring-1 ring-red-400/40',
  COMPRESSION: 'bg-sky-500/30 text-sky-100 ring-1 ring-sky-400/40',
  TERMINATION: 'bg-zinc-500/30 text-zinc-100 ring-1 ring-zinc-400/40',
  NOVATION: 'bg-violet-500/30 text-violet-100 ring-1 ring-violet-400/40',
  RESET_OPT: 'bg-amber-500/30 text-amber-100 ring-1 ring-amber-400/40',
  CORRECTION: 'bg-orange-500/30 text-orange-100 ring-1 ring-orange-400/40',
  CLEARING_TERM: 'bg-teal-500/30 text-teal-100 ring-1 ring-teal-400/40',
  EXERCISE_BORN: 'bg-pink-500/30 text-pink-100 ring-1 ring-pink-400/40',
  OTHER: 'bg-slate-500/30 text-slate-100 ring-1 ring-slate-400/40',
}

export const TRADE_TYPE_TONES: Record<string, string> = {
  OUTRIGHT: 'bg-slate-800/60 text-slate-300',
  CURVE: 'bg-sky-900/40 text-sky-200',
  FLY: 'bg-indigo-900/40 text-indigo-200',
  SPREADOVER: 'bg-fuchsia-900/40 text-fuchsia-200',
  MATCHED_MATURITY: 'bg-teal-900/40 text-teal-200',
  MAC: 'bg-cyan-900/40 text-cyan-200',
  IMM: 'bg-lime-900/40 text-lime-200',
  FOMC: 'bg-amber-900/40 text-amber-200',
}

// Full-row background tints keyed by trade_type / package_type, applied to
// every tape row. Mirrors the swaption tape's PACKAGE_TONES palette: distinct
// low-alpha colors per structure so the trader can at-a-glance tell curves
// from outrights from flies. `!bg-*` so the tint wins over PrimeReact's
// default tr styling.
// feedback-round-1: Bloomberg-muted row tints keyed by package_structure.
// UNWIND override wins via rowClassName's inactiveLifecycle branch.
export const TRADE_TYPE_ROW_TONES: Record<string, string> = {
  OUTRIGHT: '!bg-slate-800/30',
  CURVE: '!bg-blue-900/30',
  FLY: '!bg-yellow-900/25',
  STRADDLE: '!bg-teal-900/30',
  STRANGLE: '!bg-fuchsia-900/25',
  SPREADOVER: '!bg-fuchsia-900/30',
  MATCHED_MATURITY: '!bg-teal-900/30',
  MAC: '!bg-cyan-900/30',
  IMM: '!bg-lime-900/30',
  FOMC: '!bg-amber-900/30',
  // Composite CURVE / FLY families (SPREADOVER_*, MATCHED_MATURITY_*) are
  // still curves/flies structurally — keep the same hue so the trader's eye
  // groups them with their base class, but dim the alpha one notch so they
  // read as the "derivative" variant rather than a plain outright curve/fly.
  SPREADOVER_CURVE: '!bg-blue-900/20',
  MATCHED_MATURITY_CURVE: '!bg-blue-900/20',
  SPREADOVER_FLY: '!bg-yellow-900/15',
  MATCHED_MATURITY_FLY: '!bg-yellow-900/15',
}

export const TRADE_TYPE_DEFAULT_ROW_TONE = '!bg-gray-900/30'

export const FLAG_CHIP_TONES = {
  BLK: 'bg-orange-900/40 text-orange-200',
  UFRO: 'bg-orange-900/40 text-orange-200',
  OFF_MKT: 'bg-yellow-900/40 text-yellow-200',
  CAPPED: 'bg-rose-900/40 text-rose-200',
  OFF_DATE: 'bg-yellow-900/40 text-yellow-200',
  NSTD: 'bg-purple-900/40 text-purple-200',
  FOMC: 'bg-amber-900/40 text-amber-200',
} as const

export const TIMESERIES_METRICS: Array<{ key: TimeseriesMetricKey; label: string }> = [
  { key: 'notional', label: 'Notional' },
  { key: 'risk', label: 'DV01' },
  { key: 'trade_count', label: 'Trade Count' },
  { key: 'fixed_rate', label: 'Weighted Fixed Rate' },
]

export const TIMESERIES_VIEWS: Array<{ key: TimeseriesViewKey; label: string }> = [
  { key: 'INTRADAY', label: 'Intraday' },
  { key: 'DAILY_CLOSE', label: 'Daily close' },
  { key: 'DAILY_OHLC', label: 'Daily OHLC' },
  // VOLUME — daily-summed DV01 stacked-bar view. Swap analog of the
  // swaption tape's "daily vega" bar chart; trader asked for this shape
  // during the 2026-04 chat.
  { key: 'VOLUME', label: 'Volume' },
]

// Range presets for the analytics dock's timeseries tab. CUSTOM defers
// to a date-picker surface elsewhere in the UI.
export const TIMESERIES_RANGE_OPTIONS: Array<{ key: TimeseriesRangeKey; label: string }> = [
  { key: '1D', label: '1D' },
  { key: '1W', label: '1W' },
  { key: '1M', label: '1M' },
  { key: '3M', label: '3M' },
  { key: '6M', label: '6M' },
  { key: '1Y', label: '1Y' },
  { key: 'CUSTOM', label: 'Custom' },
]

// Default column definitions — consumed by TradeTapeTable/columns.tsx
export const COLUMN_DEFS = [
  { key: 'select', header: '', width: 40 },
  { key: 'expand', header: '', width: 48 },
  { key: 'time', header: 'Time', width: 190 },
  { key: 'action', header: 'Action', width: 132 },
  { key: 'platform', header: 'Platform', width: 120 },
  { key: 'pkg', header: 'Pkg', width: 96 },
  { key: 'pkg_ind', header: 'Pkg Ind', width: 84 },
  { key: 'tape_label', header: 'Tape Label', width: 700 },
  { key: 'risk_or_notional', header: 'Risk', width: 110 }, // toggles to Notional
  { key: 'rate', header: 'Reported LvL', width: 110 },
  { key: 'other_lvl', header: 'Other Lvl', width: 110 },
] as const

export const CLEAN_TAPE_HIDDEN_LIFECYCLES: LifecycleType[] = [
  'UNWIND',
  'COMPRESSION',
  'RESET_OPT',
  'CLEARING_TERM',
]

export const DEFAULT_FLAG_FILTER_STATE = {
  lifecycleAllSelected: true,
  clean: false,
}
