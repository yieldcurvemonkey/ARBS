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

// Seed every filterable column with an empty AND-constrained entry so
// PrimeReact's menu-mode filter overlay has a `{operator, constraints}`
// object to render (Match All / Contains / input / Add Rule). Without this
// the overlay renders only the Clear/Apply footer.
export function buildInitialFilters(): DataTableFilterMeta {
  const textField = () => ({
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_TEXT_MATCH_MODE }],
  })
  const numericField = () => ({
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_NUMERIC_MATCH_MODE }],
  })
  return {
    execution_start: textField(),
    lifecycle_type: textField(),
    platform_identifier: textField(),
    tape_label: textField(),
    total_risk: numericField(),
    total_notional: numericField(),
    weighted_fixed_rate: numericField(),
    other_lvl_reported: textField(),
  } as DataTableFilterMeta
}

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
