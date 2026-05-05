// ABOUTME: Single source of truth for the volume-grid forward x tenor
// bucket schemas, package-type filter groups, and SQL helpers. Both
// /api/usd-swaps-tape-v2/volume-grid and /volume-grid/cell import from
// here so axes can never drift between the matrix view and its drill-
// down.
//
// The module is schema-driven: callers pick a `forwardSchema` /
// `tenorSchema` id, and the helpers below resolve to a concrete bucket
// list and SQL CASE expression. IMM-dated forward schemas are computed
// dynamically from `now` so the buckets always track the next 16
// quarterly IMM dates.

export interface BucketDef {
  /** SQL-safe id used in CASE labels and response keys. */
  readonly id: string
  /** UI label rendered as the row/column header. */
  readonly label: string
  /** Inclusive lower bound in years. `null` → -∞. */
  readonly lo: number | null
  /** Exclusive upper bound in years. `null` → +∞. */
  readonly hi: number | null
}

export type ForwardSchemaId = 'default' | 'legacy' | 'imm16'
export type TenorSchemaId = 'default' | 'legacy'

const ONE_DAY_MS = 86_400_000
const YEARS_PER_DAY = 1 / 365.25

// Default forward schema — user-spec 2026-05.
const FORWARD_DEFAULT: ReadonlyArray<BucketDef> = [
  // 1W = 7/365.25 ≈ 0.01916y. Anything below 1W or NULL → spot.
  { id: 'spot',     lo: null,    hi: 0.0192, label: 'Spot' },
  { id: '1w_3m',    lo: 0.0192,  hi: 0.25,   label: '1W-3M' },
  { id: '3m_6m',    lo: 0.25,    hi: 0.5,    label: '3M-6M' },
  { id: '6m_1y',    lo: 0.5,     hi: 1.0,    label: '6M-1Y' },
  { id: '1y_2y',    lo: 1.0,     hi: 2.0,    label: '1Y-2Y' },
  { id: '2y_5y',    lo: 2.0,     hi: 5.0,    label: '2Y-5Y' },
  { id: '5y_10y',   lo: 5.0,     hi: 10.0,   label: '5Y-10Y' },
  { id: '10y_plus', lo: 10.0,    hi: null,   label: '10Y+' },
] as const

// Legacy forward schema — original JPM-mirror bucket set, kept so any
// in-flight links / persisted state still resolve.
const FORWARD_LEGACY: ReadonlyArray<BucketDef> = [
  { id: 'spot',   lo: null,  hi: 0.083, label: 'spot' },
  { id: '6m_1y',  lo: 0.083, hi: 1.0,   label: '6m-1Y' },
  { id: '1y_2y',  lo: 1.0,   hi: 2.0,   label: '1Y-2Y' },
  { id: '2y_5y',  lo: 2.0,   hi: 5.0,   label: '2Y-5Y' },
  { id: '5y_10y', lo: 5.0,   hi: 10.0,  label: '5-10Y' },
] as const

// Default tenor schema — user-spec 2026-05.
const TENOR_DEFAULT: ReadonlyArray<BucketDef> = [
  { id: '1m_3m',    lo: 0.083,  hi: 0.25,   label: '1M-3M' },
  // 6M-12M absorbs the 3M-6M gap from the user's list (user listed 6M-12M
  // but no 3M-6M, so this bucket starts at 0.25y).
  { id: '6m_12m',   lo: 0.25,   hi: 1.0,    label: '6M-12M' },
  { id: '1y_18m',   lo: 1.0,    hi: 1.5,    label: '1Y-18M' },
  { id: '18m_2y',   lo: 1.5,    hi: 1.85,   label: '18M-2Y' },
  // Round-year tenors absorb the next half-year so e.g. a 2.4y tenor
  // still lands in '2Y' rather than falling through to '3Y'.
  { id: '2y',       lo: 1.85,   hi: 2.5,    label: '2Y' },
  { id: '3y',       lo: 2.5,    hi: 3.5,    label: '3Y' },
  { id: '4y',       lo: 3.5,    hi: 4.5,    label: '4Y' },
  { id: '5y',       lo: 4.5,    hi: 5.5,    label: '5Y' },
  { id: '6y_7y',    lo: 5.5,    hi: 7.5,    label: '6Y-7Y' },
  { id: '8y_9y',    lo: 7.5,    hi: 9.5,    label: '8Y-9Y' },
  { id: '10y',      lo: 9.5,    hi: 10.5,   label: '10Y' },
  { id: '10y_12y',  lo: 10.5,   hi: 12.5,   label: '10Y-12Y' },
  { id: '12y_15y',  lo: 12.5,   hi: 15.5,   label: '12Y-15Y' },
  { id: '15y_20y',  lo: 15.5,   hi: 19.5,   label: '15Y-20Y' },
  { id: '20y_25y',  lo: 19.5,   hi: 25.5,   label: '20Y-25Y' },
  { id: '30y_plus', lo: 25.5,   hi: null,   label: '30Y+' },
] as const

