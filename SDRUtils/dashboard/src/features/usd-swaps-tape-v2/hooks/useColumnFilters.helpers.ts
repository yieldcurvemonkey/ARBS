// ABOUTME: Pure URL <-> DataTableFilterMeta helpers for useColumnFilters.
// Split from the hook so tests can exercise the round-trip without mocking
// the Next.js router.
import { FilterMatchMode, FilterOperator } from 'primereact/api'
import type { DataTableFilterMeta } from 'primereact/datatable'
import {
  buildColumnFilterPayload,
  isEmptyFilterValue,
  type ColumnFilterPayload,
} from '../components/TradeTapeTable/filter-utils'

export function rehydrateFilters(rawValue: string | null): DataTableFilterMeta {
  if (!rawValue) return {}
  let parsed: ColumnFilterPayload | null = null
  try {
    parsed = JSON.parse(rawValue) as ColumnFilterPayload
  } catch {
    return {}
  }
  if (!parsed || typeof parsed !== 'object') return {}
  const next: DataTableFilterMeta = {}
  for (const [field, rawFilter] of Object.entries(parsed)) {
    if (!rawFilter) continue
    const constraints = Array.isArray(rawFilter.constraints)
      ? rawFilter.constraints
      : []
    const active = constraints.filter((c) => !isEmptyFilterValue(c?.value))
    if (!active.length) continue
    next[field] = {
      operator:
        rawFilter.operator === FilterOperator.OR
          ? FilterOperator.OR
          : FilterOperator.AND,
      constraints: active.map((c) => ({
        value: c.value,
        matchMode: (c.matchMode ?? FilterMatchMode.CONTAINS) as any,
      })),
    }
  }
  return next
}

export function serializeFilters(filters: DataTableFilterMeta): string {
  const payload = buildColumnFilterPayload(filters)
  if (!Object.keys(payload).length) return ''
  return JSON.stringify(payload)
}
