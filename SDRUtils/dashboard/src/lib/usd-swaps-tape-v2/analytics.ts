// Server-side helpers shared by the analytics dock API routes.
// Platform classification (custy vs IDB), distribution stats, and the
// SQL expression that splits leg rows into the two platforms off the
// venue column. Kept close to the DB layer so routes stay declarative.

// Platform classification for the analytics dock (IDB vs CUSTY).
//
// The SDR feed exposes two signals:
//   - `venue`: coarse D2D / D2C tag ("dealer-to-dealer" / "dealer-to-client")
//   - `platform_identifier`: MIC-style code
//
// Authoritative dealer (IDB) MICs:
//   BGCD — BGC Derivative Markets L.P.
//   DWSF — Dealerweb SEF LLC
//   IGDL — ICAP Global Derivatives Ltd
//   ISWV — ICAP Global Derivatives Ltd – Voice
//   TPSE — TP SEF Inc
//   TSEF — Tradition SEF
//
// Authoritative custy MICs:
//   TWSF, BBSF, BILT, XOFF, XXXX
//
// D2D maps cleanly to IDB. Anything else (D2C or null) we call custy.
// The MIC code is kept as a fallback so the logic still works if a
// future feed drops the venue column. Earlier revisions of this set
// only listed BGCD / ISWV / TPSE, which mis-bucketed Dealerweb /
// ICAP-Global / Tradition flow into custy.
export const IDB_MIC_SET = [
  'BGCD',
  'DWSF',
  'IGDL',
  'ISWV',
  'TPSE',
  'TSEF',
] as const

// Explicit custy whitelist used by tests + the venue chip's tooltip
// disambiguation. Anything not in IDB_MIC_SET *and* not in this set
// falls through to CUSTY anyway, but pinning it makes the contract
// reviewable.
export const CUSTY_MIC_SET = [
  'TWSF',
  'BBSF',
  'BILT',
  'XOFF',
  'XXXX',
] as const

export function platformCaseSql(alias: string): string {
  const micLikes = IDB_MIC_SET
    .map((mic) => `UPPER(COALESCE(${alias}.platform_identifier, '')) = '${mic}'`)
    .join(' OR ')
  return `CASE
    WHEN UPPER(COALESCE(${alias}.venue, '')) = 'D2D' THEN 'IDB'
    WHEN ${micLikes} THEN 'IDB'
    ELSE 'CUSTY'
  END`
}

const SOFR_TERM_PREFIX_RE = /^USD[-\s]+SOFR[-\s]+(?:CME[-\s]+)?TERM/i
const SOFR_OIS_PREFIX_RE =
  /^USD[-\s]+SOFR(?:[-\s]+OIS)?(?:[-\s]+COMPOUND|\s+COMPOUND)?/i

// Lifecycle / event flags that the ingest layer (`trade_tape.py
// _label_for_row`) appends to the package tape_label. They make every
// unwind / clearing / restate row produce a bucket-of-one against the
// analytics-timeseries query (which filters by tape_label), so the dock
// chart had no historical context for unwind / restate / clearing rows.
// Strip them so an UNWIND row buckets with the underlying instrument's
// flow prints. UFRO (off-market upfront marker) and BLOCK (size flag)
// stay in — they describe the trade economics, not its lifecycle.
const ANALYTICS_LIFECYCLE_FLAG_TOKENS = [
  'UNWIND',
  'PARTIAL-UNWIND',
  'TERM',
  'CORR',
  'MODI',
  'XD-TERM',
  'NOVA-IN',
  'NOVA-OUT',
  'EXER',
  'CLRG',
] as const

export const __analyticsLifecycleFlagTokens = ANALYTICS_LIFECYCLE_FLAG_TOKENS

const LIFECYCLE_FLAG_RE = new RegExp(
  `(^|\\s)(?:${ANALYTICS_LIFECYCLE_FLAG_TOKENS.join('|')})(?=\\s|$)`,
  'gi',
)

