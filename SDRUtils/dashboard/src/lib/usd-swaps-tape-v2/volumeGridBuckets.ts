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

export type ForwardSchemaId = 'default' | 'legacy' | 'imm16' | 'fomc' | 'custom'
/** Column-axis schemas — tenor-by-years or platform_identifier (venue). */
export type TenorSchemaId = 'default' | 'legacy' | 'venue' | 'custom'

/**
 * Identifies how a forward schema's buckets are bound in SQL.
 *   - `years`:        forward_start_years vs lo/hi range CASE (default)
 *   - `fomc_label`:   bucket id is `fomc_meeting_label` directly; the schema's
 *                     bucket list is discovered dynamically from the data.
 */
export type ForwardSchemaKind = 'years' | 'fomc_label'

/**
 * Identifies how a column-axis schema's buckets are bound in SQL.
 *   - `tenor_years`:  tenor_years vs lo/hi range CASE (default)
 *   - `venue`:        bucket id is `platform_identifier` (a MIC code);
 *                     buckets are discovered dynamically from the data
 *                     and ordered IDB-first then CUSTY-first.
 */
export type TenorSchemaKind = 'tenor_years' | 'venue'

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
  { id: '30y_plus', lo: 25.5,   hi: null,   label: '25Y-30Y+' },
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

export function computeStructureDefaultForwardBuckets(now: Date = new Date()): ReadonlyArray<BucketDef> {
  const imms = computeImmDates(now, 4)
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: 'UTC',
    month: 'short',
    year: '2-digit',
  })
  const immBuckets: BucketDef[] = imms.map((imm, i) => {
    const yearsFromNow = (imm.getTime() - now.getTime()) / (365.25 * ONE_DAY_MS)
    return {
      id: `imm_${i + 1}`,
      label: `IMM${i + 1} (${fmt.format(imm).replace(' ', '')})`,
      lo: Math.max(0, yearsFromNow - 0.125),
      hi: yearsFromNow + 0.125,
    }
  })
  return [
    { id: 'spot', label: 'Spot', lo: null, hi: 0.125 },
    ...immBuckets,
    { id: '1y', label: '1Y', lo: 0.875, hi: 1.125 },
    { id: '2y', label: '2Y', lo: 1.875, hi: 2.125 },
    { id: '5y', label: '5Y', lo: 4.875, hi: 5.125 },
  ]
}

const FORWARD_SCHEMA_LABELS: Record<ForwardSchemaId, string> = {
  default: 'Default',
  legacy: 'Legacy',
  imm16: 'IMM (16q)',
  fomc: 'FOMC',
  custom: 'Custom',
}

const TENOR_SCHEMA_LABELS: Record<TenorSchemaId, string> = {
  default: 'Default',
  legacy: 'Legacy',
  venue: 'Venue (MIC)',
  custom: 'Custom',
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
  /**
   * How the schema's bucket id is computed in SQL.
   *  - 'years' / 'tenor_years': year-range CASE on the relevant column
   *    (default for forward + tenor schemas)
   *  - 'fomc_label': forward schema only — bucket id is `${alias}.fomc_meeting_label`
   *    directly; bucket list is discovered post-query.
   *  - 'venue': tenor (column) schema only — bucket id is `${alias}.platform_identifier`
   *    (MIC code); bucket list is discovered post-query.
   */
  kind?: ForwardSchemaKind | TenorSchemaKind
  /** Extra SQL fragment AND-joined into the legs CTE WHERE clause. */
  extraFilterSql?: string
}

export function resolveForwardSchema(
  id: ForwardSchemaId,
  now: Date = new Date(),
): ResolvedSchema {
  const label = FORWARD_SCHEMA_LABELS[id]
  switch (id) {
    case 'default': return { id, label, buckets: FORWARD_DEFAULT, kind: 'years' }
    case 'legacy':  return { id, label, buckets: FORWARD_LEGACY, kind: 'years' }
    case 'imm16':   return { id, label, buckets: computeImm16ForwardBuckets(now), kind: 'years' }
    case 'fomc':
      return {
        id, label,
        buckets: [], // populated post-query from distinct meeting labels
        kind: 'fomc_label',
        // The v2 legs feed populates `fomc_meeting_label` for any leg
        // whose payment schedule references an FOMC meeting; the
        // separate `is_fomc_dated` boolean isn't always set even for
        // FOMC-anchored prints, so filter only on the label being
        // present.
        extraFilterSql: 'l.fomc_meeting_label IS NOT NULL',
      }
    case 'custom':
      return { id, label, buckets: [], kind: 'years' }
  }
}

export function resolveTenorSchema(id: TenorSchemaId): ResolvedSchema {
  const label = TENOR_SCHEMA_LABELS[id]
  switch (id) {
    case 'default': return { id, label, buckets: TENOR_DEFAULT, kind: 'tenor_years' }
    case 'legacy':  return { id, label, buckets: TENOR_LEGACY, kind: 'tenor_years' }
    case 'venue':
      return {
        id, label,
        buckets: [], // populated post-query from distinct platform_identifier MICs
        kind: 'venue',
        extraFilterSql: 'l.platform_identifier IS NOT NULL',
      }
    case 'custom':
      return { id, label, buckets: [], kind: 'tenor_years' }
  }
}

