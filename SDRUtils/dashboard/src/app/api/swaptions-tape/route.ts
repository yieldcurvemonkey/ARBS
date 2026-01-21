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
const COLUMN_FILTER_EXPRESSIONS_V2: Record<string, string[]> = {
  action: ['plat.event_action'],
  package_type: ['d.package_type'],
  time: ['d.execution_start::text', 'd.execution_end::text'],
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
  time: ['d.execution_start::text', 'd.execution_end::text'],
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
  if (!value) return null

  const normalizedMode = normalizeTextMatchMode(matchMode)
  let op = 'ILIKE'
  let pattern = value

  switch (normalizedMode) {
    case 'startsWith':
      pattern = `${value}%`
      op = 'ILIKE'
      break
    case 'contains':
      pattern = `%${value}%`
      op = 'ILIKE'
      break
    case 'notContains':
      pattern = `%${value}%`
      op = 'NOT ILIKE'
      break
    case 'endsWith':
      pattern = `%${value}`
      op = 'ILIKE'
      break
    case 'equals':
      pattern = value
      op = 'ILIKE'
      break
    case 'notEquals':
      pattern = value
      op = 'NOT ILIKE'
      break
    default:
      pattern = `%${value}%`
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
