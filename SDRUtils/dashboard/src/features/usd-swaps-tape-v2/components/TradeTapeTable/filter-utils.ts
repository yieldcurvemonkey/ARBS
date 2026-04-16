// ABOUTME: Pure-logic per-column filter helpers — power the inline row
// filter inputs (filterDisplay="row") in TradeTapeTable.
import { FilterMatchMode, FilterOperator } from 'primereact/api'
import type { DataTableFilterMeta } from 'primereact/datatable'

export const DEFAULT_TEXT_MATCH_MODE = FilterMatchMode.CONTAINS
export const DEFAULT_NUMERIC_MATCH_MODE = FilterMatchMode.EQUALS

export type ColumnFilterConstraint = {
  value: any
  matchMode?: string
}

// URL payload shape — flat per-field { value, matchMode }. The legacy
// menu-mode { operator, constraints[] } shape is still understood by
// `rehydrateFilters` for back-compat with old bookmarks.
export type ColumnFilterPayload = Record<
  string,
  ColumnFilterConstraint & {
    operator?: string
    constraints?: ColumnFilterConstraint[]
  }
>

function isValid(value: any): boolean {
  return value !== null && value !== undefined && !Number.isNaN(value)
}

export function isEmptyFilterValue(value: any): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === 'string' && value.trim() === '') return true
  if (Array.isArray(value) && value.length === 0) return true
  return false
}

