// ABOUTME: Pure helpers for the tape v2 main route — parse filters, build WHERE clauses.
// No DB access here; unit-testable in isolation.
import { TAPE_DISPLAY } from '@/lib/tape-tables'

// Re-exported for existing importers. The generation itself now lives in
// src/lib/tape-tables.ts, which is deliberately a constant rather than an
// env var — see that file for why, and for the v1-rollback story (design §4.11).
export const TAPE_DISPLAY_VIEW = TAPE_DISPLAY

export const DEFAULT_LIMIT = 200
export const MAX_LIMIT = 500

export type WhereFragment = { sql: string; params: unknown[] }

export type ParsedParams = {
  cursor: string | null
  since: string | null
  limit: number
  filter: string | null
  clean: boolean
  lifecycle: string[]
  tradeTypes: string[]
  venues: string[]
  ccps: string[]
  sessions: string[]
  rateIndex: string[]
  tenors: string[]
  fomcMeeting: string | null
  columnFilters: Record<string, any>
  columnFilterOp: 'and' | 'or'
}

export type ParseResult =
  | { ok: true; value: ParsedParams }
  | { ok: false; error: string; status?: number }

const LIFECYCLE_VALUES = new Set([
  'new_risk',
  'unwind',
  'compression',
  'termination',
  'novation',
  'reset_opt',
  'correction',
  'clearing_term',
  'exercise_born',
  'other',
])

const VENUE_VALUES = new Set(['D2D', 'D2C'])
const CCP_VALUES = new Set(['LCH', 'CME'])
const SESSION_VALUES = new Set(['Asia', 'London', 'NY_AM', 'NY_PM', 'Late'])
const RATE_INDEX_VALUES = new Set(['SOFR', 'FED_FUNDS', 'BASIS', 'OTHER'])

function parseLimit(raw: string | null): number {
  const n = Number(raw ?? DEFAULT_LIMIT)
  if (!Number.isFinite(n) || n < 1) return DEFAULT_LIMIT
  return Math.min(Math.floor(n), MAX_LIMIT)
}

function parseCsv(raw: string | null): string[] {
  if (!raw) return []
  return raw
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

function parseColumnFilters(raw: string | null): Record<string, any> {
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return {}
    return parsed as Record<string, any>
  } catch {
    return {}
  }
}

export function parseParams(searchParams: URLSearchParams): ParseResult {
  const cursor = searchParams.get('cursor')
  const since = searchParams.get('since')
  if (cursor && since) {
    return { ok: false, error: 'cursor and since are mutually exclusive', status: 400 }
  }
  const lifecycle = parseCsv(searchParams.get('lifecycle'))
  for (const lc of lifecycle) {
    if (!LIFECYCLE_VALUES.has(lc.toLowerCase())) {
      return { ok: false, error: `invalid lifecycle value: ${lc}`, status: 400 }
    }
  }
  const venues = parseCsv(searchParams.get('venues'))
  for (const v of venues) {
    if (!VENUE_VALUES.has(v)) {
      return { ok: false, error: `invalid venue: ${v}`, status: 400 }
    }
  }
  const ccps = parseCsv(searchParams.get('ccps'))
  for (const c of ccps) {
    if (!CCP_VALUES.has(c)) {
      return { ok: false, error: `invalid ccp: ${c}`, status: 400 }
    }
  }
  const sessions = parseCsv(searchParams.get('sessions'))
  for (const s of sessions) {
    if (!SESSION_VALUES.has(s)) {
      return { ok: false, error: `invalid session: ${s}`, status: 400 }
    }
  }
  const rateIndex = parseCsv(searchParams.get('rateIndex'))
  for (const r of rateIndex) {
    if (!RATE_INDEX_VALUES.has(r)) {
      return { ok: false, error: `invalid rateIndex: ${r}`, status: 400 }
    }
  }
  return {
    ok: true,
    value: {
      cursor,
      since,
      limit: parseLimit(searchParams.get('limit')),
      filter: searchParams.get('filter'),
      clean: searchParams.get('clean') === 'true',
      lifecycle: lifecycle.map((l) => l.toLowerCase()),
      tradeTypes: parseCsv(searchParams.get('tradeTypes')),
      venues,
      ccps,
      sessions,
      rateIndex,
      tenors: parseCsv(searchParams.get('tenors')),
      fomcMeeting: searchParams.get('fomcMeeting'),
      columnFilters: parseColumnFilters(searchParams.get('columnFilters')),
      columnFilterOp: searchParams.get('columnFilterOp') === 'or' ? 'or' : 'and',
    },
  }
}

