// ABOUTME: Pure-logic per-column filter helpers — power the inline row
// filter inputs (filterDisplay="row") in TradeTapeTable.
import { FilterMatchMode, FilterOperator } from 'primereact/api'
import type { DataTableFilterMeta } from 'primereact/datatable'

// Timestamp fields that the tape renders via formatExecutionWindow
// (NYC-localised "M/D/YYYY HH:MM:SS"). The filter must compare
// against the visible display string — comparing against the raw
// ISO timestamp ("2026-04-23T17:22:23.000Z") means a "contains
// 04/23" filter matches nothing, since the ISO format uses hyphens.
const TIMESTAMP_FILTER_FIELDS: ReadonlySet<string> = new Set([
  'execution_start',
  'execution_end',
  'original_execution_start',
  'clearing_accepted_start',
])

// NYC desk timezone — every tape timestamp is rendered against this
// regardless of the viewer's locale, so the filter has to match it.
const NYC_TZ = 'America/New_York'

/**
 * Format a timestamp the same way the Time-column body cell does, so a
 * `contains "04/23"` filter compares against the visible string the
 * trader is reading. Returns null when the value isn't a valid date.
 */
function formatTimestampForFilter(value: unknown): string | null {
  if (value === null || value === undefined) return null
  if (typeof value === 'string' && value.trim() === '') return null
  const d = value instanceof Date ? value : new Date(String(value))
  if (Number.isNaN(d.getTime())) return null
  const datePart = d.toLocaleDateString('en-US', { timeZone: NYC_TZ })
  const timePart = d.toLocaleTimeString('en-US', {
    timeZone: NYC_TZ,
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
  return `${datePart} ${timePart}`
}

/**
 * Strip leading zeros from numeric date parts (`04/23` → `4/23`,
 * `04/05/2026` → `4/5/2026`) so the trader's "04/23" filter matches
 * the cell's leading-zero-free `toLocaleDateString` output. Restricted
 * to the timestamp-filter path so plain text like `"007 Smith"` isn't
 * affected.
 */
function stripLeadingZerosOnDateParts(s: string): string {
  // Match `0N` where N is a digit, only when bordered by `/` or string
  // edges so we don't touch internal zeros (e.g. `2026` stays).
  return s.replace(/(^|\/|-)0(\d)/g, '$1$2')
}

function normalizeTimestampFilterMeta(filterMeta: any): any {
  if (!filterMeta) return filterMeta
  const normalizeConstraint = (c: ColumnFilterConstraint): ColumnFilterConstraint => {
    if (typeof c?.value === 'string') {
      return { ...c, value: stripLeadingZerosOnDateParts(c.value) }
    }
    return c
  }
  if (Array.isArray(filterMeta.constraints)) {
    return {
      ...filterMeta,
      constraints: filterMeta.constraints.map(normalizeConstraint),
    }
  }
  if (typeof filterMeta.value === 'string') {
    return {
      ...filterMeta,
      value: stripLeadingZerosOnDateParts(filterMeta.value),
    }
  }
  return filterMeta
}

export const DEFAULT_TEXT_MATCH_MODE = FilterMatchMode.CONTAINS
export const DEFAULT_NUMERIC_MATCH_MODE = FilterMatchMode.EQUALS

const NUMERIC_MATCH_MODES: ReadonlySet<string> = new Set([
  FilterMatchMode.EQUALS,
  FilterMatchMode.NOT_EQUALS,
  FilterMatchMode.LESS_THAN,
  FilterMatchMode.LESS_THAN_OR_EQUAL_TO,
  FilterMatchMode.GREATER_THAN,
  FilterMatchMode.GREATER_THAN_OR_EQUAL_TO,
])

const DATE_MATCH_MODES: ReadonlySet<string> = new Set(['dateAfter', 'dateBefore'])

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

/**
 * Parse a display-formatted date "M/D/YYYY" or "M/D/YYYY HH:MM:SS" into a
 * Date object (midnight UTC on that calendar day). Returns null if unparseable.
 */
function parseDateFromDisplay(s: string): Date | null {
  if (!s) return null
  // Extract just the date portion (before the space if time is present)
  const datePart = s.split(' ')[0]
  const parts = datePart.split('/')
  if (parts.length < 3) return null
  const month = parseInt(parts[0], 10)
  const day = parseInt(parts[1], 10)
  const year = parseInt(parts[2], 10)
  if (!Number.isFinite(month) || !Number.isFinite(day) || !Number.isFinite(year)) return null
  if (month < 1 || month > 12 || day < 1 || day > 31) return null
  // Use UTC to avoid timezone confusion — all comparisons are date-level
  return new Date(Date.UTC(year, month - 1, day))
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
  if (NUMERIC_MATCH_MODES.has(mode) && rowNumber !== null && filterNumber !== null) {
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

  // Date comparison modes — parse both sides as dates, compare chronologically.
  // The filter value comes in as "M/D/YYYY" or "MM/DD/YYYY" (the display format).
  // The row value for timestamp fields arrives pre-formatted as "M/D/YYYY HH:MM:SS".
  if (DATE_MATCH_MODES.has(mode)) {
    const rowDate = parseDateFromDisplay(String(rowValue))
    const filterDate = parseDateFromDisplay(String(filterValue))
    if (rowDate === null || filterDate === null) return false
    if (mode === 'dateAfter') return rowDate.getTime() >= filterDate.getTime()
    if (mode === 'dateBefore') return rowDate.getTime() <= filterDate.getTime()
    return false
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

/**
 * Collect every plausible value to test a filter against for a given row +
 * field. Most package-level fields (tape_label, total_risk, weighted_fixed_rate,
 * package_type) live directly on the row, so the candidate list is just
 * `[row[field]]`. A handful of columns the dashboard renders from leg-only
 * data — Platform (`platform_identifier`), Action (`lifecycle_type`),
 * per-leg PTS / PTP — are null at the package level; previously the filter
 * loop saw `undefined` and rejected every row regardless of the user's
 * input. Walking `legs_json` so any leg can satisfy the constraint mirrors
 * the body cell's `displayPlatform` fallback and matches trader intent
 * ("show packages with at least one leg matching X").
 */
export function collectFilterCandidates(
  row: Record<string, unknown> & { legs_json?: Array<Record<string, unknown>> },
  field: string,
): unknown[] {
  const isTimestampField = TIMESTAMP_FILTER_FIELDS.has(field)
  const root = row?.[field]
  if (!isEmptyFilterValue(root)) {
    // Timestamp fields render as "M/D/YYYY HH:MM:SS" in NYC tz; the
    // filter has to compare against that display string, not the raw
    // ISO. Format here so every match path sees the visible text.
    if (isTimestampField) {
      const formatted = formatTimestampForFilter(root)
      return formatted !== null ? [formatted] : [root]
    }
    return [root]
  }
  const legs = Array.isArray(row?.legs_json) ? row.legs_json : []
  const legValues = legs
    .map((leg) => (leg ? leg[field] : undefined))
    .filter((value) => !isEmptyFilterValue(value))
  // Fall back to the (nullish) root so the constraint still gets evaluated
  // — matchFilterMeta treats nullish + a non-empty filter value as a miss,
  // which is what we want when neither the row nor any leg carries data.
  if (legValues.length > 0) {
    if (isTimestampField) {
      return legValues
        .map((v) => formatTimestampForFilter(v))
        .filter((v): v is string => v !== null)
    }
    return legValues
  }
  return [root]
}

export function matchFilterMetaWithRow(
  row: Record<string, unknown> & { legs_json?: Array<Record<string, unknown>> },
  field: string,
  filterMeta: any,
): boolean {
  if (!filterMeta) return true
  const candidates = collectFilterCandidates(row, field)
  // Timestamp filters need leading-zero-tolerance on the trader's
  // input so "04/23" matches the cell's "4/23/2026" display.
  const effectiveMeta = TIMESTAMP_FILTER_FIELDS.has(field)
    ? normalizeTimestampFilterMeta(filterMeta)
    : filterMeta
  return candidates.some((value) => matchFilterMeta(value, effectiveMeta))
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
    case 'dateAfter':
      return 'after'
    case 'dateBefore':
      return 'before'
    default:
      return 'contains'
  }
}

// OPA sign-confidence filter definition — surfaced in the filter overlay
// and consumed by the SQL pushdown allowlist in route.logic.ts.
export const OPA_CONFIDENCE_FILTER = {
  id: 'opa_sign_confidence',
  label: 'OPA Confidence',
  options: ['EXACT', 'TIGHT', 'LOOSE', 'UNRESOLVED'] as const,
  type: 'multiSelect' as const,
} as const

export type OpaConfidence = typeof OPA_CONFIDENCE_FILTER.options[number]

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
