// ABOUTME: Pure helpers for the tape v2 main route — parse filters, build WHERE clauses.
// No DB access here; unit-testable in isolation.

// Phase 4 cutover constant. Flip to 'arbs_usd_swap_tape_display_v1' to
// roll back to the frozen v1 view without a rebuild (design §4.11).
export const TAPE_DISPLAY_VIEW = 'arbs_usd_swap_tape_display_v2'

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
const RATE_INDEX_VALUES = new Set(['SOFR', 'FED_FUNDS', 'OTHER'])

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

export function buildColumnFilterClause(
  columnFilters: Record<string, any>,
  params: unknown[],
): string | null {
  if (!columnFilters || typeof columnFilters !== 'object') return null
  const fieldClauses: string[] = []
  for (const [field, meta] of Object.entries(columnFilters)) {
    if (!meta || typeof meta !== 'object') continue
    const constraints = Array.isArray(meta.constraints)
      ? meta.constraints
      : meta.value !== undefined
        ? [{ value: meta.value, matchMode: meta.matchMode }]
        : []
    if (constraints.length === 0) continue
    const op = meta.operator === 'or' ? ' OR ' : ' AND '
    const built = constraints
      .map((c: any) => buildSingleConstraint(field, c, params))
      .filter((s: string | null): s is string => s !== null)
    if (built.length === 0) continue
    fieldClauses.push(`(${built.join(op)})`)
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

  const sql = `
    SELECT ${columns}
    FROM ${displayView} d
    ${whereSql}
    ORDER BY d.execution_start DESC
    LIMIT ${limitParam}
  `
  return { sql, params }
}
