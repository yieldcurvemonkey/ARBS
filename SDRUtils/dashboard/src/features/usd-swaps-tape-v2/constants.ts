// Tokens and defaults for the USD swap tape v2 feature.
import type {
  EconomicClass,
  LifecycleType,
  TimeseriesMetricKey,
  TimeseriesRangeKey,
  TimeseriesViewKey,
} from './types'

export const POLL_INTERVAL_MS = 10_000
export const SIGNAL_POLL_MS = 3_000
export const FALLBACK_POLL_MS = 60_000
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
  // Phase 2-3 additions ordered after the original set so existing
  // dashboards that iterate the array don't reorder visually.
  'AMENDMENT',
  'NULL_FILL',
  'SCHED_AMORT',
  'ERROR',
  'ERROR_RECOVERY',
  'PORT_TRANSFER',
  'VALUATION',
  // OTHER is the catch-all bucket for lifecycle codes the SDR feed
  // didn't classify. Keep it last so the column-filter dropdown still
  // surfaces it and the lifecycle-pill renderer doesn't drop those
  // rows on the floor.
  'OTHER',
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
  AMENDMENT: 'AMND',
  NULL_FILL: 'NULL',
  SCHED_AMORT: 'SCHED',
  ERROR: 'EROR',
  ERROR_RECOVERY: 'REVI',
  PORT_TRANSFER: 'PRTO',
  VALUATION: 'VALU',
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
  // MODI sub-states. AMEND is a real economic event so it gets the same
  // emerald family as NEW; NULL_FILL and SCHED_AMORT are administrative
  // and fade to slate/neutral.
  AMENDMENT: 'bg-emerald-700/40 text-emerald-100 ring-1 ring-emerald-300/40',
  NULL_FILL: 'bg-slate-700/30 text-slate-200 ring-1 ring-slate-400/30 italic',
  SCHED_AMORT: 'bg-cyan-700/30 text-cyan-100 ring-1 ring-cyan-300/40 italic',
  // §45.14 error/recovery — yellow-ish to draw the trader's eye.
  ERROR: 'bg-yellow-700/40 text-yellow-100 ring-1 ring-yellow-300/50',
  ERROR_RECOVERY: 'bg-yellow-500/30 text-yellow-100 ring-1 ring-yellow-300/40',
  PORT_TRANSFER: 'bg-zinc-600/30 text-zinc-200 ring-1 ring-zinc-400/30',
  // VALU/MARU are EOD valuations — explicitly muted so they don't compete
  // visually with real lifecycle activity.
  VALUATION: 'bg-zinc-800/40 text-zinc-400 ring-1 ring-zinc-600/30',
  OTHER: 'bg-slate-500/30 text-slate-100 ring-1 ring-slate-400/40',
}

// Phase 3 economic-class column palette. The matrix is the source of
// truth for every flow/volume/PnL aggregator; the dashboard surfaces
// the kind directly so traders can see *why* a row is or isn't in flow.
export const ECONOMIC_CLASS_LABELS: Record<EconomicClass, string> = {
  ECONOMIC_FLOW: 'FLOW',
  ECONOMIC_UNWIND: 'UNW',
  ECONOMIC_AMENDMENT: 'AMND',
  RESTATEMENT: 'RST',
  ADMINISTRATIVE: 'ADMIN',
  VALUATION: 'VALU',
  ERROR: 'EROR',
  ERROR_RECOVERY: 'REVI',
  UNKNOWN: '?',
}

export const ECONOMIC_CLASS_TONES: Record<EconomicClass, string> = {
  ECONOMIC_FLOW: 'bg-emerald-500/30 text-emerald-100 ring-1 ring-emerald-400/40',
  ECONOMIC_UNWIND: 'bg-red-500/30 text-red-100 ring-1 ring-red-400/40',
  ECONOMIC_AMENDMENT: 'bg-emerald-700/40 text-emerald-100 ring-1 ring-emerald-300/40',
  RESTATEMENT: 'bg-orange-500/30 text-orange-100 ring-1 ring-orange-400/40',
  ADMINISTRATIVE: 'bg-zinc-700/30 text-zinc-300 ring-1 ring-zinc-500/30 italic',
  VALUATION: 'bg-zinc-800/40 text-zinc-400 ring-1 ring-zinc-600/30',
  ERROR: 'bg-yellow-700/40 text-yellow-100 ring-1 ring-yellow-300/50',
  ERROR_RECOVERY: 'bg-yellow-500/30 text-yellow-100 ring-1 ring-yellow-300/40',
  UNKNOWN: 'bg-fuchsia-700/40 text-fuchsia-100 ring-1 ring-fuchsia-300/50',
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
  CURVE: '!bg-blue-900/50',
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
  // groups them with their base class, but drop the alpha further (~½ the
  // base CURVE/FLY tint) so a SPREADOVER_CURVE reads as a clearly lighter
  // "derivative" variant of an outright CURVE on first glance.
  SPREADOVER_CURVE: '!bg-blue-900/15',
  MATCHED_MATURITY_CURVE: '!bg-blue-900/15',
  SPREADOVER_FLY: '!bg-yellow-900/10',
  MATCHED_MATURITY_FLY: '!bg-yellow-900/10',
  BASIS: '!bg-emerald-900/30',
  BASIS_SWAP: '!bg-emerald-900/30',
  BASIS_CURVE: '!bg-emerald-900/15',
  BASIS_FLY: '!bg-emerald-900/10',
}

export const TRADE_TYPE_DEFAULT_ROW_TONE = '!bg-gray-900/30'

