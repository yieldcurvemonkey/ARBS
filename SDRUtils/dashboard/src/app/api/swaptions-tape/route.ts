// ABOUTME: Reads from arbs_swaption_master_tape_v2 with cursor pagination and fuzzy filtering for the Trade Tape.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { resolveDisplayView, TapeRow } from '@/lib/swaptions-tape'

const DEFAULT_LIMIT = 200
const MAX_LIMIT = 500
const COLUMN_FILTER_QUERY_KEY = 'columnFilters'
const COLUMN_FILTER_OPERATOR_QUERY_KEY = 'columnFilterOp'
const COLUMN_FILTER_FIELDS = [
  'action',
  'package_type',
  'time',
  'platform',
  'notional',
  'label'
] as const

function buildTimeSearchExpressions(column: string): string[] {
  return [
    `${column}::text`,
    `to_char(${column} AT TIME ZONE 'UTC', 'MM/DD')`,
    `to_char(${column} AT TIME ZONE 'UTC', 'FMMM/FMDD')`,
    `to_char(${column} AT TIME ZONE 'UTC', 'FMMM-FMDD')`,
    `to_char(${column} AT TIME ZONE 'UTC', 'FMMM.FMDD')`,
    `to_char(${column} AT TIME ZONE 'UTC', 'FMMon FMDD')`,
    `to_char(${column} AT TIME ZONE 'UTC', 'FMMonth FMDD')`,
    `to_char(${column} AT TIME ZONE 'UTC', 'FMDD FMMon')`,
    `to_char(${column} AT TIME ZONE 'UTC', 'YYYY-MM-DD')`,
    `to_char(${column} AT TIME ZONE 'America/New_York', 'MM/DD')`,
    `to_char(${column} AT TIME ZONE 'America/New_York', 'FMMM/FMDD')`,
    `to_char(${column} AT TIME ZONE 'America/New_York', 'FMMM-FMDD')`,
    `to_char(${column} AT TIME ZONE 'America/New_York', 'FMMM.FMDD')`,
    `to_char(${column} AT TIME ZONE 'America/New_York', 'FMMon FMDD')`,
    `to_char(${column} AT TIME ZONE 'America/New_York', 'FMMonth FMDD')`,
    `to_char(${column} AT TIME ZONE 'America/New_York', 'FMDD FMMon')`,
    `to_char(${column} AT TIME ZONE 'America/New_York', 'YYYY-MM-DD')`
  ]
}

const TIME_FILTER_EXPRESSIONS = [
  ...buildTimeSearchExpressions('d.execution_start'),
  ...buildTimeSearchExpressions('d.execution_end')
]

const COLUMN_FILTER_EXPRESSIONS_V2: Record<string, string[]> = {
  action: ['plat.event_action'],
  package_type: ['d.package_type'],
  time: TIME_FILTER_EXPRESSIONS,
  platform: [
    "COALESCE(plat.platform_identifier, d.package_metrics->>'platform_identifier')"
  ],
  notional: ['d.total_notional'],
  label: [
    'd.package_id',
    'd.manual_package_id',
    'd.tenor_label',
    'd.forward_label',
    'd.package_type',
    'd.user_comment',
    'd.link_reason',
    'd.tags::text',
    'd.legs_json::text'
  ]
}
const COLUMN_FILTER_EXPRESSIONS_V1: Record<string, string[]> = {
  action: ['plat.event_action'],
  package_type: ['d.package_type'],
  time: TIME_FILTER_EXPRESSIONS,
  platform: [
    "COALESCE(plat.platform_identifier, d.package_metrics->>'platform_identifier')"
  ],
  notional: ['d.total_notional'],
  label: [
    'd.package_id',
    'd.tenor_label',
    'd.forward_label',
    'd.package_type',
    'd.legs_json::text'
  ]
}

type FilterConstraint = {
  value?: unknown
  matchMode?: string
}

type ColumnFilterMeta = {
  operator?: string
  constraints?: FilterConstraint[]
  value?: unknown
  matchMode?: string
}