export const FORWARD_SCHEMA_IDS: ReadonlyArray<ForwardSchemaId> = ['default', 'legacy', 'imm16', 'fomc', 'custom']
export const TENOR_SCHEMA_IDS: ReadonlyArray<TenorSchemaId> = ['default', 'legacy', 'venue', 'custom']

// Authoritative venue ordering: IDB MICs first, then CUSTY MICs, both in
// alphabetical order so the column layout stays stable across requests
// (the data doesn't always include every MIC). Used by the post-query
// venue bucket builder.
const VENUE_MIC_ORDER: ReadonlyArray<string> = [
  // IDB
  'BGCD', 'DWSF', 'IGDL', 'ISWV', 'TPSE', 'TSEF',
  // CUSTY
  'BBSF', 'BILT', 'TWSF', 'XOFF', 'XXXX',
]

/**
 * Build a venue (column) bucket list from observed platform_identifier
 * values. MICs in the canonical order come first, then any extra MICs
 * the feed produced (sorted alphabetically) so newer venues still
 * surface without a code change.
 */
export function buildVenueBucketsFromIdentifiers(
  identifiers: ReadonlyArray<string>,
): BucketDef[] {
  const seen = new Set(identifiers.filter((s) => s != null && s !== ''))
  const inOrder = VENUE_MIC_ORDER.filter((mic) => seen.has(mic))
  const known = new Set(inOrder)
  const extras = [...seen]
    .filter((mic) => !known.has(mic))
    .sort((a, b) => a.localeCompare(b))
  return [...inOrder, ...extras].map((mic) => ({
    id: mic, label: mic, lo: null, hi: null,
  }))
}

/**
 * Parse a SDR fomc_meeting_label like "APR26" into a Date for sorting.
 * Returns null on unparseable input.
 */
export function parseFomcLabel(label: string): Date | null {
  const m = /^([A-Z]{3})(\d{2})$/.exec(label)
  if (!m) return null
  const months = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC']
  const monthIdx = months.indexOf(m[1])
  if (monthIdx < 0) return null
  const yy = parseInt(m[2], 10)
  if (!Number.isFinite(yy)) return null
  const yyyy = yy < 50 ? 2000 + yy : 1900 + yy
  return new Date(Date.UTC(yyyy, monthIdx, 15))
}

/**
 * Build the FOMC schema's bucket list from a set of observed meeting
 * labels. Sorts chronologically (FOMC label format: "APR26"), drops
 * unparseable inputs, and trims to a useful window: starting from
 * `windowStart` (default = 30 days ago) onward, take at most `limit`
 * (default = 16) meetings going forward in time.
 */
export function buildFomcBucketsFromLabels(
  labels: ReadonlyArray<string>,
  opts: { now?: Date; windowStart?: Date; limit?: number } = {},
): BucketDef[] {
  const now = opts.now ?? new Date()
  const windowStart =
    opts.windowStart ?? new Date(now.getTime() - 30 * ONE_DAY_MS)
  const limit = opts.limit ?? 16
  const parsed = labels
    .map((label) => ({ label, date: parseFomcLabel(label) }))
    .filter((x): x is { label: string; date: Date } => x.date !== null)
    .filter((x) => x.date.getTime() >= windowStart.getTime())
  parsed.sort((a, b) => a.date.getTime() - b.date.getTime())
  return parsed.slice(0, limit).map(({ label }) => ({
    id: label,
    label,
    lo: null,
    hi: null,
  }))
}

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

export function buildPkgFamilySql(alias: string): string {
  return `CASE
    WHEN ${alias}.package_type IN ('OUTRIGHT','SPREADOVER','MATCHED_MATURITY') THEN 'outright'
    WHEN ${alias}.package_type IN ('CURVE','SPREADOVER_CURVE','MATCHED_MATURITY_CURVE') THEN 'curve'
    WHEN ${alias}.package_type IN ('FLY','SPREADOVER_FLY','MATCHED_MATURITY_FLY') THEN 'fly'
    ELSE 'other'
  END`
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
): { sql: string; params: Array<number | string> } {
  const params: Array<number | string> = []
  const a = legAlias
  const parts: string[] = []
  let pi = startParamIndex

  if (forwardSchema.kind === 'fomc_label') {
    // Schema-level filter (label NOT NULL) is applied upstream in the
    // route's WHERE chain. Here we just match the specific meeting label.
    if (!/^[A-Z]{3}\d{2}$/.test(fwdId)) {
      throw new Error(`fwd id "${fwdId}" is not a valid FOMC meeting label`)
    }
    parts.push(`${a}.fomc_meeting_label = $${pi}`)
    params.push(fwdId)
    pi += 1
  } else {
    const fwd = forwardSchema.buckets.find((b) => b.id === fwdId)
    if (!fwd) {
      throw new Error(`unknown forward bucket id "${fwdId}" in schema "${forwardSchema.id}"`)
    }
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
  }

  if (tenorSchema.kind === 'venue') {
    // Venue (column) drill-down: match the platform_identifier MIC.
    parts.push(`${a}.platform_identifier = $${pi}`)
    params.push(tenorId)
    pi += 1
  } else {
    const tenor = tenorSchema.buckets.find((b) => b.id === tenorId)
    if (!tenor) {
      throw new Error(`unknown tenor bucket id "${tenorId}" in schema "${tenorSchema.id}"`)
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
  }
  return { sql: parts.join(' AND '), params }
}
