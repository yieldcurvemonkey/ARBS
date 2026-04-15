// ABOUTME: Pure client-side pipeline for fuzzy search, column filters, and sort.
// layered on top of the server-fetched rows. Mirrors the swaption tape's
// "operate on displayed values" behavior.
import { FilterMatchMode, FilterOperator } from 'primereact/api'
import type { DataTableFilterMeta } from 'primereact/datatable'
import { LIFECYCLE_LABELS } from '../../constants'
import type { LifecycleType, UsdSwapTapeRow } from '../../types'
import { fuzzyBestScore } from '../../utils/fuzzy'
import {
  formatDv01,
  formatExecutionWindow,
  formatNotional,
  formatRate,
} from '../../utils/format'
import { lifecyclePillsFor } from './RowBadges.helpers'
import { displayTapeLabel } from './TapeLabelCell.helpers'

type FilterConstraintLike = {
  value?: unknown
  matchMode?: string
}

type FilterMetaLike = {
  operator?: string
  constraints?: FilterConstraintLike[]
  value?: unknown
  matchMode?: string
}

const ACTION_FALLBACKS: Array<{
  type: LifecycleType
  active: (row: UsdSwapTapeRow) => boolean
}> = [
  { type: 'CLEARING_TERM', active: (row) => Boolean(row.is_clearing_termination_any) },
  { type: 'UNWIND', active: (row) => Boolean(row.is_unwind) },
  { type: 'TERMINATION', active: (row) => Boolean(row.is_termination_any) },
  { type: 'COMPRESSION', active: (row) => Boolean(row.is_compression_any) },
  { type: 'RESET_OPT', active: (row) => Boolean(row.is_reset_optimization_any) },
  { type: 'NOVATION', active: (row) => Boolean(row.is_novation_any) },
  { type: 'CORRECTION', active: (row) => Boolean(row.is_correction_any) },
  { type: 'EXERCISE_BORN', active: (row) => Boolean((row.lifecycle_mix ?? {}).EXERCISE_BORN) },
  { type: 'NEW_RISK', active: (row) => Boolean(row.is_new_risk) },
]

function firstLeg(row: UsdSwapTapeRow) {
  return row.legs_json?.[0]
}

function isEmptyValue(value: unknown): boolean {
  return (
    value === null ||
    value === undefined ||
    value === '' ||
    (Array.isArray(value) && value.length === 0)
  )
}

function parseNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value !== 'string' || value.trim() === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function parseTimestamp(value: unknown): number | null {
  if (value instanceof Date) {
    const ms = value.getTime()
    return Number.isNaN(ms) ? null : ms
  }
  if (typeof value !== 'string' || value.trim() === '') return null
  const ms = Date.parse(value)
  return Number.isNaN(ms) ? null : ms
}

function normalizeConstraints(meta: FilterMetaLike | undefined): FilterConstraintLike[] {
  if (!meta) return []
  const constraints = Array.isArray(meta.constraints)
    ? meta.constraints
    : [{ value: meta.value, matchMode: meta.matchMode }]
  return constraints.filter((constraint) => !isEmptyValue(constraint?.value))
}

function resolveActionText(row: UsdSwapTapeRow): string {
  const pills = lifecyclePillsFor(row)
  if (pills.length) {
    return pills.map((pill) => `${pill.label} ${pill.type}`).join(' ')
  }

  const fallback = ACTION_FALLBACKS.filter(({ active }) => active(row)).map(
    ({ type }) => `${LIFECYCLE_LABELS[type]} ${type}`,
  )
  if (fallback.length) return fallback.join(' ')

  return String(row.event_action ?? firstLeg(row)?.event_action ?? '')
}

function resolvePlatformText(row: UsdSwapTapeRow): string {
  return String(row.platform_identifier ?? firstLeg(row)?.platform_identifier ?? '')
}

function resolveFilterValue(row: UsdSwapTapeRow, field: string): unknown {
  switch (field) {
    case 'time':
    case 'execution_start':
    case 'execution_end':
      return formatExecutionWindow(row.execution_start, row.execution_end)
    case 'action':
    case 'action_label':
    case 'lifecycle':
      return resolveActionText(row)
    case 'platform':
    case 'platform_identifier':
      return resolvePlatformText(row)
    case 'label':
    case 'tape_label':
      return displayTapeLabel(row)
    case 'dv01':
    case 'total_risk':
      return row.total_risk ?? null
    case 'notional':
    case 'total_notional':
      return row.total_notional ?? null
    case 'rate':
    case 'weighted_fixed_rate':
      return row.weighted_fixed_rate ?? null
    default:
      return (row as Record<string, unknown>)[field]
  }
}