// ---------------------------------------------------------------------------
// WHERE-clause builder
// ---------------------------------------------------------------------------

const LIFECYCLE_TO_FLAG: Record<string, string> = {
  new_risk: 'd.is_new_risk',
  unwind: 'd.is_unwind',
  compression: 'd.is_compression_any',
  termination: 'd.is_termination_any',
  novation: 'd.is_novation_any',
  reset_opt: 'd.is_reset_optimization_any',
  correction: 'd.is_correction_any',
  clearing_term: 'd.is_clearing_termination_any',
  exercise_born: "(d.lifecycle_mix->>'EXERCISE_BORN')::int > 0",
}

export function buildCleanTapeClause(): string {
  return [
    'NOT d.is_unwind',
    'NOT d.is_compression_any',
    'NOT d.is_ufro_any',
    'NOT d.is_reset_optimization_any',
    'NOT d.is_clearing_termination_any',
    "COALESCE((d.lifecycle_mix->>'NOVATION'), '0')::int = 0",
    // Phase 3 cutover: drop anything the matrix tags as administrative
    // (β/γ NEWT-CLRG, partial novations, null-fill MODIs, port transfers,
    // VALU/MARU spam) and any row that the state-machine validator
    // flagged. The legacy is_*_any guards above remain so legacy v1 rows
    // (which lack contributes_to_flow_any) stay filtered too.
    'COALESCE(d.contributes_to_flow_any, TRUE) = TRUE',
    'COALESCE(d.state_machine_violation_any, FALSE) = FALSE',
  ].join(' AND ')
}

export function buildLifecycleClause(selected: string[]): string | null {
  if (selected.length === 0) return null
  const ors: string[] = []
  for (const lc of selected) {
    const expr = LIFECYCLE_TO_FLAG[lc]
    if (expr) ors.push(expr)
  }
  if (ors.length === 0) return null
  return `(${ors.join(' OR ')})`
}

export function buildCategoryInClause(
  column: string,
  values: string[],
  params: unknown[],
): string | null {
  if (values.length === 0) return null
  const placeholders = values.map((v) => {
    params.push(v)
    return `$${params.length}`
  })
  return `${column} IN (${placeholders.join(', ')})`
}

export function buildTenorInClause(values: string[], params: unknown[]): string | null {
  if (values.length === 0) return null
  const placeholders = values.map((v) => {
    params.push(v)
    return `$${params.length}`
  })
  return `EXISTS (
    SELECT 1 FROM jsonb_array_elements(d.legs_json) l
    WHERE (l->>'tenor_label') IN (${placeholders.join(', ')})
  )`
}

// ---------------------------------------------------------------------------
// columnFilters pushdown
//
// The dashboard's per-column filter overlay writes a `columnFilters` JSON
// payload to the URL via useColumnFilters. Pre-pushdown the route silently
// dropped that payload — every match was decided client-side after the
// cursor scan returned 200 packages per page. With a tape_label filter
// like "contains 10Y" the chain-load `useEffect` would drag down 14k+
// packages to find a few hundred matches.
//
// `buildColumnFilterClause` translates the same payload into parameterised
// SQL fragments, allowlisted to the columns surfaced in the overlay.
// Match-mode semantics mirror `matchFilterValue` in
// components/TradeTapeTable/filter-utils.ts so the SQL pushdown produces
// the same set as the existing client-side path; the client filter is
// retained as a defensive safety net.
// ---------------------------------------------------------------------------

const COLUMN_FILTER_ALLOWLIST_PACKAGE = new Set([
  'tape_label',
  'total_risk',
  'total_notional',
  'weighted_fixed_rate',
  'package_type',
  'package_indicator',
  'other_lvl_reported',
  'package_id',
  'opa_sign_confidence',
  'dealer_spread_bps',
])

const COLUMN_FILTER_ALLOWLIST_LEG = new Set([
  'platform_identifier',
  'lifecycle_type',
])

const TEXT_MATCH_MODES = new Set([
  'contains',
  'notContains',
  'startsWith',
  'endsWith',
  'equals',
  'notEquals',
  'in',
])

const NUMERIC_MATCH_MODES = new Set([
  'equals',
  'notEquals',
  'lt',
  'lte',
  'gt',
  'gte',
])

const NUMERIC_FIELDS = new Set([
  'total_risk',
  'total_notional',
  'weighted_fixed_rate',
  'dealer_spread_bps',
])

const ESCAPE_LIKE_RE = /[%_\\]/g

function escapeLikePattern(raw: string): string {
  return raw.replace(ESCAPE_LIKE_RE, (m) => '\\' + m)
}

