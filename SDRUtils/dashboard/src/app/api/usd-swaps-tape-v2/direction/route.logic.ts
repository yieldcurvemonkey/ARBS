// ABOUTME: Param parsing, SQL building, and the cross-bucket-level refusal for
// the dealer-direction endpoints. Pure — no I/O, so it is tested with no mocks.
//
// ====================================================================
// THE REFUSAL LIVES HERE, BECAUSE IT CANNOT LIVE IN THE TABLE
// ====================================================================
//
// DV01 retention runs 0.761 at 0-1Y down to 0.495 at 15-20Y — a 1.54x
// cross-bucket scaling distortion — because the packages the classifier cannot
// orient are not a random sample of the tape. So:
//
//     "the 5y bucket against its own history"  is supportable
//     "dealers are longer 5y than 10y"         is not
//
// A bar chart of signed DV01 across tenor buckets is exactly the forbidden
// view, and it is the first chart anyone would draw.
//
// The Python side refuses it structurally rather than in a docstring:
// indicator.cross_section() raises, the level column is NAMED FOR ITS BUCKET
// (delta_dv01__5_7Y) so a naive concat is a NaN block diagonal, and there is no
// to_frame accessor. A Postgres table cannot do any of that — buckets are rows,
// and `SELECT bucket_key, delta_dv01 ... WHERE visibility_date = $1` is one
// line of SQL. So the enforcement point is this module:
//
//   * levelSql() serves ONE bucket, and buildBucketParams throws on a missing,
//     unknown, or repeated `bucket`;
//   * standardisedSql() serves every bucket and selects NO level column at all;
//   * suffixLevels() renames the level keys on the wire to delta_dv01__5_7Y,
//     so even a client that concatenated two bucket responses would get
//     non-aligning keys rather than a comparison.
//
// A route test asserts that no key in the /standardised payload matches
// /delta_dv01|abs_dv01/. That assertion is the control; this comment is not.
//
// What IS cross-bucket safe is `z`, exactly:
//     z = (r_b*L - r_b*mu) / (r_b*sigma) = (L - mu) / sigma
// a constant retention factor cancels. That is why /standardised exists.

import { DD_COVERAGE, DD_IN_LADDER, DD_LADDER, DD_UNIT } from '@/lib/dealer-direction-tables'

/** indicator.TENOR_BUCKETS, verbatim and in order. */
export const TENOR_BUCKETS = [
  '0-1Y', '1-2Y', '2-3Y', '3-5Y', '5-7Y',
  '7-10Y', '10-15Y', '15-20Y', '20-30Y', '30Y+',
] as const
export type TenorBucket = (typeof TENOR_BUCKETS)[number]

/** types.VENUE_* — three series, never merged. VENUE_UNKNOWN is not "UNKNOWN". */
export const VENUE_CLASSES = ['D2C', 'D2D', 'VENUE_UNKNOWN'] as const
export type VenueClass = (typeof VENUE_CLASSES)[number]

/** ladder.SERIES_* */
export const SERIES = ['FLOW', 'LIFECYCLE'] as const
export type Series = (typeof SERIES)[number]

export const BUCKET_SPACE = 'TENOR10'

/** indicator.SAMPLE_FLOOR. Earlier dates are not published. */
export const SAMPLE_FLOOR = '2024-07-01'

/** indicator._slug: "-" -> "_", "+" -> "plus". Must match Python exactly. */
export function slug(bucket: string): string {
  return bucket.replace(/-/g, '_').replace(/\+/g, 'plus')
}

/** indicator.level_column("5-7Y") === "delta_dv01__5_7Y" */
export function levelColumn(bucket: string, basis: 'raw' | 'cov_adj' | 'gross' = 'raw'): string {
  const base =
    basis === 'raw' ? 'delta_dv01' : basis === 'cov_adj' ? 'delta_dv01_cov_adj' : 'abs_dv01'
  return `${base}__${slug(bucket)}`
}

export class BadRequest extends Error {}

