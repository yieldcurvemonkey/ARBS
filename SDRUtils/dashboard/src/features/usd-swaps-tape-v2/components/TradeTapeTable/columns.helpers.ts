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
function isInactiveLifecycle(row: UsdSwapTapeRow): boolean {
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
  if (row.is_clearing_termination_any) {
    return '!bg-red-950/60 !text-red-100 border-l-2 border-red-500'
  }
  if (row.is_unwind) return '!bg-red-900/40 !text-red-100'
  if (row.is_termination_any) return '!bg-rose-900/30 !text-rose-100'
  if (row.is_compression_any) return '!bg-zinc-900/50 !text-zinc-400 italic'
  if (row.is_reset_optimization_any)
    return '!bg-neutral-900/50 !text-neutral-400'
  return '!bg-red-900/30 !text-red-100'
}

// Softer tints for lifecycle events that are still "live" risk but worth
// flagging (novations, corrections). Layered on top of the trade-type tone
// via the optional secondary class.
function livelycleAccent(row: UsdSwapTapeRow): string {
  if (row.is_novation_any) return 'ring-1 ring-purple-500/30'
  if (row.is_correction_any) return 'ring-1 ring-sky-500/30'
  return ''
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
  return [tradeTypeTone(row), tradeTypeBorder(row), livelycleAccent(row)]
    .filter(Boolean)
    .join(' ')
}