// Tape-label analytics should bucket by economic label, not by SDR/UPI
// spelling. Keep this intentionally narrow: SOFR OIS source prefixes,
// PHY/PHYS delivery spelling, and the lifecycle/event flag tokens
// that mark per-print state (UNWIND / TERM / CORR / MODI / etc.).
export function normalizeAnalyticsTapeLabel(
  label: string | null | undefined,
): string {
  let text = String(label ?? '')
    .trim()
    .replace(/\s+/g, ' ')
    .toUpperCase()
  text = text
    .replace(/\bPHYSICAL\b/g, 'PHYS')
    .replace(/\bPHY\b/g, 'PHYS')
  if (SOFR_TERM_PREFIX_RE.test(text)) {
    text = text.replace(SOFR_TERM_PREFIX_RE, 'USD-SOFR-TERM')
  } else {
    text = text.replace(SOFR_OIS_PREFIX_RE, 'USD-SOFR-OIS COMPOUND')
  }
  // Strip lifecycle / event flag tokens so per-row state doesn't
  // shatter the bucket. Run repeatedly so adjacent flags
  // ("MMS UNWIND") collapse cleanly without leaving doubled spaces.
  while (LIFECYCLE_FLAG_RE.test(text)) {
    LIFECYCLE_FLAG_RE.lastIndex = 0
    text = text.replace(LIFECYCLE_FLAG_RE, '$1')
  }
  return text.replace(/\s+/g, ' ').trim()
}

function cleanTapeLabelSql(valueExpr: string): string {
  return `BTRIM(REGEXP_REPLACE(UPPER(COALESCE(${valueExpr}::text, '')), '[[:space:]]+', ' ', 'g'))`
}

function normalizeDeliverySql(valueExpr: string): string {
  const physical =
    `REGEXP_REPLACE(${valueExpr}, '(^|[[:space:]])PHYSICAL($|[[:space:]])', '\\1PHYS\\2', 'g')`
  return `REGEXP_REPLACE(${physical}, '(^|[[:space:]])PHY($|[[:space:]])', '\\1PHYS\\2', 'g')`
}

function stripLifecycleFlagsSql(valueExpr: string): string {
  // Mirror ANALYTICS_LIFECYCLE_FLAG_TOKENS — strip lifecycle / event
  // tokens that the ingest layer appends per row so unwind / restate /
  // clearing rows still bucket against their underlying instrument.
  // POSIX regex has no word boundaries; pad the value with spaces and
  // match `[[:space:]]TOKEN[[:space:]]`, replacing with a single space,
  // then collapse consecutive spaces and trim.
  const tokens = ANALYTICS_LIFECYCLE_FLAG_TOKENS.join('|')
  // Two passes so adjacent flags ("MMS UNWIND PHYS") collapse cleanly:
  // each pass consumes both surrounding spaces, so sequential flags
  // need a second sweep to re-pair the new boundaries.
  const padded = `(' ' || ${valueExpr} || ' ')`
  const stripOnce = (expr: string): string =>
    `REGEXP_REPLACE(${expr}, '[[:space:]](${tokens})[[:space:]]', ' ', 'gi')`
  const stripped = stripOnce(stripOnce(padded))
  const collapsed = `REGEXP_REPLACE(${stripped}, '[[:space:]]+', ' ', 'g')`
  return `BTRIM(${collapsed})`
}

export function normalizeAnalyticsTapeLabelSql(valueExpr: string): string {
  const cleaned = cleanTapeLabelSql(valueExpr)
  const delivery = normalizeDeliverySql(cleaned)
  const termPattern = '^USD[[:space:]-]+SOFR[[:space:]-]+(CME[[:space:]-]+)?TERM'
  const sofrOisPattern = '^USD[[:space:]-]+SOFR([[:space:]-]+OIS)?([[:space:]-]+COMPOUND)?'
  const term = `REGEXP_REPLACE(${delivery}, '${termPattern}', 'USD-SOFR-TERM', 'i')`
  const sofrOis = `REGEXP_REPLACE(${delivery}, '${sofrOisPattern}', 'USD-SOFR-OIS COMPOUND', 'i')`
  const prefixed = `CASE
    WHEN ${delivery} ~* '${termPattern}' THEN ${term}
    ELSE ${sofrOis}
  END`
  return stripLifecycleFlagsSql(`(${prefixed})`)
}

export function packageAnalyticsFilterPredicate(
  groupBy: string,
  valueParam: string,
  legsTable: string,
  opts?: { candidatesMode?: boolean },
): string | null {
  if (groupBy === 'tape_label') {
    if (opts?.candidatesMode) {
      return `UPPER(COALESCE(p.tape_label, '')) = ANY(${valueParam}::text[])`
    }
    return `(
      p.tape_label = ${valueParam}
      OR ${normalizeAnalyticsTapeLabelSql('p.tape_label')} = ${normalizeAnalyticsTapeLabelSql(valueParam)}
    )`
  }
  if (groupBy === 'package') return `p.package_id = ${valueParam}`
  if (groupBy === 'trade_type') return `p.package_type = ${valueParam}`
  if (groupBy === 'tenor') {
    return `EXISTS (
      SELECT 1 FROM ${legsTable} lf
      WHERE lf.package_id = p.package_id
        AND lf.tenor_label = ${valueParam}
    )`
  }
  if (groupBy === 'canonical') {
    return `EXISTS (
      SELECT 1 FROM ${legsTable} lf
      WHERE lf.package_id = p.package_id
        AND lf.canonical_underlier_key = ${valueParam}
    )`
  }
  return null
}

