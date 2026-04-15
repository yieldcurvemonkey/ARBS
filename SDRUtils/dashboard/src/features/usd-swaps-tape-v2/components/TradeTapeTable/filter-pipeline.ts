// ABOUTME: Pure client-side pipeline — fuzzy search, column filters, sort —
// layered on top of the server-fetched rows. Mirrors SwaptionTradeTape pattern.
import { FilterMatchMode } from 'primereact/api'
import type { DataTableFilterMeta } from 'primereact/datatable'
import type { UsdSwapTapeRow } from '../../types'
import { fuzzyBestScore } from '../../utils/fuzzy'

const FUZZY_FIELDS: Array<(row: UsdSwapTapeRow) => string | null | undefined> = [
  (r) => r.tape_label,
  (r) => r.platform_identifier,
  (r) => (r as any).trade_type,
  (r) => r.package_type,
  (r) => r.package_id,
  (r) =>
    (r.legs_json ?? [])
      .map((l: any) => l.tape_label)
      .filter(Boolean)
      .join(' '),
]

export function applyFuzzy(rows: UsdSwapTapeRow[], query: string): UsdSwapTapeRow[] {
  const q = (query ?? '').trim()
  if (!q) return rows
  return rows.filter((row) => {
    const fields = FUZZY_FIELDS.map((f) => f(row))
    return fuzzyBestScore(q, fields) >= 0
  })
}

function matchOne(value: any, matchValue: any, mode: string): boolean {
  if (matchValue === null || matchValue === undefined || matchValue === '') return true
  if (value === null || value === undefined) return false
  switch (mode) {
    case FilterMatchMode.EQUALS: {
      if (typeof value === 'number') return Number(value) === Number(matchValue)
      return String(value).toLowerCase() === String(matchValue).toLowerCase()
    }
    case FilterMatchMode.NOT_EQUALS: {
      if (typeof value === 'number') return Number(value) !== Number(matchValue)
      return String(value).toLowerCase() !== String(matchValue).toLowerCase()
    }
    case FilterMatchMode.STARTS_WITH:
      return String(value).toLowerCase().startsWith(String(matchValue).toLowerCase())
    case FilterMatchMode.ENDS_WITH:
      return String(value).toLowerCase().endsWith(String(matchValue).toLowerCase())
    case FilterMatchMode.GREATER_THAN:
      return Number(value) > Number(matchValue)
    case FilterMatchMode.GREATER_THAN_OR_EQUAL_TO:
      return Number(value) >= Number(matchValue)
    case FilterMatchMode.LESS_THAN:
      return Number(value) < Number(matchValue)
    case FilterMatchMode.LESS_THAN_OR_EQUAL_TO:
      return Number(value) <= Number(matchValue)
    case FilterMatchMode.CONTAINS:
    default:
      return String(value).toLowerCase().includes(String(matchValue).toLowerCase())
  }
}

export function applyColumnFilters(
  rows: UsdSwapTapeRow[],
  filters: DataTableFilterMeta | Record<string, any>,
  operator: 'and' | 'or' = 'and',
): UsdSwapTapeRow[] {
  const entries = Object.entries(filters ?? {}).filter(([, meta]) => {
    if (!meta) return false
    const m: any = meta
    const val = 'constraints' in m ? m.constraints?.[0]?.value : m.value
    return val !== null && val !== undefined && val !== ''
  })
  if (!entries.length) return rows
  return rows.filter((row) => {
    const matches = entries.map(([field, meta]) => {
      const m: any = meta
      const matchValue =
        'constraints' in m ? m.constraints?.[0]?.value : m.value
      const mode =
        ('constraints' in m ? m.constraints?.[0]?.matchMode : m.matchMode) ??
        FilterMatchMode.CONTAINS
      const value = (row as any)[field]
      return matchOne(value, matchValue, mode)
    })
    return operator === 'or'
      ? matches.some(Boolean)
      : matches.every(Boolean)
  })
}

export function applySort(
  rows: UsdSwapTapeRow[],
  sortField: string | null | undefined,
  sortOrder: 1 | -1 | 0,
): UsdSwapTapeRow[] {
  if (!sortField || sortOrder === 0) return rows
  const copy = [...rows]
  copy.sort((a, b) => {
    const av = (a as any)[sortField]
    const bv = (b as any)[sortField]
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    if (typeof av === 'number' && typeof bv === 'number') {
      return sortOrder === 1 ? av - bv : bv - av
    }
    const as = String(av).toLowerCase()
    const bs = String(bv).toLowerCase()
    if (as === bs) return 0
    return sortOrder === 1 ? (as > bs ? 1 : -1) : as < bs ? 1 : -1
  })
  return copy
}