/** Columns published for a single bucket's own history. Levels included. */
export const BUCKET_COLUMNS = [
  'visibility_date', 'observed',
  'delta_dv01', 'delta_dv01_cov_adj', 'abs_dv01',
  'n_units', 'mean_abs_signed_weight',
  'z_raw', 'z_cov_adj', 'pct_raw', 'z_n_obs',
  'coverage_frac', 'coverage_smooth', 'coverage_drift_flag',
  'coverage_trend_pp_per_yr', 'coverage_drift_source',
  'coverage_dv01_kept', 'coverage_dv01_total',
  'frac_dv01_block', 'frac_dv01_capped', 'frac_dv01_dead_zone',
  'frac_dv01_visibility_measured',
  'code_vintage', 'primary_level_basis',
] as const

/**
 * Columns published across ALL buckets. NO LEVEL.
 *
 * Everything here is either invariant to the retention factor (z), a share
 * (coverage_frac, the frac_dv01_* family), a count, or a flag. Adding a
 * DV01-valued column to this list would defeat the whole control, which is why
 * a test asserts the absence rather than trusting the list.
 */
export const STANDARDISED_COLUMNS = [
  'bucket_key', 'visibility_date', 'observed',
  'z_raw', 'z_cov_adj', 'pct_raw', 'z_n_obs',
  'n_units', 'mean_abs_signed_weight',
  'coverage_frac', 'coverage_smooth', 'coverage_drift_flag',
  'coverage_trend_pp_per_yr', 'coverage_drift_source',
  'frac_dv01_block', 'frac_dv01_capped', 'frac_dv01_dead_zone',
  'frac_dv01_visibility_measured',
] as const

/** Anything whose value is a signed or gross DV01 level. */
const LEVEL_KEY = /^(delta_dv01|abs_dv01)/

export function assertNoLevelKeys(rows: Record<string, unknown>[]): void {
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (LEVEL_KEY.test(key)) {
        throw new Error(
          `the all-bucket payload carries the level key ${key!}; a level is not ` +
            'comparable across buckets (retention 0.761 at 0-1Y vs 0.495 at ' +
            '15-20Y, a 1.54x scaling distortion). Use z.',
        )
      }
    }
  }
}

export type CommonParams = {
  venueClass: VenueClass
  series: Series
  from: string
  to: string | null
  lastSessions: number
}

/**
 * How many trailing sessions /standardised returns by default.
 *
 * THIS IS A RESPONSE-SIZE CONTROL, NOT A PREFERENCE, and it exists because the
 * unbounded version has a dated failure.
 *
 * MEASURED on the production build: the endpoint returns one row per
 * (bucket, session) at 541 B/row and there are 10 buckets, so 5,407 B per
 * session. At 629 published sessions that is 3.24 MB. Vercel's documented
 * serverless response cap is 4.5 MB, i.e. 873 sessions -- 244 trading sessions
 * away, about 11.6 months. Past it the panel does not get slower, it 500s.
 *
 * And the whole overage is waste: the heatmap draws HEATMAP_DAYS = 60. 90 is
 * that with headroom, and it takes the payload from 3,322 KB to 375 KB and the
 * query from 102 ms to 24 ms.
 *
 * A consumer that genuinely wants more asks for it, and the response says
 * whether it was cut, so this can never silently truncate someone's history.
 */
export const DEFAULT_LAST_SESSIONS = 90

/**
 * The ceiling on that ask. 400 sessions is ~2.16 MB, comfortably under the cap
 * with room for the row to grow a column or two. Above this the caller is
 * building something the ladder endpoint is the wrong shape for.
 */
export const MAX_LAST_SESSIONS = 400

function parseDate(raw: string | null, name: string): string | null {
  if (!raw) return null
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    throw new BadRequest(`${name} must be YYYY-MM-DD`)
  }
  return raw
}