function packageKindSql(alias: string, kind: 'CURVE' | 'FLY' | 'SPREADOVER'): string {
  return `(
    UPPER(CONCAT_WS(' ', ${alias}.package_type, ${alias}.tape_label))
      ~ '(^|[^A-Z0-9])${kind}([^A-Z0-9]|$)'
  )`
}

function packageLegIndexSql(alias: string): string {
  return `GREATEST(1, COALESCE(${alias}.legs_count, 1))`
}

function packageMiddleLegIndexSql(alias: string): string {
  return `GREATEST(1, ((COALESCE(${alias}.legs_count, 1) + 1) / 2)::int)`
}

export function packageSummaryFixedRateSql(alias: string): string {
  const last = packageLegIndexSql(alias)
  const mid = packageMiddleLegIndexSql(alias)
  return `CASE
    WHEN ${packageKindSql(alias, 'FLY')} AND COALESCE(${alias}.legs_count, 0) >= 3 THEN
      2 * ${alias}.fixed_rates[${mid}] - ${alias}.fixed_rates[1] - ${alias}.fixed_rates[${last}]
    WHEN ${packageKindSql(alias, 'CURVE')} AND COALESCE(${alias}.legs_count, 0) >= 2 THEN
      ${alias}.fixed_rates[${last}] - ${alias}.fixed_rates[1]
    WHEN ${packageKindSql(alias, 'SPREADOVER')} AND COALESCE(${alias}.legs_count, 0) >= 2 THEN
      ${alias}.fixed_rates[${last}] - ${alias}.fixed_rates[1]
    ELSE COALESCE(${alias}.weighted_fixed_rate, ${alias}.fixed_rates[1])
  END`
}

export function packageSummaryRiskSql(alias: string): string {
  const last = packageLegIndexSql(alias)
  const mid = packageMiddleLegIndexSql(alias)
  return `CASE
    WHEN ${packageKindSql(alias, 'FLY')} AND COALESCE(${alias}.legs_count, 0) >= 3 THEN
      ${alias}.risks[${mid}]
    WHEN ${packageKindSql(alias, 'CURVE')} AND COALESCE(${alias}.legs_count, 0) >= 2 THEN
      ${alias}.risks[${last}]
    WHEN ${packageKindSql(alias, 'SPREADOVER')} AND COALESCE(${alias}.legs_count, 0) >= 2 THEN
      ${alias}.risks[${last}]
    ELSE COALESCE(${alias}.total_risk, ${alias}.risks[1])
  END`
}

export function packageAnalyticsCtes(opts: {
  packagesTable: string
  legsTable: string
  filterPredicate: string
  timePredicate?: string
}): string {
  const where = [
    opts.filterPredicate,
    opts.timePredicate,
    'NOT COALESCE(p.is_unwind, false)',
  ].filter(Boolean).join('\n        AND ')
  const rateExpr = packageSummaryFixedRateSql('r')
  const riskExpr = packageSummaryRiskSql('r')
  return `
      package_rollup AS (
        SELECT
          p.package_id,
          p.tape_label,
          p.package_type,
          COALESCE(p.original_execution_start, p.execution_start) AS ts,
          p.venue,
          (array_agg(l.platform_identifier ORDER BY l.leg_order ASC))[1] AS platform_identifier,
          (array_agg(l.trade_id ORDER BY l.leg_order ASC))[1] AS trade_id,
          p.total_risk::float AS total_risk,
          p.weighted_fixed_rate::float AS weighted_fixed_rate,
          COALESCE(
            ABS(p.total_notional::float),
            ABS(p.gross_notional::float),
            SUM(ABS(l.notional::float))
          ) AS notional,
          array_agg(l.fixed_rate::float ORDER BY l.tenor_years ASC NULLS LAST, l.leg_order ASC) AS fixed_rates,
          array_agg(l.risk::float ORDER BY l.tenor_years ASC NULLS LAST, l.leg_order ASC) AS risks,
          COUNT(*)::int AS legs_count,
          p.package_transaction_spread::float AS pts
        FROM ${opts.packagesTable} p
        JOIN ${opts.legsTable} l ON l.package_id = p.package_id
        WHERE ${where}
        GROUP BY
          p.package_id,
          p.tape_label,
          p.package_type,
          p.original_execution_start,
          p.execution_start,
          p.venue,
          p.total_risk,
          p.weighted_fixed_rate,
          p.total_notional,
          p.gross_notional,
          p.package_transaction_spread
      ),
      package_summary_unfiltered AS (
        SELECT
          r.package_id,
          r.trade_id,
          r.tape_label,
          r.package_type,
          r.ts,
          r.venue,
          ${platformCaseSql('r')} AS platform,
          ${rateExpr} AS fixed_rate,
          ${riskExpr} AS risk,
          r.notional,
          r.pts
        FROM package_rollup r
      ),
      package_summary AS (
        SELECT *
        FROM package_summary_unfiltered
        WHERE fixed_rate IS NOT NULL
      )`
}