// Legacy tenor schema — original JPM-mirror tenor set.
const TENOR_LEGACY: ReadonlyArray<BucketDef> = [
  { id: '1y',     lo: null, hi: 1.5,  label: '1y' },
  { id: '2y',     lo: 1.5,  hi: 2.5,  label: '2y' },
  { id: '2_5y',   lo: 2.5,  hi: 4.5,  label: '2-5y' },
  { id: '5y',     lo: 4.5,  hi: 5.5,  label: '5y' },
  { id: '5_10y',  lo: 5.5,  hi: 9.5,  label: '5-10y' },
  { id: '10y',    lo: 9.5,  hi: 11.0, label: '10y' },
  { id: '10_20y', lo: 11.0, hi: 19.5, label: '10-20y' },
  { id: '20y',    lo: 19.5, hi: 21.0, label: '20y' },
  { id: '20_30y', lo: 21.0, hi: 29.5, label: '20-30y' },
  { id: '30y',    lo: 29.5, hi: 31.0, label: '30y' },
  { id: '50y',    lo: 31.0, hi: null, label: '50y' },
] as const

const FORWARD_SCHEMA_LABELS: Record<ForwardSchemaId, string> = {
  default: 'Default',
  legacy: 'Legacy',
  imm16: 'IMM (16q)',
}

const TENOR_SCHEMA_LABELS: Record<TenorSchemaId, string> = {
  default: 'Default',
  legacy: 'Legacy',
}

/**
 * Third Wednesday of the given month (UTC). Used to compute IMM dates.
 */
export function thirdWednesdayUtc(year: number, monthIdx0: number): Date {
  const first = new Date(Date.UTC(year, monthIdx0, 1))
  const dow = first.getUTCDay() // 0=Sun..6=Sat
  const daysToFirstWed = (3 - dow + 7) % 7
  const firstWed = 1 + daysToFirstWed
  return new Date(Date.UTC(year, monthIdx0, firstWed + 14))
}

/**
 * Compute the next `count` quarterly IMM dates (third Wed of Mar/Jun/Sep/Dec)
 * starting from `now`.
 */
export function computeImmDates(now: Date, count: number): Date[] {
  const imms: Date[] = []
  const immMonths = [2, 5, 8, 11] // Mar, Jun, Sep, Dec (0-based)
  let year = now.getUTCFullYear()
  while (imms.length < count) {
    for (const m of immMonths) {
      const imm = thirdWednesdayUtc(year, m)
      if (imm.getTime() >= now.getTime()) {
        imms.push(imm)
        if (imms.length >= count) break
      }
    }
    year += 1
  }
  return imms
}

/**
 * IMM forward schema — buckets are ±0.125y windows around each of the
 * next 16 quarterly IMM dates.
 */
function computeImm16ForwardBuckets(now: Date): ReadonlyArray<BucketDef> {
  const imms = computeImmDates(now, 16)
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: 'UTC',
    month: 'short',
    year: '2-digit',
  })
  return imms.map((imm, i) => {
    const yearsFromNow = (imm.getTime() - now.getTime()) / (365.25 * ONE_DAY_MS)
    const lo = Math.max(0, yearsFromNow - 0.125)
    const hi = yearsFromNow + 0.125
    return {
      id: `imm_${i + 1}`,
      label: fmt.format(imm).replace(' ', ''), // e.g. "Jun26"
      lo,
      hi,
    }
  })
}