function resolveSortValue(row: UsdSwapTapeRow, field: string): unknown {
  switch (field) {
    case 'action':
    case 'action_label':
    case 'lifecycle':
      return resolveActionText(row)
    case 'platform':
    case 'platform_identifier':
      return resolvePlatformText(row)
    case 'label':
    case 'tape_label':
      return displayTapeLabel(row)
    case 'dv01':
    case 'total_risk':
      return row.total_risk ?? null
    case 'notional':
    case 'total_notional':
      return row.total_notional ?? null
    case 'rate':
    case 'weighted_fixed_rate':
      return row.weighted_fixed_rate ?? null
    case 'time':
      return row.execution_start
    default:
      return (row as Record<string, unknown>)[field]
  }
}

const FUZZY_FIELDS: Array<(row: UsdSwapTapeRow) => string | null | undefined> = [
  (row) => displayTapeLabel(row),
  (row) => resolvePlatformText(row),
  (row) => resolveActionText(row),
  (row) => String(row.trade_type ?? row.package_type ?? ''),
  (row) => row.package_id,
  (row) => formatExecutionWindow(row.execution_start, row.execution_end),
  (row) => formatDv01(row.total_risk ?? null, { signed: true }),
  (row) => formatNotional(row.total_notional ?? null, { compact: true }),
  (row) => formatRate(row.weighted_fixed_rate ?? null),
  (row) =>
    (row.legs_json ?? [])
      .map((leg) => leg.tape_label ?? leg.trade_label ?? leg.tenor_label ?? '')
      .filter(Boolean)
      .join(' '),
]

export function applyFuzzy(rows: UsdSwapTapeRow[], query: string): UsdSwapTapeRow[] {
  const q = (query ?? '').trim()
  if (!q) return rows
  return rows.filter((row) => {
    const fields = FUZZY_FIELDS.map((resolver) => resolver(row))
    return fuzzyBestScore(q, fields) >= 0
  })
}

function matchOne(value: unknown, matchValue: unknown, mode: string): boolean {
  if (isEmptyValue(matchValue)) return true
  if (value === null || value === undefined) return false

  if (mode === FilterMatchMode.IN) {
    if (!Array.isArray(matchValue)) return false
    return matchValue.some((candidate) =>
      matchOne(value, candidate, FilterMatchMode.EQUALS),
    )
  }

  const rowTime = parseTimestamp(value)
  const filterTime = parseTimestamp(matchValue)
  const rowNumber = parseNumber(value)
  const filterNumber = parseNumber(matchValue)

  const compare = (left: number, right: number): boolean => {
    switch (mode) {
      case FilterMatchMode.EQUALS:
        return left === right
      case FilterMatchMode.NOT_EQUALS:
        return left !== right
      case FilterMatchMode.GREATER_THAN:
        return left > right
      case FilterMatchMode.GREATER_THAN_OR_EQUAL_TO:
        return left >= right
      case FilterMatchMode.LESS_THAN:
        return left < right
      case FilterMatchMode.LESS_THAN_OR_EQUAL_TO:
        return left <= right
      default:
        return false
    }
  }

  if (rowTime !== null && filterTime !== null) {
    return compare(rowTime, filterTime)
  }
  if (rowNumber !== null && filterNumber !== null) {
    return compare(rowNumber, filterNumber)
  }

  const valueText = String(value).toLowerCase()
  const matchText = String(matchValue).toLowerCase()
  switch (mode) {
    case FilterMatchMode.EQUALS:
      return valueText === matchText
    case FilterMatchMode.NOT_EQUALS:
      return valueText !== matchText
    case FilterMatchMode.STARTS_WITH:
      return valueText.startsWith(matchText)
    case FilterMatchMode.ENDS_WITH:
      return valueText.endsWith(matchText)
    case FilterMatchMode.CONTAINS:
    default:
      return valueText.includes(matchText)
  }
}

function matchFieldMeta(
  row: UsdSwapTapeRow,
  field: string,
  meta: FilterMetaLike,
): boolean {
  const constraints = normalizeConstraints(meta)
  if (!constraints.length) return true
  const fieldOperator =
    meta.operator === FilterOperator.OR ? FilterOperator.OR : FilterOperator.AND
  const rowValue = resolveFilterValue(row, field)
  const matches = constraints.map((constraint) =>
    matchOne(
      rowValue,
      constraint.value,
      constraint.matchMode ?? FilterMatchMode.CONTAINS,
    ),
  )
  return fieldOperator === FilterOperator.OR
    ? matches.some(Boolean)
    : matches.every(Boolean)
}

export function applyColumnFilters(
  rows: UsdSwapTapeRow[],
  filters: DataTableFilterMeta | Record<string, any>,
  operator: 'and' | 'or' = 'and',
): UsdSwapTapeRow[] {
  const entries = Object.entries(filters ?? {}).filter(([field, meta]) => {
    if (field === 'global' || !meta) return false
    return normalizeConstraints(meta as FilterMetaLike).length > 0
  })
  if (!entries.length) return rows

  return rows.filter((row) => {
    const matches = entries.map(([field, meta]) =>
      matchFieldMeta(row, field, meta as FilterMetaLike),
    )
    return operator === 'or' ? matches.some(Boolean) : matches.every(Boolean)
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
    const av = resolveSortValue(a, sortField)
    const bv = resolveSortValue(b, sortField)
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