function buildSingleConstraint(
  field: string,
  constraint: { value: unknown; matchMode?: string },
  params: unknown[],
): string | null {
  const { value, matchMode } = constraint
  if (value === null || value === undefined || value === '') return null
  if (Array.isArray(value) && value.length === 0) return null

  const isLeg = COLUMN_FILTER_ALLOWLIST_LEG.has(field)
  const isPackage = COLUMN_FILTER_ALLOWLIST_PACKAGE.has(field)
  if (!isLeg && !isPackage) return null

  const colExpr = isLeg ? `l->>'${field}'` : `d.${field}`

  // Numeric path
  if (NUMERIC_FIELDS.has(field) && NUMERIC_MATCH_MODES.has(String(matchMode))) {
    const n = Number(value)
    if (!Number.isFinite(n)) return null
    params.push(n)
    const p = `$${params.length}`
    const op =
      matchMode === 'lt'
        ? '<'
        : matchMode === 'lte'
          ? '<='
          : matchMode === 'gt'
            ? '>'
            : matchMode === 'gte'
              ? '>='
              : matchMode === 'notEquals'
                ? '<>'
                : '='
    return isLeg
      ? `EXISTS (SELECT 1 FROM jsonb_array_elements(d.legs_json) l WHERE (${colExpr})::numeric ${op} ${p})`
      : `${colExpr} ${op} ${p}`
  }

  // Text path
  const mode = String(matchMode ?? 'contains')
  if (!TEXT_MATCH_MODES.has(mode)) return null

  if (mode === 'in') {
    const arr = Array.isArray(value) ? value : [value]
    const ors: string[] = []
    for (const v of arr) {
      if (v === null || v === undefined || v === '') continue
      params.push(String(v).toLowerCase())
      const p = `$${params.length}`
      ors.push(`LOWER(${colExpr}) = ${p}`)
    }
    if (ors.length === 0) return null
    const inner = ors.join(' OR ')
    return isLeg
      ? `EXISTS (SELECT 1 FROM jsonb_array_elements(d.legs_json) l WHERE ${inner})`
      : `(${inner})`
  }

  if (mode === 'equals' || mode === 'notEquals') {
    params.push(String(value).toLowerCase())
    const p = `$${params.length}`
    const op = mode === 'notEquals' ? '<>' : '='
    return isLeg
      ? `EXISTS (SELECT 1 FROM jsonb_array_elements(d.legs_json) l WHERE LOWER(${colExpr}) ${op} ${p})`
      : `LOWER(${colExpr}) ${op} ${p}`
  }

  // contains / notContains / startsWith / endsWith — ILIKE patterns
  const escaped = escapeLikePattern(String(value))
  let pattern: string
  if (mode === 'startsWith') pattern = `${escaped}%`
  else if (mode === 'endsWith') pattern = `%${escaped}`
  else pattern = `%${escaped}%`
  params.push(pattern)
  const p = `$${params.length}`
  const op = mode === 'notContains' ? 'NOT ILIKE' : 'ILIKE'
  return isLeg
    ? `EXISTS (SELECT 1 FROM jsonb_array_elements(d.legs_json) l WHERE ${colExpr} ${op} ${p})`
    : `${colExpr} ${op} ${p}`
}

// ---------------------------------------------------------------------------
// Date-pattern parser for the execution_start column filter
//
// Traders type natural date patterns into the per-column filter input
// (`04/21`, `4/21/2026`, `2026-04-21`). Pre-this change, those values fell
// through to client-side substring matching against the NYC display string,
// which forced the chain-load to drag every day backward from today until
// a match was found. Parsing the value into a calendar date here lets
// buildColumnFilterClause emit a single `as_of_date = $1` predicate, hitting
// the existing idx_tape_v2_packages_date composite index.
//
// Returns ISO yyyy-mm-dd. Multi-day patterns and inequality patterns are
// NOT supported in v1 — see the design doc for deferred follow-ups.
// ---------------------------------------------------------------------------

const DATE_PATTERN_MD_Y = /^(\d{1,2})\/(\d{1,2})(?:\/(\d{2}|\d{4}))?$/
const DATE_PATTERN_ISO = /^(\d{4})-(\d{1,2})-(\d{1,2})$/

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

function isValidYmd(year: number, month: number, day: number): boolean {
  if (month < 1 || month > 12) return false
  if (day < 1 || day > 31) return false
  // Round-trip through Date to validate (catches Feb 30, etc.).
  const d = new Date(Date.UTC(year, month - 1, day))
  return (
    d.getUTCFullYear() === year &&
    d.getUTCMonth() === month - 1 &&
    d.getUTCDate() === day
  )
}