type ColumnFilterPayload = Record<string, ColumnFilterMeta>

function parseLimit(raw: string | null): number {
  const parsed = Number(raw ?? DEFAULT_LIMIT)
  if (Number.isNaN(parsed) || parsed < 1) return DEFAULT_LIMIT
  return Math.min(parsed, MAX_LIMIT)
}

function normalizeFilterOperator(value: string | null | undefined) {
  return value?.toLowerCase() === 'or' ? 'or' : 'and'
}

function isEmptyFilterValue(value: unknown) {
  if (value === null || value === undefined) return true
  if (typeof value === 'string' && value.trim() === '') return true
  if (Array.isArray(value) && value.length === 0) return true
  return false
}

function parseColumnFilters(rawValue: string | null): ColumnFilterPayload {
  if (!rawValue) return {}
  try {
    const parsed = JSON.parse(rawValue) as ColumnFilterPayload
    if (!parsed || typeof parsed !== 'object') return {}
    return parsed
  } catch {
    return {}
  }
}

function normalizeTextMatchMode(matchMode?: string) {
  switch (matchMode) {
    case 'startsWith':
    case 'contains':
    case 'notContains':
    case 'endsWith':
    case 'equals':
    case 'notEquals':
    case 'in':
      return matchMode
    case 'lt':
    case 'lte':
    case 'gt':
    case 'gte':
      return 'contains'
    default:
      return 'contains'
  }
}

const TEMPORAL_MATCH_MODES = new Set([
  'equals',
  'notEquals',
  'lt',
  'lte',
  'gt',
  'gte'
])
const ISO_TIMESTAMP_PATTERN =
  /\b\d{4}-\d{2}-\d{2}t\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:z|[+-]\d{2}:?\d{2})?\b/i
const ISO_LOCAL_TIMESTAMP_PATTERN =
  /\b(\d{4})-(\d{1,2})-(\d{1,2})(?:[ t](\d{1,2}):(\d{2})(?::(\d{2}))?)?\b/i