export function parseCommon(sp: URLSearchParams): CommonParams {
  const venueClass = (sp.get('venueClass') ?? 'D2C') as VenueClass
  if (!VENUE_CLASSES.includes(venueClass)) {
    throw new BadRequest(
      `venueClass must be one of ${VENUE_CLASSES.join(', ')}. D2C, D2D and ` +
        'VENUE_UNKNOWN are three separate series and are never summed: dealers ' +
        'recycling risk among themselves is not customer flow.',
    )
  }
  const series = (sp.get('series') ?? 'FLOW') as Series
  if (!SERIES.includes(series)) {
    throw new BadRequest(`series must be one of ${SERIES.join(', ')}`)
  }
  const from = parseDate(sp.get('from'), 'from') ?? SAMPLE_FLOOR
  const to = parseDate(sp.get('to'), 'to')

  const rawLast = sp.get('lastSessions')
  let lastSessions = DEFAULT_LAST_SESSIONS
  if (rawLast != null && rawLast !== '') {
    lastSessions = Number(rawLast)
    if (!Number.isInteger(lastSessions) || lastSessions < 1 || lastSessions > MAX_LAST_SESSIONS) {
      throw new BadRequest(
        `lastSessions must be an integer between 1 and ${MAX_LAST_SESSIONS}. ` +
          'The ladder returns one row per (bucket, session) at a measured ' +
          '5,407 B per session across 10 buckets, so an unbounded window walks ' +
          "into Vercel's 4.5 MB serverless response cap at 873 sessions — " +
          'where the panel 500s rather than slows.',
      )
    }
  }
  if (from < SAMPLE_FLOOR) {
    throw new BadRequest(
      `from is before the sample floor ${SAMPLE_FLOOR}. The exclusion rate ` +
        'steps -3.2pp across the ingest break and the tape carries no ' +
        'termination events before it.',
    )
  }
  return { venueClass, series, from, to, lastSessions }
}

/**
 * Exactly one bucket. A list is refused rather than served, because serving a
 * list of levels IS the cross-bucket level comparison however it is drawn.
 */
export function parseBucket(sp: URLSearchParams): TenorBucket {
  const all = sp.getAll('bucket')
  if (all.length === 0) {
    throw new BadRequest(
      'bucket is required. This endpoint serves one bucket\'s own history; ' +
        'there is deliberately no way to ask it for several at once.',
    )
  }
  if (all.length > 1 || all[0]!.includes(',')) {
    throw new BadRequest(
      'bucket takes exactly one value. A signed DV01 level is not comparable ' +
        'across buckets — retention runs 0.761 at 0-1Y against 0.495 at ' +
        '15-20Y. For a cross-sectional read use /direction/standardised, ' +
        'which serves z and no level.',
    )
  }
  const bucket = all[0] as TenorBucket
  if (!TENOR_BUCKETS.includes(bucket)) {
    throw new BadRequest(`bucket must be one of ${TENOR_BUCKETS.join(', ')}`)
  }
  return bucket
}

export function bucketSql(): string {
  return `
    SELECT ${BUCKET_COLUMNS.join(', ')}
    FROM ${DD_LADDER}
    WHERE bucket_space = $1
      AND bucket_key   = $2
      AND venue_class  = $3
      AND series       = $4
      AND visibility_date >= $5::date
      AND ($6::date IS NULL OR visibility_date <= $6::date)
    ORDER BY visibility_date ASC
  `
}

/**
 * Every bucket, over the LAST N SESSIONS rather than all of history.
 *
 * The window is taken over DISTINCT visibility_date, not by a row LIMIT: a row
 * limit would slice mid-session and hand the heatmap a ragged final column
 * where some buckets have a cell and others do not, which renders as "nothing
 * was oriented in 20-30Y today" — a claim, and a false one.
 *
 * See DEFAULT_LAST_SESSIONS for why this is bounded at all.
 */
export function standardisedSql(): string {
  return `
    WITH win AS (
      SELECT DISTINCT visibility_date
      FROM ${DD_LADDER}
      WHERE bucket_space = $1
        AND venue_class  = $2
        AND series       = $3
        AND visibility_date >= $4::date
        AND ($5::date IS NULL OR visibility_date <= $5::date)
      ORDER BY visibility_date DESC
      LIMIT $6
    )
    SELECT ${STANDARDISED_COLUMNS.join(', ')}
    FROM ${DD_LADDER}
    WHERE bucket_space = $1
      AND venue_class  = $2
      AND series       = $3
      AND visibility_date >= (SELECT min(visibility_date) FROM win)
      AND ($5::date IS NULL OR visibility_date <= $5::date)
    ORDER BY visibility_date ASC, bucket_key ASC
  `
}