export const FLAG_CHIP_TONES = {
  BLK: 'bg-orange-900/40 text-orange-200',
  UFRO: 'bg-orange-900/40 text-orange-200',
  OFF_MKT: 'bg-rose-600/30 text-rose-100 ring-1 ring-rose-500/50',
  CAPPED: 'bg-rose-900/40 text-rose-200',
  OFF_DATE: 'bg-yellow-900/40 text-yellow-200',
  NSTD: 'bg-purple-900/40 text-purple-200',
  FOMC: 'bg-amber-900/40 text-amber-200',
  // Phase 4-5 compliance / data-quality chips. Distinct red/violet hues
  // so the trader can visually triage state-machine vs cap-band issues
  // when scanning the tape.
  VIOL: 'bg-red-900/60 text-red-100 ring-1 ring-red-500/60',
  CAP_BAND: 'bg-rose-900/60 text-rose-100 ring-1 ring-rose-400/40',
  FREQ_ANOM: 'bg-fuchsia-900/40 text-fuchsia-200',
  D2_MISS: 'bg-amber-900/60 text-amber-100',
  TRUNC: 'bg-yellow-900/40 text-yellow-200',
  CLR_ACC: 'bg-teal-900/40 text-teal-200',
  P43_OFF: 'bg-zinc-800/60 text-zinc-300',
} as const

export const TAPE_TAG_TONES: Record<string, string> = {
  OFFM: 'bg-red-900/50 text-red-200',
  UNWIND: 'bg-amber-900/40 text-amber-200',
  UFRO: 'bg-orange-900/40 text-orange-200',
  BLOCK: 'bg-sky-900/40 text-sky-200',
  TERM: 'bg-zinc-700/50 text-zinc-300',
  CORR: 'bg-zinc-700/50 text-zinc-300',
  MODI: 'bg-zinc-700/50 text-zinc-300',
  'XD-TERM': 'bg-zinc-700/50 text-zinc-300',
  'PARTIAL-UNWIND': 'bg-amber-900/40 text-amber-200',
  'NOVA-IN': 'bg-cyan-900/40 text-cyan-200',
  'NOVA-OUT': 'bg-cyan-900/40 text-cyan-200',
  EXER: 'bg-cyan-900/40 text-cyan-200',
  CLRG: 'bg-zinc-700/50 text-zinc-300',
  'PAST-EFF': 'bg-amber-500/25 text-amber-200 ring-1 ring-amber-500/40',
  'OFF-MKT': 'bg-rose-600/30 text-rose-100 ring-1 ring-rose-500/50',
}

export const TIMESERIES_METRICS: Array<{ key: TimeseriesMetricKey; label: string }> = [
  { key: 'notional', label: 'Notional' },
  { key: 'risk', label: 'DV01' },
  { key: 'trade_count', label: 'Trade Count' },
  { key: 'fixed_rate', label: 'Weighted Fixed Rate' },
  { key: 'pts', label: 'PTS (bp)' },
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
  // Phase 3: Economic-vs-Admin matrix kind, surfaced as a column so
  // traders can immediately see *why* a row is/isn't in flow.
  { key: 'class', header: 'Class', width: 84 },
  { key: 'platform', header: 'Platform', width: 120 },
  { key: 'pkg', header: 'Pkg', width: 96 },
  { key: 'pkg_ind', header: 'Pkg Ind', width: 84 },
  { key: 'tape_label', header: 'Tape Label', width: 700 },
  { key: 'risk_or_notional', header: 'Risk', width: 110 }, // toggles to Notional
  { key: 'rate', header: 'Reported LvL', width: 110 },
  { key: 'other_lvl', header: 'Other Lvl', width: 110 },
  // Phase 4-5 compliance/quality flag stack (state-machine, cap-band,
  // freq anomaly, schedule truncation, d2-missing, clearing-accept lag).
  { key: 'quality', header: 'Q', width: 96 },
] as const

export const CLEAN_TAPE_HIDDEN_LIFECYCLES: LifecycleType[] = [
  'UNWIND',
  'COMPRESSION',
  'RESET_OPT',
  'CLEARING_TERM',
  // Phase 3 admin classes — "clean tape" hides VALU spam, null-fills, and
  // scheduled amortization steps so the trader sees only economic events.
  'NULL_FILL',
  'SCHED_AMORT',
  'VALUATION',
  'PORT_TRANSFER',
]

export const DEFAULT_FLAG_FILTER_STATE = {
  lifecycleAllSelected: true,
  clean: false,
}

// ---------------------------------------------------------------
// Package-detection confidence (see docs/plans/2026-05-03-package-confidence-design.md).
// computePackageConfidence() in ../utils/packageConfidence.ts reads these.
// Exposed as constants so the desk can tune without code rewrites.
// ---------------------------------------------------------------
export const PACKAGE_CONFIDENCE_TOLERANCES = {
  /** ± bp window for derived-spread vs reported PTS match. */
  ptsMatchBp: 0.5,
  /** Relative tolerance for risk-balance checks (10% = 0.10). */
  riskBalanceRel: 0.10,
}

export const PACKAGE_CONFIDENCE_TONES = {
  /** All signals passed. */
  high: 'bg-emerald-900/40 text-emerald-200 ring-1 ring-emerald-400/40',
  /** One signal failed. */
  medium: 'bg-amber-900/40 text-amber-200 ring-1 ring-amber-400/40',
  /** Multiple signals failed. */
  low: 'bg-rose-900/40 text-rose-200 ring-1 ring-rose-400/40',
  /** OUTRIGHT structural-only check — informational, not a quality grade. */
  info: 'bg-slate-800/60 text-slate-300 ring-1 ring-slate-600/40',
} as const
