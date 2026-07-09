// Pure row-class mapping — testable without React.
//
// Mirrors the swaption tape row-coloring model (see SwaptionTradeTape.tsx.bak):
// each row gets a persistent background tint by package / trade type when the
// lifecycle is a normal new-risk / trade, and flips to a red "inactive" tone
// when the row represents a lifecycle event we want the trader to treat as
// warning or read-only (unwind, compression, termination, etc.).
import {
  TRADE_TYPE_DEFAULT_ROW_TONE,
  TRADE_TYPE_ROW_TONES,
} from '../../constants'
import type { UsdSwapTapeRow } from '../../types'

const PACKAGE_BADGE_TONES: Record<string, string> = {
  OUTRIGHT: 'border-slate-600/40 bg-slate-800/60 text-slate-200',
  CURVE: 'border-sky-500/40 bg-sky-900/40 text-sky-200',
  FLY: 'border-indigo-500/40 bg-indigo-900/40 text-indigo-200',
  BASIS: 'border-emerald-500/40 bg-emerald-900/40 text-emerald-200',
  BASIS_CURVE: 'border-emerald-500/40 bg-emerald-900/40 text-emerald-200',
  BASIS_FLY: 'border-emerald-500/40 bg-emerald-900/40 text-emerald-200',
  MATCHED_MATURITY: 'border-teal-500/40 bg-teal-900/40 text-teal-200',
  MATCHED_MATURITY_CURVE: 'border-sky-500/40 bg-sky-900/40 text-sky-200',
  MATCHED_MATURITY_FLY: 'border-indigo-500/40 bg-indigo-900/40 text-indigo-200',
}

const PACKAGE_LABELS: Record<string, string> = {
  OUTRIGHT: 'Outright',
  CURVE: 'Curve',
  FLY: 'Fly',
  BASIS: 'Basis',
  BASIS_CURVE: 'B.Curve',
  BASIS_FLY: 'B.Fly',
  MATCHED_MATURITY: 'MMS',
  MATCHED_MATURITY_CURVE: 'MMS Curve',
  MATCHED_MATURITY_FLY: 'MMS Fly',
}

// Left-edge accent borders, kept from the original palette — they're a second
// cheap signal orthogonal to the full-row tint (useful when a trader is color
// blind or viewing on a dim screen).
const TRADE_TYPE_BORDER: Record<string, string> = {
  OUTRIGHT: 'border-l-2 border-slate-600/70',
  CURVE: 'border-l-2 border-sky-500/70',
  FLY: 'border-l-2 border-indigo-500/70',
  SPREADOVER: 'border-l-2 border-fuchsia-500/70',
  MATCHED_MATURITY: 'border-l-2 border-teal-500/70',
  MAC: 'border-l-2 border-cyan-500/70',
  IMM: 'border-l-2 border-lime-500/70',
  FOMC: 'border-l-2 border-amber-500/70',
  // Composite CURVE / FLY variants share the base family's accent color but
  // at lower opacity, mirroring the row-tint dimming in
  // constants.TRADE_TYPE_ROW_TONES.
  SPREADOVER_CURVE: 'border-l-2 border-sky-500/50',
  MATCHED_MATURITY_CURVE: 'border-l-2 border-sky-500/50',
  SPREADOVER_FLY: 'border-l-2 border-indigo-500/50',
  MATCHED_MATURITY_FLY: 'border-l-2 border-indigo-500/50',
  BASIS: 'border-l-2 border-emerald-500/70',
  BASIS_SWAP: 'border-l-2 border-emerald-500/70',
  BASIS_CURVE: 'border-l-2 border-emerald-500/50',
  BASIS_FLY: 'border-l-2 border-emerald-500/50',
}

function tradeTypeKey(row: UsdSwapTapeRow): string {
  return (row as any).trade_type ?? row.package_type ?? ''
}

function tradeTypeBorder(row: UsdSwapTapeRow): string {
  return TRADE_TYPE_BORDER[tradeTypeKey(row)] ?? ''
}

function tradeTypeTone(row: UsdSwapTapeRow): string {
  return TRADE_TYPE_ROW_TONES[tradeTypeKey(row)] ?? TRADE_TYPE_DEFAULT_ROW_TONE
}