const US_LOCAL_TIMESTAMP_PATTERN =
  /\b(\d{1,2})\/(\d{1,2})\/(\d{2,4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?\b/

type ParsedTemporalFilterValue =
  | { kind: 'absolute'; value: string }
  | { kind: 'easternLocal'; value: string }
type ParsedTemporalDayRange =
  | { kind: 'absolute'; start: string; end: string }
  | { kind: 'easternLocal'; start: string; end: string }

function parseYear(rawYear: string): number {
  const parsed = Number(rawYear)
  if (!Number.isFinite(parsed)) return Number.NaN
  if (rawYear.length === 2) {
    return parsed >= 70 ? parsed + 1900 : parsed + 2000
  }
  return parsed
}

function toEasternLocalTimestamp(
  year: number,
  month: number,
  day: number,
  hour = 0,
  minute = 0,
  second = 0
): string | null {
  if (
    !Number.isInteger(year) ||
    !Number.isInteger(month) ||
    !Number.isInteger(day) ||
    !Number.isInteger(hour) ||
    !Number.isInteger(minute) ||
    !Number.isInteger(second)
  ) {
    return null
  }
  if (month < 1 || month > 12) return null
  if (day < 1 || day > 31) return null
  if (hour < 0 || hour > 23) return null
  if (minute < 0 || minute > 59) return null
  if (second < 0 || second > 59) return null

  // Validate date parts (reject rollover cases like 2/30).
  const probe = new Date(Date.UTC(year, month - 1, day, hour, minute, second))
  if (
    probe.getUTCFullYear() !== year ||
    probe.getUTCMonth() + 1 !== month ||
    probe.getUTCDate() !== day ||
    probe.getUTCHours() !== hour ||
    probe.getUTCMinutes() !== minute ||
    probe.getUTCSeconds() !== second
  ) {
    return null
  }

  const yyyy = String(year).padStart(4, '0')
  const mm = String(month).padStart(2, '0')
  const dd = String(day).padStart(2, '0')
  const hh = String(hour).padStart(2, '0')
  const mi = String(minute).padStart(2, '0')
  const ss = String(second).padStart(2, '0')
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss}`
}

function buildEasternLocalDayRange(
  year: number,
  month: number,
  day: number
): { start: string; end: string } | null {
  const start = toEasternLocalTimestamp(year, month, day, 0, 0, 0)
  if (!start) return null
  const nextDay = new Date(Date.UTC(year, month - 1, day))
  if (Number.isNaN(nextDay.getTime())) return null
  nextDay.setUTCDate(nextDay.getUTCDate() + 1)
  const end = toEasternLocalTimestamp(
    nextDay.getUTCFullYear(),
    nextDay.getUTCMonth() + 1,
    nextDay.getUTCDate(),
    0,
    0,
    0
  )
  if (!end) return null
  return { start, end }
}

function parseTemporalContainsDayRange(
  rawValue: unknown
): ParsedTemporalDayRange | null {
  if (rawValue === null || rawValue === undefined) return null
  const normalized = String(rawValue).replace(/\+/g, ' ').trim()
  if (!normalized) return null

  const usDateOnly = normalized.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/)
  if (usDateOnly) {
    const month = Number(usDateOnly[1])
    const day = Number(usDateOnly[2])
    const year = parseYear(usDateOnly[3])
    const range = buildEasternLocalDayRange(year, month, day)
    if (range) return { kind: 'easternLocal', ...range }
  }

  const isoDateOnly = normalized.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/)
  if (isoDateOnly) {
    const year = Number(isoDateOnly[1])
    const month = Number(isoDateOnly[2])
    const day = Number(isoDateOnly[3])
    const range = buildEasternLocalDayRange(year, month, day)
    if (range) return { kind: 'easternLocal', ...range }
  }

  return null
}

function parseTemporalFilterValue(
  rawValue: unknown
): ParsedTemporalFilterValue | null {
  if (rawValue === null || rawValue === undefined) return null
  const normalized = String(rawValue)
    .replace(/\+/g, ' ')
    .replace(/\s+/g, ' ')
  .trim()
  if (!normalized) return null

  // Absolute timestamps with explicit timezone (Z or +/-hh:mm).
  const isoMatch = normalized.match(ISO_TIMESTAMP_PATTERN)?.[0]
  if (isoMatch && /(?:z|[+-]\d{2}:?\d{2})$/i.test(isoMatch)) {
    const parsed = Date.parse(isoMatch)
    if (!Number.isNaN(parsed)) {
      return { kind: 'absolute', value: new Date(parsed).toISOString() }
    }
  }

  // Parse local timestamp inputs as America/New_York regardless of host timezone.
  const usMatch = normalized.match(US_LOCAL_TIMESTAMP_PATTERN)
  if (usMatch) {
    const month = Number(usMatch[1])
    const day = Number(usMatch[2])
    const year = parseYear(usMatch[3])
    const hour = usMatch[4] ? Number(usMatch[4]) : 0
    const minute = usMatch[5] ? Number(usMatch[5]) : 0
    const second = usMatch[6] ? Number(usMatch[6]) : 0
    const easternLocal = toEasternLocalTimestamp(
      year,
      month,
      day,
      hour,
      minute,
      second
    )
    if (easternLocal) return { kind: 'easternLocal', value: easternLocal }
  }

  const isoLocalMatch = normalized.match(ISO_LOCAL_TIMESTAMP_PATTERN)
  if (isoLocalMatch) {
    const year = Number(isoLocalMatch[1])
    const month = Number(isoLocalMatch[2])
    const day = Number(isoLocalMatch[3])
    const hour = isoLocalMatch[4] ? Number(isoLocalMatch[4]) : 0
    const minute = isoLocalMatch[5] ? Number(isoLocalMatch[5]) : 0
    const second = isoLocalMatch[6] ? Number(isoLocalMatch[6]) : 0
    const easternLocal = toEasternLocalTimestamp(
      year,
      month,
      day,
      hour,
      minute,
      second
    )
    if (easternLocal) return { kind: 'easternLocal', value: easternLocal }
  }

  // Last-resort parse for fully-qualified timestamp strings.
  const parsed = Date.parse(normalized)
  if (!Number.isNaN(parsed)) {
    return { kind: 'absolute', value: new Date(parsed).toISOString() }
  }

  return null
}

function buildTextCondition(
  expressions: string[],
  matchMode: string | undefined,
  rawValue: unknown,
  params: unknown[]
) {
  if (rawValue === null || rawValue === undefined) return null
  if (matchMode === 'in' && Array.isArray(rawValue)) {
    const values = rawValue
      .map((entry) => String(entry))
      .map((entry) => entry.trim())
      .filter(Boolean)
    if (!values.length) return null
    params.push(values)
    const placeholder = `$${params.length}`
    const clause = expressions
      .map((expr) => `${expr} ILIKE ANY(${placeholder})`)
      .join(' OR ')
    return expressions.length > 1 ? `(${clause})` : clause
  }

  const value = String(rawValue).trim()
  const normalizedInput = value.replace(/\+/g, ' ').replace(/\s+/g, ' ').trim()
  if (!normalizedInput) return null

  const normalizedMode = normalizeTextMatchMode(matchMode)
  let op = 'ILIKE'
  let pattern = normalizedInput

  switch (normalizedMode) {
    case 'startsWith':
      pattern = `${normalizedInput}%`
      op = 'ILIKE'
      break
    case 'contains':
      pattern = `%${normalizedInput}%`
      op = 'ILIKE'
      break
    case 'notContains':
      pattern = `%${normalizedInput}%`
      op = 'NOT ILIKE'
      break
    case 'endsWith':
      pattern = `%${normalizedInput}`
      op = 'ILIKE'
      break
    case 'equals':
      pattern = normalizedInput
      op = 'ILIKE'
      break
    case 'notEquals':
      pattern = normalizedInput
      op = 'NOT ILIKE'
      break
    default:
      pattern = `%${normalizedInput}%`
      op = 'ILIKE'
      break
  }

  params.push(pattern)
  const placeholder = `$${params.length}`
  const joiner = op.startsWith('NOT') ? ' AND ' : ' OR '
  const clause = expressions
    .map((expr) => `${expr} ${op} ${placeholder}`)
    .join(joiner)
  return expressions.length > 1 ? `(${clause})` : clause
}

function buildNumericCondition(
  expression: string,
  matchMode: string | undefined,
  rawValue: unknown,
  params: unknown[]
) {
  if (rawValue === null || rawValue === undefined) return null
  if (matchMode === 'in' && Array.isArray(rawValue)) {
    const values = rawValue
      .map((entry) => Number(entry))
      .filter((entry) => !Number.isNaN(entry))
    if (!values.length) return null
    params.push(values)
    const placeholder = `$${params.length}`
    return `${expression} = ANY(${placeholder})`
  }

  const numericValue = Number(rawValue)
  if (Number.isNaN(numericValue)) {
    return buildTextCondition(
      [`${expression}::text`],
      matchMode,
      rawValue,
      params
    )
  }

  const normalizedMode = matchMode || 'equals'
  if (
    !['equals', 'notEquals', 'lt', 'lte', 'gt', 'gte'].includes(normalizedMode)
  ) {
    return buildTextCondition(
      [`${expression}::text`],
      matchMode,
      rawValue,
      params
    )
  }

  let op = '='
  switch (normalizedMode) {
    case 'notEquals':
      op = '<>'
      break
    case 'lt':
      op = '<'
      break
    case 'lte':
      op = '<='
      break
    case 'gt':
      op = '>'
      break
    case 'gte':
      op = '>='
      break
    default:
      op = '='
  }

  params.push(numericValue)
  return `${expression} ${op} $${params.length}`
}

function buildTimeCondition(
  expressions: string[],
  matchMode: string | undefined,
  rawValue: unknown,
  params: unknown[]
) {
  const normalizedMode = matchMode || 'contains'
  if (normalizedMode === 'contains') {
    const dayRange = parseTemporalContainsDayRange(rawValue)
    if (dayRange) {
      params.push(dayRange.start)
      const startPlaceholder = `$${params.length}`
      params.push(dayRange.end)
      const endPlaceholder = `$${params.length}`
      const startExpr =
        dayRange.kind === 'easternLocal'
          ? `(${startPlaceholder}::timestamp AT TIME ZONE 'America/New_York')`
          : `${startPlaceholder}::timestamptz`
      const endExpr =
        dayRange.kind === 'easternLocal'
          ? `(${endPlaceholder}::timestamp AT TIME ZONE 'America/New_York')`
          : `${endPlaceholder}::timestamptz`
      return `(d.execution_start >= ${startExpr} AND d.execution_start < ${endExpr})`
    }
  }

  if (TEMPORAL_MATCH_MODES.has(normalizedMode)) {
    const parsedTimestamp = parseTemporalFilterValue(rawValue)
    if (parsedTimestamp) {
      let op = '='
      switch (normalizedMode) {
        case 'notEquals':
          op = '<>'
          break
        case 'lt':
          op = '<'
          break
        case 'lte':
          op = '<='
          break
        case 'gt':
          op = '>'
          break
        case 'gte':
          op = '>='
          break
        default:
          op = '='
      }
      params.push(parsedTimestamp.value)
      const placeholder = `$${params.length}`
      const rhs =
        parsedTimestamp.kind === 'easternLocal'
          ? `(${placeholder}::timestamp AT TIME ZONE 'America/New_York')`
          : `${placeholder}::timestamptz`
      return `d.execution_start ${op} ${rhs}`
    }
  }

  return buildTextCondition(expressions, matchMode, rawValue, params)
}

function buildColumnFilterClause(
  field: string,
  constraint: FilterConstraint,
  params: unknown[],
  expressionsMap: Record<string, string[]>
) {
  const expressions = expressionsMap[field]
  if (!expressions) return null
  if (field === 'notional') {
    return buildNumericCondition(
      expressions[0],
      constraint.matchMode,
      constraint.value,
      params
    )
  }
  if (field === 'time') {
    return buildTimeCondition(
      expressions,
      constraint.matchMode,
      constraint.value,
      params
    )
  }
  return buildTextCondition(
    expressions,
    constraint.matchMode,
    constraint.value,
    params
  )
}

function buildColumnFiltersClause(
  columnFilters: ColumnFilterPayload,
  columnFilterOperator: string,
  params: unknown[],
  expressionsMap: Record<string, string[]>
) {
  const fieldClauses: string[] = []
  COLUMN_FILTER_FIELDS.forEach((field) => {
    const filterMeta = columnFilters[field]
    if (!filterMeta) return
    const constraints = Array.isArray(filterMeta.constraints)
      ? filterMeta.constraints
      : [
          {
            value: filterMeta.value,
            matchMode: filterMeta.matchMode
          }
        ]
    const activeConstraints = constraints.filter(
      (constraint) => !isEmptyFilterValue(constraint?.value)
    )
    if (!activeConstraints.length) return

    const operator = normalizeFilterOperator(filterMeta.operator)
    const constraintClauses = activeConstraints
      .map((constraint) =>
        buildColumnFilterClause(field, constraint, params, expressionsMap)
      )
      .filter(Boolean) as string[]
    if (!constraintClauses.length) return

    const joiner = operator === 'or' ? ' OR ' : ' AND '
    const fieldClause =
      constraintClauses.length > 1
        ? `(${constraintClauses.join(joiner)})`
        : constraintClauses[0]
    fieldClauses.push(fieldClause)
  })

  if (!fieldClauses.length) return null
  const joiner = columnFilterOperator === 'or' ? ' OR ' : ' AND '
  return fieldClauses.length > 1
    ? `(${fieldClauses.join(joiner)})`
    : fieldClauses[0]
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const cursor = searchParams.get('cursor')
  const since = searchParams.get('since')
  const filter = (searchParams.get('filter') || '').trim()
  const columnFilters = parseColumnFilters(
    searchParams.get(COLUMN_FILTER_QUERY_KEY)
  )
  const columnFilterOperator = normalizeFilterOperator(
    searchParams.get(COLUMN_FILTER_OPERATOR_QUERY_KEY)
  )
  const limit = parseLimit(searchParams.get('limit'))
  const { view, columns, hasManualFields } = await resolveDisplayView()
  const columnFilterExpressions = hasManualFields
    ? COLUMN_FILTER_EXPRESSIONS_V2
    : COLUMN_FILTER_EXPRESSIONS_V1

  if (cursor && since) {
    return NextResponse.json(
      { error: 'Use either cursor or since, not both' },
      { status: 400 }
    )
  }

  const conditions: string[] = []
  const params: unknown[] = []

  if (cursor) {
    params.push(cursor)
    conditions.push(`execution_start < $${params.length}`)
  }

  if (since) {
    params.push(since)
    conditions.push(`execution_start > $${params.length}`)
  }

  if (filter) {
    params.push(`%${filter}%`)
    const idx = params.length
    const filterClauses = [
      `package_id ILIKE $${idx}`,
      `tenor_label ILIKE $${idx}`,
      `forward_label ILIKE $${idx}`,
      `package_type ILIKE $${idx}`
    ]
    if (hasManualFields) {
      filterClauses.push(`manual_package_id ILIKE $${idx}`)
    }
    conditions.push(`(${filterClauses.join(' OR ')})`)
  }

  const columnFilterClause = buildColumnFiltersClause(
    columnFilters,
    columnFilterOperator,
    params,
    columnFilterExpressions
  )
  if (columnFilterClause) {
    conditions.push(columnFilterClause)
  }

  // Hide sparse outright artifacts (typically MODI duplicates) that have
  // no usable leg metadata and only pollute the tape.
  conditions.push(
    `NOT (
      d.package_type = 'OUTRIGHT'
      AND COALESCE(plat.event_action, '') = ''
      AND COALESCE(plat.product_type, '') = ''
      AND COALESCE(plat.trade_label, '') = ''
    )`
  )

  const limitParamIndex = params.length + 1
  params.push(limit + 1) // Fetch one extra row to compute hasMore
  const whereClause = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''

  try {
    const result = await query(
      `SELECT ${columns}
       FROM ${view} d
       LEFT JOIN LATERAL (
         SELECT mode() WITHIN GROUP (ORDER BY platform_identifier) AS platform_identifier
               , mode() WITHIN GROUP (ORDER BY event_action) AS event_action
               , mode() WITHIN GROUP (ORDER BY product_type) AS product_type
               , mode() WITHIN GROUP (ORDER BY trade_label) AS trade_label
         FROM arbs_swaption_legs_v1 l
         WHERE l.package_id = d.package_id
       ) plat ON TRUE
       ${whereClause}
       ORDER BY d.execution_start DESC
       LIMIT $${limitParamIndex}`,
      params
    )

    let rows = result.rows as TapeRow[]
    let hasMore = false

    if (rows.length > limit) {
      hasMore = true
      rows = rows.slice(0, limit)
    }

    const nextCursor = hasMore && rows.length > 0 
      ? rows[rows.length - 1].execution_start 
      : null

    const latestExecutionStart = rows.length > 0 
      ? rows[0].execution_start 
      : since || null

    return NextResponse.json({
      rows,
      hasMore,
      nextCursor,
      latestExecutionStart
    })
  } catch (error: any) {
    console.error('swaptions-tape GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch swaptions tape' },
      { status: 500 }
    )
  }
}