export function parseDatePattern(
  raw: unknown,
  now: Date = new Date(),
): string | null {
  if (typeof raw !== 'string') return null
  const trimmed = raw.trim()
  if (!trimmed) return null

  // M/D, M/D/YY, M/D/YYYY
  const mdMatch = trimmed.match(DATE_PATTERN_MD_Y)
  if (mdMatch) {
    const month = Number(mdMatch[1])
    const day = Number(mdMatch[2])
    const yearRaw = mdMatch[3]
    let year: number
    let yearWasExplicit = false
    if (yearRaw === undefined) {
      year = now.getFullYear()
    } else {
      yearWasExplicit = true
      year = Number(yearRaw)
      if (year < 100) year += Math.floor(now.getFullYear() / 100) * 100
    }
    if (!isValidYmd(year, month, day)) return null

    // If M/D defaulted to current year and the resulting date is in the
    // future (e.g. trader types "12/30" on 2027-01-05), step back a year so
    // they get the recent past.
    if (!yearWasExplicit) {
      const candidate = new Date(Date.UTC(year, month - 1, day))
      const today = new Date(
        Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()),
      )
      if (candidate.getTime() > today.getTime()) {
        year -= 1
        if (!isValidYmd(year, month, day)) return null
      }
    }
    return `${year}-${pad2(month)}-${pad2(day)}`
  }

  // YYYY-M-D, YYYY-MM-DD
  const isoMatch = trimmed.match(DATE_PATTERN_ISO)
  if (isoMatch) {
    const year = Number(isoMatch[1])
    const month = Number(isoMatch[2])
    const day = Number(isoMatch[3])
    if (!isValidYmd(year, month, day)) return null
    return `${year}-${pad2(month)}-${pad2(day)}`
  }

  return null
}

function areDatesContiguous(sortedDates: string[]): boolean {
  for (let i = 1; i < sortedDates.length; i++) {
    const prev = new Date(sortedDates[i - 1] + 'T00:00:00Z')
    const curr = new Date(sortedDates[i] + 'T00:00:00Z')
    if (curr.getTime() - prev.getTime() !== 86_400_000) return false
  }
  return true
}

export function buildColumnFilterClause(
  columnFilters: Record<string, any>,
  params: unknown[],
  options: { now?: Date } = {},
): string | null {
  if (!columnFilters || typeof columnFilters !== 'object') return null
  const fieldClauses: string[] = []
  const parsedDateBounds: string[] = []
  let executionStartInFilter = false

  for (const [field, meta] of Object.entries(columnFilters)) {
    if (!meta || typeof meta !== 'object') continue
    const constraints = Array.isArray(meta.constraints)
      ? meta.constraints
      : meta.value !== undefined
        ? [{ value: meta.value, matchMode: meta.matchMode }]
        : []
    if (constraints.length === 0) continue

    if (field === 'execution_start') {
      executionStartInFilter = true
      for (const c of constraints) {
        const parsed = parseDatePattern(c?.value, options.now)
        if (parsed !== null) {
          parsedDateBounds.push(parsed)
        }
      }
      continue
    }

    const op = meta.operator === 'or' ? ' OR ' : ' AND '
    const built = constraints
      .map((c: any) => buildSingleConstraint(field, c, params))
      .filter((s: string | null): s is string => s !== null)
    if (built.length === 0) continue
    fieldClauses.push(`(${built.join(op)})`)
  }

  // Date bounds are only injected when execution_start is explicitly in the
  // filter map. Previously ANY allowlisted column triggered a today-only
  // date clamp, which broke cross-day package_id lookups from the volume
  // grid and tape_label filters spanning multiple dates. Without an
  // explicit execution_start filter, ORDER BY + LIMIT naturally returns
  // the most recent matching rows via the execution_start DESC index.
  if (executionStartInFilter) {
    const uniqueDates = [...new Set(parsedDateBounds)].sort()
    if (uniqueDates.length === 0) {
      fieldClauses.push(
        `d.execution_start >= date_trunc('day', now() AT TIME ZONE 'America/New_York') AT TIME ZONE 'America/New_York'`,
      )
      fieldClauses.push(
        `d.execution_start <  date_trunc('day', now() AT TIME ZONE 'America/New_York') AT TIME ZONE 'America/New_York' + INTERVAL '1 day'`,
      )
    } else if (uniqueDates.length === 1) {
      params.push(uniqueDates[0])
      const p = `$${params.length}`
      fieldClauses.push(
        `d.execution_start >= (${p}::timestamp AT TIME ZONE 'America/New_York')`,
      )
      fieldClauses.push(
        `d.execution_start <  (${p}::timestamp AT TIME ZONE 'America/New_York') + INTERVAL '1 day'`,
      )
    } else if (areDatesContiguous(uniqueDates)) {
      params.push(uniqueDates[0])
      const pMin = `$${params.length}`
      params.push(uniqueDates[uniqueDates.length - 1])
      const pMax = `$${params.length}`
      fieldClauses.push(
        `d.execution_start >= (${pMin}::timestamp AT TIME ZONE 'America/New_York')`,
      )
      fieldClauses.push(
        `d.execution_start <  (${pMax}::timestamp AT TIME ZONE 'America/New_York') + INTERVAL '1 day'`,
      )
    } else {
      const dayRanges = uniqueDates.map((date) => {
        params.push(date)
        const p = `$${params.length}`
        return `(d.execution_start >= (${p}::timestamp AT TIME ZONE 'America/New_York') AND d.execution_start < (${p}::timestamp AT TIME ZONE 'America/New_York') + INTERVAL '1 day')`
      })
      fieldClauses.push(`(${dayRanges.join(' OR ')})`)
    }
  }

  if (fieldClauses.length === 0) return null
  return fieldClauses.join(' AND ')
}