export interface ResolvedSchema {
  id: string
  label: string
  buckets: ReadonlyArray<BucketDef>
}

export function resolveForwardSchema(
  id: ForwardSchemaId,
  now: Date = new Date(),
): ResolvedSchema {
  const label = FORWARD_SCHEMA_LABELS[id]
  switch (id) {
    case 'default': return { id, label, buckets: FORWARD_DEFAULT }
    case 'legacy':  return { id, label, buckets: FORWARD_LEGACY }
    case 'imm16':   return { id, label, buckets: computeImm16ForwardBuckets(now) }
  }
}

export function resolveTenorSchema(id: TenorSchemaId): ResolvedSchema {
  const label = TENOR_SCHEMA_LABELS[id]
  switch (id) {
    case 'default': return { id, label, buckets: TENOR_DEFAULT }
    case 'legacy':  return { id, label, buckets: TENOR_LEGACY }
  }
}

export const FORWARD_SCHEMA_IDS: ReadonlyArray<ForwardSchemaId> = ['default', 'legacy', 'imm16']
export const TENOR_SCHEMA_IDS: ReadonlyArray<TenorSchemaId> = ['default', 'legacy']

/**
 * Build a SQL CASE expression that classifies `${alias}.${column}` into
 * one of the schema's bucket ids. NULLs go into the first bucket if it
 * has `lo === null`, otherwise into 'other'. Out-of-range years go into
 * 'other' so callers can filter them out.
 */
export function buildBucketCaseSql(
  alias: string,
  column: string,
  buckets: ReadonlyArray<BucketDef>,
): string {
  const nullBucket = buckets.find((b) => b.lo == null)
  const lines: string[] = ['CASE']
  if (nullBucket) {
    lines.push(`  WHEN ${alias}.${column} IS NULL THEN '${nullBucket.id}'`)
  } else {
    lines.push(`  WHEN ${alias}.${column} IS NULL THEN 'other'`)
  }
  for (const b of buckets) {
    const conds: string[] = []
    if (b.lo != null) conds.push(`${alias}.${column} >= ${b.lo}`)
    if (b.hi != null) conds.push(`${alias}.${column} < ${b.hi}`)
    if (conds.length === 0) continue // unbounded sentinel handled by null branch
    lines.push(`  WHEN ${conds.join(' AND ')} THEN '${b.id}'`)
  }
  lines.push(`  ELSE 'other'`)
  lines.push('END')
  return lines.join('\n')
}

// ---------------------------------------------------------------------------
// Package-type filter groups
// ---------------------------------------------------------------------------

export type PackageTypeGroupId =
  | 'outright'
  | 'spreadover'        // SPREADOVER + MATCHED_MATURITY
  | 'curve'
  | 'spreadover_curve'  // SPREADOVER_CURVE + MATCHED_MATURITY_CURVE
  | 'fly'
  | 'spreadover_fly'    // SPREADOVER_FLY + MATCHED_MATURITY_FLY
  | 'fomc'
  | 'imm'
  | 'all'

export const PACKAGE_TYPE_GROUPS: Record<PackageTypeGroupId, ReadonlyArray<string>> = {
  outright:         ['OUTRIGHT'],
  spreadover:       ['SPREADOVER', 'MATCHED_MATURITY'],
  curve:            ['CURVE'],
  spreadover_curve: ['SPREADOVER_CURVE', 'MATCHED_MATURITY_CURVE'],
  fly:              ['FLY'],
  spreadover_fly:   ['SPREADOVER_FLY', 'MATCHED_MATURITY_FLY'],
  fomc:             ['FOMC'],
  imm:              ['IMM'],
  all:              [],
}

export const PACKAGE_TYPE_GROUP_LABELS: Record<PackageTypeGroupId, string> = {
  outright:         'Outright',
  spreadover:       'Spreadover / MM',
  curve:            'Curve',
  spreadover_curve: 'Spreadover Curve / MM Curve',
  fly:              'Fly',
  spreadover_fly:   'Spreadover Fly / MM Fly',
  fomc:             'FOMC',
  imm:              'IMM',
  all:              'All',
}