export function rangeToStartDate(range: string | null | undefined): Date {
  const now = new Date()
  const d = new Date(now)
  switch (range) {
    case '1D':
      d.setUTCDate(now.getUTCDate() - 1); return d
    case '1W':
      d.setUTCDate(now.getUTCDate() - 7); return d
    case '1M':
      d.setUTCMonth(now.getUTCMonth() - 1); return d
    case '3M':
      d.setUTCMonth(now.getUTCMonth() - 3); return d
    case '6M':
      d.setUTCMonth(now.getUTCMonth() - 6); return d
    case '1Y':
    case 'CUSTOM':
    default:
      d.setUTCFullYear(now.getUTCFullYear() - 1); return d
  }
}

// JS percentile — linear interpolation.
export function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0
  if (sorted.length === 1) return sorted[0]
  const idx = (sorted.length - 1) * (p / 100)
  const lo = Math.floor(idx)
  const hi = Math.ceil(idx)
  if (lo === hi) return sorted[lo]
  return sorted[lo] * (hi - idx) + sorted[hi] * (idx - lo)
}

export type DistStats = {
  count: number
  mean: number
  stddev: number
  median: number
  p5: number
  p25: number
  p75: number
  p95: number
  iqr: number
  min: number
  max: number
}

export function distributionStats(values: number[]): DistStats {
  const sorted = [...values].filter((v) => Number.isFinite(v)).sort((a, b) => a - b)
  if (sorted.length === 0) {
    return { count: 0, mean: 0, stddev: 0, median: 0, p5: 0, p25: 0, p75: 0, p95: 0, iqr: 0, min: 0, max: 0 }
  }
  const mean = sorted.reduce((a, b) => a + b, 0) / sorted.length
  const variance = sorted.reduce((s, x) => s + (x - mean) ** 2, 0) / sorted.length
  const stddev = Math.sqrt(variance)
  const p5 = percentile(sorted, 5)
  const p25 = percentile(sorted, 25)
  const p50 = percentile(sorted, 50)
  const p75 = percentile(sorted, 75)
  const p95 = percentile(sorted, 95)
  return {
    count: sorted.length,
    mean, stddev,
    median: p50, p5, p25, p75, p95,
    iqr: p75 - p25,
    min: sorted[0], max: sorted[sorted.length - 1],
  }
}

export function percentileRank(value: number, sorted: number[]): number {
  if (sorted.length === 0) return 50
  if (value <= sorted[0]) return 0
  if (value >= sorted[sorted.length - 1]) return 100
  let lo = 0, hi = sorted.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (sorted[mid] < value) lo = mid + 1
    else if (sorted[mid] > value) hi = mid - 1
    else return (mid / (sorted.length - 1)) * 100
  }
  return (lo / (sorted.length - 1)) * 100
}

// Fixed rate lives in the DB as a decimal (0.03842) and renders in the
// analytics surface as basis points (384.2). One source-of-truth shim.
export function rateToBps(decimal: number | null | undefined): number {
  if (decimal == null || Number.isNaN(decimal)) return 0
  return +(Number(decimal) * 10_000).toFixed(2)
}

export function safeNum(n: unknown): number {
  const v = Number(n)
  return Number.isFinite(v) ? v : 0
}

export function rarityZone(p: number): 'typical' | 'notable' | 'rare' | 'extreme' {
  const d = Math.abs(p - 50)
  if (d <= 25) return 'typical'
  if (d <= 40) return 'notable'
  if (d <= 47) return 'rare'
  return 'extreme'
}

export function rarityDescriptor(p: number): string {
  const d = Math.abs(p - 50)
  if (d <= 25) return 'in the middle band'
  if (d <= 40) return p > 50 ? 'above typical range' : 'below typical range'
  if (d <= 47) return p > 50 ? 'rarely seen this high' : 'rarely seen this low'
  return p > 50 ? 'extreme high print' : 'extreme low print'
}