export function parseFilterNumber(value: any): number | null {
  if (typeof value === 'number' && !Number.isNaN(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const numeric = Number(value)
    return Number.isNaN(numeric) ? null : numeric
  }
  return null
}

// Serialize the menu-mode filter map into the URL payload. Each field is
// preserved with its `{ operator, constraints[...] }` so multi-constraint
// AND/OR rules round-trip across reloads. Empty constraints are stripped so
// shared links stay clean.
export function buildColumnFilterPayload(
  filters: DataTableFilterMeta,
): ColumnFilterPayload {
  const payload: ColumnFilterPayload = {}
  Object.keys(filters ?? {}).forEach((field) => {
    const filterMeta: any = (filters || {})[field]
    if (!filterMeta) return
    const constraints: ColumnFilterConstraint[] = Array.isArray(
      filterMeta.constraints,
    )
      ? filterMeta.constraints
      : [{ value: filterMeta.value, matchMode: filterMeta.matchMode }]
    const active = constraints
      .map((c) => ({ value: c?.value, matchMode: c?.matchMode }))
      .filter((c) => !isEmptyFilterValue(c.value))
    if (!active.length) return
    payload[field] = {
      operator:
        filterMeta.operator === FilterOperator.OR
          ? FilterOperator.OR
          : FilterOperator.AND,
      constraints: active,
    } as any
  })
  return payload
}

export function matchFilterValue(
  rowValue: any,
  filterValue: any,
  matchMode?: string,
): boolean {
  if (isEmptyFilterValue(filterValue)) return true
  if (!isValid(rowValue)) return false
  const mode = matchMode || DEFAULT_TEXT_MATCH_MODE

  if (mode === FilterMatchMode.IN) {
    if (!Array.isArray(filterValue)) return false
    return filterValue.some((item) =>
      matchFilterValue(rowValue, item, FilterMatchMode.EQUALS),
    )
  }

  const rowNumber = parseFilterNumber(rowValue)
  const filterNumber = parseFilterNumber(filterValue)
  const numericModes = new Set<string>([
    FilterMatchMode.EQUALS,
    FilterMatchMode.NOT_EQUALS,
    FilterMatchMode.LESS_THAN,
    FilterMatchMode.LESS_THAN_OR_EQUAL_TO,
    FilterMatchMode.GREATER_THAN,
    FilterMatchMode.GREATER_THAN_OR_EQUAL_TO,
  ])
  if (numericModes.has(mode) && rowNumber !== null && filterNumber !== null) {
    switch (mode) {
      case FilterMatchMode.EQUALS:
        return rowNumber === filterNumber
      case FilterMatchMode.NOT_EQUALS:
        return rowNumber !== filterNumber
      case FilterMatchMode.LESS_THAN:
        return rowNumber < filterNumber
      case FilterMatchMode.LESS_THAN_OR_EQUAL_TO:
        return rowNumber <= filterNumber
      case FilterMatchMode.GREATER_THAN:
        return rowNumber > filterNumber
      case FilterMatchMode.GREATER_THAN_OR_EQUAL_TO:
        return rowNumber >= filterNumber
      default:
        return false
    }
  }

  const rowString = String(rowValue).toLowerCase()
  const filterString = String(filterValue).toLowerCase()

  switch (mode) {
    case FilterMatchMode.STARTS_WITH:
      return rowString.startsWith(filterString)
    case FilterMatchMode.CONTAINS:
      return rowString.includes(filterString)
    case FilterMatchMode.NOT_CONTAINS:
      return !rowString.includes(filterString)
    case FilterMatchMode.ENDS_WITH:
      return rowString.endsWith(filterString)
    case FilterMatchMode.EQUALS:
      return rowString === filterString
    case FilterMatchMode.NOT_EQUALS:
      return rowString !== filterString
    default:
      return rowString.includes(filterString)
  }
}

export function matchFilterMeta(rowValue: any, filterMeta: any): boolean {
  if (!filterMeta) return true
  const constraints: ColumnFilterConstraint[] = Array.isArray(
    filterMeta.constraints,
  )
    ? filterMeta.constraints
    : [
        {
          value: filterMeta.value,
          matchMode: filterMeta.matchMode,
        },
      ]
  const activeConstraints = constraints.filter(
    (constraint) => !isEmptyFilterValue(constraint?.value),
  )
  if (!activeConstraints.length) return true
  const operator = filterMeta.operator || FilterOperator.AND
  const useOr = operator === FilterOperator.OR
  return useOr
    ? activeConstraints.some((constraint) =>
        matchFilterValue(rowValue, constraint.value, constraint.matchMode),
      )
    : activeConstraints.every((constraint) =>
        matchFilterValue(rowValue, constraint.value, constraint.matchMode),
      )
}

export function hasActiveConstraints(filterMeta: any): boolean {
  if (!filterMeta) return false
  const constraints: ColumnFilterConstraint[] = Array.isArray(
    filterMeta.constraints,
  )
    ? filterMeta.constraints
    : [
        {
          value: filterMeta.value,
          matchMode: filterMeta.matchMode,
        },
      ]
  return constraints.some(
    (constraint) => !isEmptyFilterValue(constraint?.value),
  )
}

function formatFilterValue(value: any): string {
  if (Array.isArray(value)) return value.map(String).join(', ')
  return String(value)
}

function formatMatchModeLabel(mode?: string): string {
  switch (mode) {
    case FilterMatchMode.STARTS_WITH:
      return 'starts with'
    case FilterMatchMode.CONTAINS:
      return 'contains'
    case FilterMatchMode.NOT_CONTAINS:
      return 'not contains'
    case FilterMatchMode.ENDS_WITH:
      return 'ends with'
    case FilterMatchMode.EQUALS:
      return 'equals'
    case FilterMatchMode.NOT_EQUALS:
      return 'not equals'
    case FilterMatchMode.LESS_THAN:
      return '<'
    case FilterMatchMode.LESS_THAN_OR_EQUAL_TO:
      return '<='
    case FilterMatchMode.GREATER_THAN:
      return '>'
    case FilterMatchMode.GREATER_THAN_OR_EQUAL_TO:
      return '>='
    case FilterMatchMode.IN:
      return 'in'
    default:
      return 'contains'
  }
}

export function getFilterDisplayLabel(filterMeta: any): string {
  if (!filterMeta) return ''
  const constraints: ColumnFilterConstraint[] = Array.isArray(
    filterMeta.constraints,
  )
    ? filterMeta.constraints
    : [
        {
          value: filterMeta.value,
          matchMode: filterMeta.matchMode,
        },
      ]
  const active = constraints.filter(
    (c) => !isEmptyFilterValue(c?.value),
  )
  if (!active.length) return ''
  const joiner = filterMeta.operator === FilterOperator.OR ? ' OR ' : ' AND '
  return active
    .map((c) => `${formatMatchModeLabel(c.matchMode)} "${formatFilterValue(c.value)}"`)
    .join(joiner)
}
