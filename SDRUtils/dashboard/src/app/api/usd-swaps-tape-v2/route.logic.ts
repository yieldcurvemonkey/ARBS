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
