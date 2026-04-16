// ABOUTME: Pure URL <-> DataTableFilterMeta helpers for useColumnFilters.
// Split from the hook so tests can exercise the round-trip without mocking
// the Next.js router.
import { FilterMatchMode, FilterOperator } from 'primereact/api'
import type { DataTableFilterMeta } from 'primereact/datatable'
import {
  buildColumnFilterPayload,
  DEFAULT_NUMERIC_MATCH_MODE,
  DEFAULT_TEXT_MATCH_MODE,
  isEmptyFilterValue,
  type ColumnFilterPayload,
} from '../components/TradeTapeTable/filter-utils'

// Menu-mode filter shape (PrimeReact uses `{ operator, constraints[] }` per
// field when `filterDisplay="menu"`). Seeding every filterable column with an
// empty AND/contains entry lets the popup overlay render a populated form
// (Match All / Contains / input / Add Rule) on first open.
export function buildInitialFilters(): DataTableFilterMeta {
  const text = () => ({
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_TEXT_MATCH_MODE }],
  })
  const numeric = () => ({
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_NUMERIC_MATCH_MODE }],
  })
  return {
    execution_start: text(),
    lifecycle_type: text(),
    platform_identifier: text(),
    tape_label: text(),
    total_risk: numeric(),
    total_notional: numeric(),
    weighted_fixed_rate: numeric(),
    other_lvl_reported: text(),
  } as DataTableFilterMeta
}

// Tolerant of two URL shapes:
//   1. Flat (current writer):   { field: { value, matchMode } }
//   2. Menu (legacy bookmarks): { field: { operator, constraints[...] } }
// In both cases we hydrate back into the menu-mode shape the overlay form
// expects.
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
    if (!rawFilter || typeof rawFilter !== 'object') continue
    const constraintsList: Array<{ value: unknown; matchMode?: string }> =
      Array.isArray((rawFilter as any).constraints)
        ? (rawFilter as any).constraints.filter(
            (c: any) => !isEmptyFilterValue(c?.value),
          )
        : !isEmptyFilterValue((rawFilter as any).value)
          ? [
              {
                value: (rawFilter as any).value,
                matchMode: (rawFilter as any).matchMode,
              },
            ]
          : []
    if (!constraintsList.length) continue
    next[field] = {
      operator:
        (rawFilter as any).operator === FilterOperator.OR
          ? FilterOperator.OR
          : FilterOperator.AND,
      constraints: constraintsList.map((c) => ({
        value: c.value,
        matchMode: (c.matchMode ?? FilterMatchMode.CONTAINS) as any,
      })),
    } as any
  }
  return next
}

// Merge URL-rehydrated filters on top of the INITIAL_FILTERS scaffold so
// every column always has a renderable entry in the overlay while still
// honoring user-applied constraints from the URL.
export function mergeWithInitialFilters(
  rehydrated: DataTableFilterMeta,
): DataTableFilterMeta {
  const base = buildInitialFilters() as Record<string, any>
  const next: Record<string, any> = { ...base }
  for (const [field, value] of Object.entries(rehydrated ?? {})) {
    next[field] = value
  }
  return next as DataTableFilterMeta
}

export function serializeFilters(filters: DataTableFilterMeta): string {
  const payload = buildColumnFilterPayload(filters)
  if (!Object.keys(payload).length) return ''
  return JSON.stringify(payload)
}
