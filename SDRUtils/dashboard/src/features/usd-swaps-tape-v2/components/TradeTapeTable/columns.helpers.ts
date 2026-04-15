// Pure row-class mapping — testable without React.
import type { UsdSwapTapeRow } from '../../types'

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

function tradeTypeBorder(row: UsdSwapTapeRow): string {
  const key = (row as any).trade_type ?? row.package_type ?? ''
  return TRADE_TYPE_BORDER[key] ?? ''
}

function lifecycleClass(row: UsdSwapTapeRow): string {
  if (row.is_clearing_termination_any)
    return 'bg-red-950/40 border-l-2 border-red-500'
  if (row.is_unwind) return 'bg-red-950/25 text-red-100'
  if (row.is_termination_any && !row.is_compression_any)
    return 'bg-rose-950/30 text-rose-100'
  if (row.is_compression_any) return 'bg-zinc-900/40 text-zinc-400 italic'
  if (row.is_novation_any) return 'bg-purple-950/25 text-purple-100'
  if (row.is_reset_optimization_any)
    return 'bg-neutral-900/40 text-neutral-500 text-xs'
  if (row.is_correction_any) return 'bg-sky-950/20 text-sky-100'
  return ''
}

export function rowClassName(row: UsdSwapTapeRow): string {
  const lifecycle = lifecycleClass(row)
  // Clearing-termination already provides its own red border — don't layer.
  if (row.is_clearing_termination_any) return lifecycle
  const border = tradeTypeBorder(row)
  return [lifecycle, border].filter(Boolean).join(' ')
}
