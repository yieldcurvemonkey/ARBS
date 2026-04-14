import type { UsdSwapTapeRow } from '../../types'

export function indexTone(index: string | null | undefined): string {
  switch (index) {
    case 'SOFR':
      return 'bg-emerald-900/40 text-emerald-200'
    case 'FED_FUNDS':
      return 'bg-amber-900/40 text-amber-200'
    default:
      return 'bg-slate-800/60 text-slate-300'
  }
}

export function structureOf(row: UsdSwapTapeRow): string {
  if (row.package_structure) return row.package_structure
  if (row.package_type) return String(row.package_type)
  return ''
}