export type BuiltQuery = {
  sql: string
  params: unknown[]
}

export function buildTapeQuery(
  parsed: ParsedParams,
  displayView: string,
  columns: string,
): BuiltQuery {
  const params: unknown[] = []
  const where: string[] = []

  if (parsed.clean) {
    where.push(buildCleanTapeClause())
  }
  const lc = buildLifecycleClause(parsed.lifecycle)
  if (lc) where.push(lc)

  const tradeTypeClause = buildCategoryInClause('d.package_type', parsed.tradeTypes, params)
  if (tradeTypeClause) where.push(tradeTypeClause)

  const venueClause = buildCategoryInClause('d.venue', parsed.venues, params)
  if (venueClause) where.push(venueClause)

  const ccpClause = buildCategoryInClause('d.ccp', parsed.ccps, params)
  if (ccpClause) where.push(ccpClause)

  const sessionClause = buildCategoryInClause('d.execution_session', parsed.sessions, params)
  if (sessionClause) where.push(sessionClause)

  const rateClause = buildCategoryInClause('d.rate_index_clean', parsed.rateIndex, params)
  if (rateClause) where.push(rateClause)

  const tenorClause = buildTenorInClause(parsed.tenors, params)
  if (tenorClause) where.push(tenorClause)

  if (parsed.fomcMeeting) {
    params.push(parsed.fomcMeeting)
    where.push(`d.fomc_meeting_label = $${params.length}`)
  }

  if (parsed.filter) {
    const pat = `%${parsed.filter.replace(/[%_\\]/g, (m) => '\\' + m)}%`
    params.push(pat)
    const p = `$${params.length}`
    where.push(
      `(
        d.tape_label ILIKE ${p}
        OR d.package_structure ILIKE ${p}
        OR d.package_tenors ILIKE ${p}
        OR d.package_id ILIKE ${p}
      )`,
    )
  }

  // Per-column filter overlay payload (URL-synced via useColumnFilters).
  // Pushed down to SQL so the cursor scan returns only matching rows;
  // before this, the chain-load loop dragged down every page and the
  // client-side filter trimmed the result, producing the trader-reported
  // "drag down 14k rows for 4k matches" behaviour.
  const columnFilterClause = buildColumnFilterClause(
    parsed.columnFilters,
    params,
  )
  if (columnFilterClause) where.push(columnFilterClause)

  // cursor / since
  if (parsed.cursor) {
    params.push(parsed.cursor)
    where.push(`d.execution_start < $${params.length}`)
  }
  if (parsed.since) {
    params.push(parsed.since)
    where.push(`d.execution_start > $${params.length}`)
  }

  params.push(parsed.limit + 1)
  const limitParam = `$${params.length}`

  const whereSql = where.length ? `WHERE ${where.join(' AND ')}` : ''

  // NULLS LAST is load-bearing: idx_tape_v2_packages_exec_start is declared
  // (execution_start DESC NULLS LAST), and Postgres matches ORDER BY pathkeys
  // syntactically — plain DESC (= NULLS FIRST) matches neither scan direction
  // of that index, forcing a seq-scan + external sort of every package row
  // (~29s on prod, past the client's 15s abort) instead of an index scan
  // (~60ms). execution_start is NOT NULL so the orderings return identical
  // rows.
  const sql = `
    SELECT ${columns}
    FROM ${displayView} d
    ${whereSql}
    ORDER BY d.execution_start DESC NULLS LAST
    LIMIT ${limitParam}
  `
  return { sql, params }
}