/**
 * Rename the level keys to their bucket-suffixed form on the wire.
 *
 * This is the Python module's block-diagonal trick, carried across the seam: a
 * client that merged two bucket responses gets delta_dv01__5_7Y beside
 * delta_dv01__7_10Y and no aligned column to plot against each other.
 */
export function suffixLevels(
  rows: Record<string, unknown>[],
  bucket: string,
): Record<string, unknown>[] {
  const s = slug(bucket)
  return rows.map((row) => {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(row)) {
      out[LEVEL_KEY.test(k) ? `${k}__${s}` : k] = v
    }
    return out
  })
}

/**
 * The exclusion breakdown, by DV01 share and by reason.
 *
 * Coverage is not a footnote: only ~58% of DV01 is oriented, and a ladder that
 * renders as though it were complete is a lie the reader cannot see. This is
 * what sits one click from every aggregate.
 */
export function coverageSql(byBucket: boolean): string {
  const groupCols = byBucket ? 'bucket_key, reason' : 'reason'
  return `
    WITH scoped AS (
      SELECT bucket_key, reason, n_units, dv01
      FROM ${DD_COVERAGE}
      WHERE venue_class = $1
        AND series      = $2
        AND visibility_date >= $3::date
        AND ($4::date IS NULL OR visibility_date <= $4::date)
        AND ($5::text IS NULL OR bucket_key = $5::text)
    ), agg AS (
      SELECT ${groupCols},
             SUM(n_units)::bigint AS n_units,
             SUM(dv01)            AS dv01
      FROM scoped
      GROUP BY ${groupCols}
    )
    SELECT ${groupCols}, n_units, dv01,
           dv01 / NULLIF(SUM(dv01) OVER (${byBucket ? 'PARTITION BY bucket_key' : ''}), 0)
             AS dv01_share,
           (reason = '${DD_IN_LADDER}') AS in_ladder
    FROM agg
    ORDER BY ${byBucket ? 'bucket_key, ' : ''}dv01 DESC
  `
}

/**
 * Headline numbers for the panel header: window, coverage, unit counts.
 *
 * THE COVERAGE COMES FROM THE COVERAGE TABLE, NOT FROM THE LADDER.
 *
 * The obvious implementation sums `coverage_dv01_kept / coverage_dv01_total`
 * over `arbs_dd_ladder_v1`, and it is wrong in the direction that flatters.
 * A ladder cell only exists where at least one unit was oriented, so
 * averaging coverage over ladder cells conditions on the very thing being
 * measured: every bucket-day whose units were *all* excluded contributes its
 * whole DV01 to the true denominator and nothing at all to that average.
 *
 * Measured on the 2024-07-01..2024-08-09 window, D2C / FLOW:
 *
 *     over ladder cells        67.0%     <- the flattering one
 *     over the coverage table  44.8%     <- the complete partition
 *
 * A 22-point overstatement, on the single number whose whole job is to stop
 * the panel reading as though it were complete. `arbs_dd_coverage_v1` is a
 * partition by construction -- every unit lands in exactly one reason -- so
 * it is the only correct source.
 */
export function summarySql(): string {
  return `
    WITH bounds AS (
      SELECT max(visibility_date) AS last_day, min(visibility_date) AS first_day
      FROM ${DD_LADDER}
      WHERE bucket_space = '${BUCKET_SPACE}'
    ), cov AS (
      SELECT SUM(dv01) FILTER (WHERE reason = '${DD_IN_LADDER}') AS kept,
             SUM(dv01)                                           AS total
      FROM ${DD_COVERAGE}
      WHERE venue_class = $1 AND series = $2
    ), units AS (
      SELECT count(*)::bigint AS n_units,
             count(*) FILTER (WHERE exclusion_reason IS NULL)::bigint AS n_called,
             max(as_of_date) AS last_as_of,
             max(code_vintage) AS code_vintage,
             max(tape_generation) AS tape_generation
      FROM ${DD_UNIT}
    )
    SELECT bounds.first_day, bounds.last_day,
           cov.kept, cov.total,
           cov.kept / NULLIF(cov.total, 0) AS coverage_frac,
           units.n_units, units.n_called, units.last_as_of,
           units.code_vintage, units.tape_generation
    FROM bounds, cov, units
  `
}