// Lifecycles we render as "inactive" — unwinds, compressions, resets, and
// terminations are not fresh risk; the trader scans past them. Red/neutral
// tones make that distinction pop without hiding the row outright.
//
// Phase 3 cutover: when the matrix tags a row as ADMINISTRATIVE / VALUATION,
// it's never "fresh risk" regardless of the legacy is_*_any signals — gate
// on `contributes_to_flow_any === false` so β/γ clearing, partial novations,
// VALU spam, and null-fill MODIs all read as inactive consistently.
function isInactiveLifecycle(row: UsdSwapTapeRow): boolean {
  if (row.contributes_to_flow_any === false) return true
  // State-machine violations are critical compliance signals — promote
  // them to the inactive branch so the yellow tone wins regardless of
  // the underlying trade type or new-risk status.
  if (row.state_machine_violation_any) return true
  return Boolean(
    row.is_clearing_termination_any ||
      row.is_unwind ||
      row.is_termination_any ||
      row.is_compression_any ||
      row.is_reset_optimization_any,
  )
}

// A more granular tone for the "inactive" branch so we can still tell unwinds
// from compressions from clearing-terminations at a glance. Loosely mirrors
// the original lifecycleClass heuristics.
function inactiveLifecycleTone(row: UsdSwapTapeRow): string {
  // State-machine violations dominate any other signal — they're the
  // most actionable thing on the row, so paint them yellow regardless.
  if (row.state_machine_violation_any) {
    return '!bg-yellow-900/40 !text-yellow-100 border-l-2 border-yellow-400'
  }
  if (row.is_clearing_termination_any) {
    return '!bg-red-950/60 !text-red-100 border-l-2 border-red-500'
  }
  if (row.is_unwind) return '!bg-red-900/40 !text-red-100'
  if (row.is_termination_any) return '!bg-rose-900/30 !text-rose-100'
  if (row.is_compression_any) return '!bg-zinc-900/50 !text-zinc-400 italic'
  if (row.is_reset_optimization_any)
    return '!bg-neutral-900/50 !text-neutral-400'
  // Phase 3: administrative-only branch — null-fills, scheduled
  // amortization, port transfers, VALU. Render muted slate so they
  // don't compete with the trader's eye scan for real economic events.
  if (row.contributes_to_flow_any === false) {
    return '!bg-slate-900/40 !text-slate-400 italic'
  }
  return '!bg-red-900/30 !text-red-100'
}

// Softer tints for lifecycle events that are still "live" risk but worth
// flagging (novations, corrections). Layered on top of the trade-type tone
// via the optional secondary class.
function lifecycleAccent(row: UsdSwapTapeRow): string {
  // State-machine violation > everything else: yellow ring even on
  // active rows so the data-quality signal is impossible to miss.
  if (row.state_machine_violation_any) return 'ring-2 ring-yellow-400/60'
  if (row.is_novation_any) return 'ring-1 ring-purple-500/30'
  if (row.is_correction_any) return 'ring-1 ring-sky-500/30'
  return ''
}

export function normalizePackageType(value: unknown): string {
  const normalized = String(value ?? '')
    .trim()
    .toUpperCase()
  if (!normalized || normalized === 'NAN' || normalized === 'NONE') {
    return 'OUTRIGHT'
  }
  return normalized
}

export function packageTypeDisplayLabel(value: unknown): string {
  const normalized = normalizePackageType(value)
  return PACKAGE_LABELS[normalized] ?? normalized
}

export function packageTypeBadgeClassName(value: unknown): string {
  return PACKAGE_BADGE_TONES[normalizePackageType(value)] ?? PACKAGE_BADGE_TONES.OUTRIGHT
}

export function packageIndicatorDisplay(value: unknown): string {
  // Null/undefined means the column isn't populated on this row (e.g. DB view
  // lags the tape ingest). Showing "false" would be wrong — the SDR flag is
  // genuinely unknown, not False — so fall back to the shared empty marker.
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (normalized === '' || normalized === 'nan' || normalized === 'none' || normalized === 'null') {
      return '—'
    }
    if (['true', 't', '1', 'yes', 'y'].includes(normalized)) {
      return 'true'
    }
    if (['false', 'f', '0', 'no', 'n'].includes(normalized)) {
      return 'false'
    }
  }
  if (typeof value === 'number') {
    if (Number.isNaN(value)) return '—'
    return value ? 'true' : 'false'
  }
  return value === true ? 'true' : 'false'
}

export function rowClassName(row: UsdSwapTapeRow): string {
  if (isInactiveLifecycle(row)) {
    // Clearing-termination already supplies its own red border — skip the
    // trade-type border to avoid a double-stripe.
    if (row.is_clearing_termination_any) {
      return inactiveLifecycleTone(row)
    }
    return [inactiveLifecycleTone(row), tradeTypeBorder(row)]
      .filter(Boolean)
      .join(' ')
  }
  return [tradeTypeTone(row), tradeTypeBorder(row), lifecycleAccent(row)]
    .filter(Boolean)
    .join(' ')
}
