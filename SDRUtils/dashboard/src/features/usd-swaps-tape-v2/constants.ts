// Tokens and defaults for the USD swap tape v2 feature.
import type { LifecycleType, TimeseriesMetricKey, TimeseriesViewKey } from './types'

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
export const LIFECYCLE_TONES: Record<LifecycleType, string> = {
  NEW_RISK: 'bg-emerald-900/40 text-emerald-200',
  UNWIND: 'bg-red-900/40 text-red-200',
  COMPRESSION: 'bg-zinc-800/60 text-zinc-400',
  TERMINATION: 'bg-rose-900/40 text-rose-200',
  NOVATION: 'bg-purple-900/40 text-purple-200',
  RESET_OPT: 'bg-neutral-800/60 text-neutral-400',
  CORRECTION: 'bg-sky-900/40 text-sky-200',
  CLEARING_TERM: 'bg-red-950/60 text-red-100 border border-red-500/40',
  EXERCISE_BORN: 'bg-amber-900/40 text-amber-200',
  OTHER: 'bg-slate-800/60 text-slate-300',
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
export const TRADE_TYPE_ROW_TONES: Record<string, string> = {
  OUTRIGHT: '!bg-gray-800/50',
  CURVE: '!bg-sky-900/30',
  FLY: '!bg-indigo-900/30',
  SPREADOVER: '!bg-fuchsia-900/30',
  MATCHED_MATURITY: '!bg-teal-900/30',
  MAC: '!bg-cyan-900/30',
  IMM: '!bg-lime-900/30',
  FOMC: '!bg-amber-900/30',
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
]

// Default column definitions — consumed by TradeTapeTable/columns.tsx
export const COLUMN_DEFS = [
  { key: 'select', header: '', width: 40 },
  { key: 'expand', header: '', width: 48 },
  { key: 'time', header: 'Time', width: 190 },
  { key: 'action', header: 'Action', width: 132 },
  { key: 'platform', header: 'Platform', width: 120 },
  { key: 'tape_label', header: 'Tape Label', width: 700 },
  { key: 'risk_or_notional', header: 'DV01', width: 110 }, // toggles to Notional
  { key: 'rate', header: 'Reported LvL', width: 110 },
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