export const PACKAGE_TYPE_GROUP_IDS: ReadonlyArray<PackageTypeGroupId> = [
  'outright',
  'spreadover',
  'curve',
  'spreadover_curve',
  'fly',
  'spreadover_fly',
  'fomc',
  'imm',
  'all',
]

/**
 * Build a SQL predicate filtering `${alias}.package_type` to the values
 * in the requested group, with positional bind params starting at
 * `startIndex`. Returns `{ sql: 'TRUE', params: [] }` for the 'all'
 * group so callers can drop it into a WHERE chain unconditionally.
 */
export function buildPackageTypeFilter(
  groupId: PackageTypeGroupId,
  alias: string,
  startIndex: number,
): { sql: string; params: string[] } {
  const types = PACKAGE_TYPE_GROUPS[groupId]
  if (types.length === 0) return { sql: 'TRUE', params: [] }
  const placeholders = types.map((_, i) => `$${startIndex + i}`).join(', ')
  return {
    sql: `${alias}.package_type IN (${placeholders})`,
    params: [...types],
  }
}

// ---------------------------------------------------------------------------
// Year ↔ years-from-now helper for the IMM schema (used by the UI to
// compute exact bucket ids server-side requests can resolve)
// ---------------------------------------------------------------------------

export function yearsFromNow(target: Date, now: Date = new Date()): number {
  return (target.getTime() - now.getTime()) / (365.25 * ONE_DAY_MS * 1)
}
void YEARS_PER_DAY

// ---------------------------------------------------------------------------
// Cell-route predicate builder
// ---------------------------------------------------------------------------

/**
 * Build a parameterised WHERE predicate matching legs that fall into
 * the requested (forward, tenor) bucket pair given the schemas. Used by
 * the /volume-grid/cell drill-down route to filter to a single cell's
 * trades.
 */
export function buildBucketPredicate(
  legAlias: string,
  forwardSchema: ResolvedSchema,
  tenorSchema: ResolvedSchema,
  fwdId: string,
  tenorId: string,
  startParamIndex: number,
): { sql: string; params: number[] } {
  const fwd = forwardSchema.buckets.find((b) => b.id === fwdId)
  if (!fwd) {
    throw new Error(`unknown forward bucket id "${fwdId}" in schema "${forwardSchema.id}"`)
  }
  const tenor = tenorSchema.buckets.find((b) => b.id === tenorId)
  if (!tenor) {
    throw new Error(`unknown tenor bucket id "${tenorId}" in schema "${tenorSchema.id}"`)
  }
  const params: number[] = []
  const a = legAlias
  const parts: string[] = []
  let pi = startParamIndex
  if (fwd.lo == null) {
    if (fwd.hi != null) {
      parts.push(`(${a}.forward_start_years IS NULL OR ${a}.forward_start_years < $${pi})`)
      params.push(fwd.hi)
      pi += 1
    } else {
      parts.push(`TRUE`)
    }
  } else {
    parts.push(`${a}.forward_start_years >= $${pi}`)
    params.push(fwd.lo)
    pi += 1
    if (fwd.hi != null) {
      parts.push(`${a}.forward_start_years < $${pi}`)
      params.push(fwd.hi)
      pi += 1
    }
  }
  if (tenor.lo == null) {
    if (tenor.hi != null) {
      parts.push(`(${a}.tenor_years IS NULL OR ${a}.tenor_years < $${pi})`)
      params.push(tenor.hi)
      pi += 1
    } else {
      parts.push(`${a}.tenor_years IS NOT NULL`)
    }
  } else {
    parts.push(`${a}.tenor_years >= $${pi}`)
    params.push(tenor.lo)
    pi += 1
    if (tenor.hi != null) {
      parts.push(`${a}.tenor_years < $${pi}`)
      params.push(tenor.hi)
      pi += 1
    }
  }
  return { sql: parts.join(' AND '), params }
}
