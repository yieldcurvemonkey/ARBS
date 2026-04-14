// Pure row-class mapping — testable without React.
import type { UsdSwapTapeRow } from '../../types'

export function rowClassName(row: UsdSwapTapeRow): string {
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
