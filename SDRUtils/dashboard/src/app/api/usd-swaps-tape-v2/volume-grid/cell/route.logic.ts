// ABOUTME: Pure helpers for /volume-grid/cell. SQL templates take the
// parameter-binding indices as a starting offset so callers thread their
// own bind list cleanly.

import {
  buildBucketPredicate,
  buildPackageTypeFilter,
  FORWARD_SCHEMA_IDS,
  PACKAGE_TYPE_GROUP_IDS,
  resolveForwardSchema,
  resolveTenorSchema,
  TENOR_SCHEMA_IDS,
  type BucketDef,
  type ForwardSchemaId,
  type PackageTypeGroupId,
  type TenorSchemaId,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import type {
  VolumeCellRange,
  VolumeGridIntradaySeasonality,
  VolumeMetric,
} from '@/features/usd-swaps-tape-v2/types/volume-grid.types'

export interface VolumeGridCellParams {
  fwd: string
  tenor?: string
  metric: VolumeMetric
  range: VolumeCellRange
  recentLimit: number
  forwardSchema: ForwardSchemaId
  tenorSchema: TenorSchemaId
  packageType: PackageTypeGroupId
  textFilter?: string
  customForwardBuckets?: BucketDef[]
  customTenorBuckets?: BucketDef[]
}

export type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string }

const VALID_METRICS: ReadonlySet<VolumeMetric> = new Set(['notional', 'dv01'])
const VALID_RANGES: ReadonlySet<VolumeCellRange> = new Set(['1M', '3M', '6M', '1Y'])
const VALID_FORWARD_SCHEMAS: ReadonlySet<ForwardSchemaId> = new Set(FORWARD_SCHEMA_IDS)
const VALID_TENOR_SCHEMAS: ReadonlySet<TenorSchemaId> = new Set(TENOR_SCHEMA_IDS)
const VALID_PACKAGE_GROUPS: ReadonlySet<PackageTypeGroupId> = new Set(PACKAGE_TYPE_GROUP_IDS)
export const INTRADAY_SEASONALITY_BUCKET_MINUTES = 1
const MINUTES_PER_DAY = 24 * 60

export function parseVolumeGridCellParams(
  search: URLSearchParams,
  now: Date = new Date(),
): ParseResult<VolumeGridCellParams> {
  const fwd = search.get('fwd')
  const tenor = search.get('tenor') ?? undefined
  if (!fwd) return { ok: false, error: 'fwd is required' }
  const forwardSchemaRaw = (search.get('forwardSchema') ?? 'default').toLowerCase()
  if (!tenor && forwardSchemaRaw !== 'fomc') {
    return { ok: false, error: 'tenor is required when forwardSchema is not fomc' }
  }
  const textFilter = search.get('textFilter') ?? undefined
  const tenorSchemaRaw = (search.get('tenorSchema') ?? 'default').toLowerCase()
  const packageTypeRaw = (search.get('packageType') ?? 'outright').toLowerCase()
  if (!VALID_FORWARD_SCHEMAS.has(forwardSchemaRaw as ForwardSchemaId)) {
    return { ok: false, error: `forwardSchema must be one of ${FORWARD_SCHEMA_IDS.join(', ')}` }
  }
  if (!VALID_TENOR_SCHEMAS.has(tenorSchemaRaw as TenorSchemaId)) {
    return { ok: false, error: `tenorSchema must be one of ${TENOR_SCHEMA_IDS.join(', ')}` }
  }
  if (!VALID_PACKAGE_GROUPS.has(packageTypeRaw as PackageTypeGroupId)) {
    return { ok: false, error: `packageType must be one of ${PACKAGE_TYPE_GROUP_IDS.join(', ')}` }
  }
  const forwardSchema = resolveForwardSchema(forwardSchemaRaw as ForwardSchemaId, now)
  const tenorSchema = resolveTenorSchema(tenorSchemaRaw as TenorSchemaId)

  // Custom bucket parsing
  let customForwardBuckets: BucketDef[] | undefined
  if (forwardSchemaRaw === 'custom') {
    const raw = search.get('forwardBuckets')
    if (!raw) return { ok: false, error: 'forwardBuckets JSON is required when forwardSchema=custom' }
    try {
      const parsedBuckets = JSON.parse(raw)
      if (!Array.isArray(parsedBuckets) || parsedBuckets.length === 0) {
        return { ok: false, error: 'forwardBuckets must be a non-empty JSON array' }
      }
      customForwardBuckets = parsedBuckets as BucketDef[]
      // Override resolved schema's empty buckets so fwd validation below works
      ;(forwardSchema as { buckets: ReadonlyArray<BucketDef> }).buckets = customForwardBuckets
    } catch {
      return { ok: false, error: 'forwardBuckets must be valid JSON' }
    }
  }

  let customTenorBuckets: BucketDef[] | undefined
  if (tenorSchemaRaw === 'custom') {
    const raw = search.get('tenorBuckets')
    if (!raw) return { ok: false, error: 'tenorBuckets JSON is required when tenorSchema=custom' }
    try {
      const parsedBuckets = JSON.parse(raw)
      if (!Array.isArray(parsedBuckets) || parsedBuckets.length === 0) {
        return { ok: false, error: 'tenorBuckets must be a non-empty JSON array' }
      }
      customTenorBuckets = parsedBuckets as BucketDef[]
      // Override resolved schema's empty buckets so tenor validation below works
      ;(tenorSchema as { buckets: ReadonlyArray<BucketDef> }).buckets = customTenorBuckets
    } catch {
      return { ok: false, error: 'tenorBuckets must be valid JSON' }
    }
  }

  // Years-kind schemas have a fixed bucket list; fomc-label schemas
  // accept any string matching the SDR fomc_meeting_label format.
  if (forwardSchema.kind === 'fomc_label') {
    if (!/^[A-Z]{3}\d{2}$/.test(fwd)) {
      return { ok: false, error: `fwd must be a FOMC meeting label like 'APR26' (got ${fwd})` }
    }
  } else if (!forwardSchema.buckets.some((b) => b.id === fwd)) {
    return { ok: false, error: `unknown fwd: ${fwd} (schema=${forwardSchema.id})` }
  }
  if (tenor != null) {
    if (tenorSchema.kind === 'venue') {
      // Venue MIC codes are 3-5 uppercase alphanumerics in the SDR feed.
      if (!/^[A-Z0-9]{3,5}$/.test(tenor)) {
        return { ok: false, error: `tenor must be a venue MIC like 'BBSF' (got ${tenor})` }
      }
    } else if (!tenorSchema.buckets.some((b) => b.id === tenor)) {
      return { ok: false, error: `unknown tenor: ${tenor} (schema=${tenorSchema.id})` }
    }
  }
  const metric = (search.get('metric') ?? 'notional').toLowerCase() as VolumeMetric
  if (!VALID_METRICS.has(metric)) return { ok: false, error: `unknown metric: ${metric}` }
  const range = (search.get('range') ?? '3M').toUpperCase() as VolumeCellRange
  if (!VALID_RANGES.has(range)) return { ok: false, error: `unknown range: ${range}` }
  const recentRaw = search.get('recentLimit')
  let recentLimit = 50
  if (recentRaw != null) {
    const n = Number(recentRaw)
    if (!Number.isFinite(n) || n < 1 || n > 200) {
      return { ok: false, error: 'recentLimit must be 1..200' }
    }
    recentLimit = Math.floor(n)
  }
  return {
    ok: true,
    value: {
      fwd,
      tenor,
      metric,
      range,
      recentLimit,
      forwardSchema: forwardSchemaRaw as ForwardSchemaId,
      tenorSchema: tenorSchemaRaw as TenorSchemaId,
      packageType: packageTypeRaw as PackageTypeGroupId,
      textFilter,
      customForwardBuckets,
      customTenorBuckets,
    },
  }
}

export function rangeToStartDate(range: VolumeCellRange, now: Date = new Date()): Date {
  const out = new Date(now)
  switch (range) {
    case '1M': out.setUTCMonth(out.getUTCMonth() - 1); return out
    case '3M': out.setUTCMonth(out.getUTCMonth() - 3); return out
    case '6M': out.setUTCMonth(out.getUTCMonth() - 6); return out
    case '1Y': out.setUTCFullYear(out.getUTCFullYear() - 1); return out
  }
}

export function easternDateKey(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now)
  const get = (type: string): string => parts.find((p) => p.type === type)?.value ?? '00'
  return `${get('year')}-${get('month')}-${get('day')}`
}

function easternMinuteOfDay(value: Date | string | null | undefined): number | null {
  if (!value) return null
  const date = value instanceof Date ? value : new Date(String(value))
  if (Number.isNaN(date.getTime())) return null
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date)
  const hour = Number(parts.find((p) => p.type === 'hour')?.value ?? 0) % 24
  const minute = Number(parts.find((p) => p.type === 'minute')?.value ?? 0)
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return null
  return hour * 60 + minute
}

function formatMinuteLabel(minuteOfDay: number): string {
  const clamped = Math.max(0, Math.min(MINUTES_PER_DAY, Math.floor(minuteOfDay)))
  if (clamped >= MINUTES_PER_DAY) return '24:00'
  const hours = Math.floor(clamped / 60)
  const minutes = clamped % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

/**
 * Build the timeseries SQL. Bind layout:
 *   $1            = range_start timestamptz
 *   $2..(n+1)     = bucket predicate params
 *   $(n+2)..(n+1+m) = package_type filter params
 */
export function buildTimeseriesSql(opts: {
  bucketPredicateSql: string
  packageFilterSql: string
  schemaExtraFilterSql?: string
  textFilterSql?: string
}): string {
  const extraFilter = opts.schemaExtraFilterSql ? `AND ${opts.schemaExtraFilterSql}` : ''
  const textFilter = opts.textFilterSql ? `AND ${opts.textFilterSql}` : ''
  return `
    WITH legs AS (
      SELECT
        COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
        ABS(COALESCE(l.notional, 0)) AS notional,
        ABS(COALESCE(l.risk, 0))     AS dv01,
        l.venue
      FROM arbs_usd_swap_tape_legs_v2 l
      JOIN arbs_usd_swap_tape_packages_v2 p ON p.package_id = l.package_id
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND ${opts.bucketPredicateSql}
        AND ${opts.packageFilterSql}
        ${extraFilter}
        ${textFilter}
    )
    SELECT
      date_trunc('day', ts AT TIME ZONE 'America/New_York')::date AS day,
      SUM(notional) AS notional,
      SUM(dv01)     AS dv01,
      COUNT(*)::int AS trade_count,
      COUNT(*) FILTER (WHERE venue = 'D2D')::int AS idb_count,
      COUNT(*) FILTER (WHERE venue <> 'D2D' OR venue IS NULL)::int AS custy_count
    FROM legs
    GROUP BY day
    ORDER BY day ASC
  `
}

export function buildIntradaySeasonalitySql(opts: {
  metric: VolumeMetric
  bucketPredicateSql: string
  packageFilterSql: string
  schemaExtraFilterSql?: string
  textFilterSql?: string
}): string {
  const metricCol = opts.metric === 'notional' ? 'notional' : 'dv01'
  const extraFilter = opts.schemaExtraFilterSql ? `AND ${opts.schemaExtraFilterSql}` : ''
  const textFilter = opts.textFilterSql ? `AND ${opts.textFilterSql}` : ''
  return `
    WITH params AS (
      SELECT
        $1::date AS current_day,
        $3::int AS bucket_minutes,
        (1440 / $3::int)::int AS bucket_count
    ),
    buckets AS (
      SELECT generate_series(0, (SELECT bucket_count - 1 FROM params))::int AS bucket_index
    ),
    legs AS (
      SELECT
        COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
        ABS(COALESCE(l.notional, 0)) AS notional,
        ABS(COALESCE(l.risk, 0))     AS dv01,
        date_trunc(
          'day',
          COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York'
        )::date AS day_et,
        LEAST(
          (SELECT bucket_count - 1 FROM params),
          GREATEST(
            0,
            floor(
              EXTRACT(EPOCH FROM (
                (
                  COALESCE(l.original_execution_timestamp, l.execution_timestamp)
                  AT TIME ZONE 'America/New_York'
                )
                - date_trunc(
                  'day',
                  COALESCE(l.original_execution_timestamp, l.execution_timestamp)
                  AT TIME ZONE 'America/New_York'
                )
              )) / ((SELECT bucket_minutes FROM params) * 60)
            )::int
          )
        ) AS bucket_index
      FROM arbs_usd_swap_tape_legs_v2 l
      JOIN arbs_usd_swap_tape_packages_v2 p ON p.package_id = l.package_id
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $2::timestamptz
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) <
          (($1::date + INTERVAL '1 day')::timestamp AT TIME ZONE 'America/New_York')
        AND ${opts.bucketPredicateSql}
        AND ${opts.packageFilterSql}
        ${extraFilter}
        ${textFilter}
    ),
    daily_bucket AS (
      SELECT day_et, bucket_index, SUM(${metricCol}) AS bucket_value
      FROM legs
      GROUP BY day_et, bucket_index
    ),
    baseline_days AS (
      SELECT DISTINCT day_et
      FROM daily_bucket
      WHERE day_et < (SELECT current_day FROM params)
    ),
    baseline_grid AS (
      SELECT d.day_et, b.bucket_index
      FROM baseline_days d
      CROSS JOIN buckets b
    ),
    baseline_cumulative AS (
      SELECT bucket_index, AVG(cumulative_value) AS average_value
      FROM (
        SELECT
          g.day_et,
          g.bucket_index,
          SUM(COALESCE(db.bucket_value, 0)) OVER (
            PARTITION BY g.day_et
            ORDER BY g.bucket_index
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          ) AS cumulative_value
        FROM baseline_grid g
        LEFT JOIN daily_bucket db
          ON db.day_et = g.day_et
         AND db.bucket_index = g.bucket_index
      ) s
      GROUP BY bucket_index
    ),
    current_grid AS (
      SELECT (SELECT current_day FROM params) AS day_et, b.bucket_index
      FROM buckets b
    ),
    current_cumulative AS (
      SELECT
        g.bucket_index,
        SUM(COALESCE(db.bucket_value, 0)) OVER (
          ORDER BY g.bucket_index
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS current_value
      FROM current_grid g
      LEFT JOIN daily_bucket db
        ON db.day_et = g.day_et
       AND db.bucket_index = g.bucket_index
    ),
    current_asof AS (
      SELECT MAX(ts) AS as_of_ts
      FROM legs
      WHERE day_et = (SELECT current_day FROM params)
    )
    SELECT
      b.bucket_index,
      ((b.bucket_index + 1) * (SELECT bucket_minutes FROM params))::int AS minute_of_day,
      COALESCE(c.current_value, 0) AS current_value,
      a.average_value,
      (SELECT COUNT(*) FROM baseline_days)::int AS observed_days,
      (SELECT as_of_ts FROM current_asof) AS as_of_ts
    FROM buckets b
    LEFT JOIN current_cumulative c USING (bucket_index)
    LEFT JOIN baseline_cumulative a USING (bucket_index)
    ORDER BY b.bucket_index ASC
  `
}

export function buildRecentTradesSql(opts: {
  bucketPredicateSql: string
  packageFilterSql: string
  schemaExtraFilterSql?: string
  textFilterSql?: string
  limitParam: string
  inCellPredicateSql?: string
}): string {
  const extraFilter = opts.schemaExtraFilterSql ? `AND ${opts.schemaExtraFilterSql}` : ''
  const textFilter = opts.textFilterSql ? `AND ${opts.textFilterSql}` : ''
  const legsSubquery = opts.inCellPredicateSql
    ? `,
      (
        SELECT json_agg(json_build_object(
          'tenor_years', l2.tenor_years,
          'forward_start_years', l2.forward_start_years,
          'notional', ABS(COALESCE(l2.notional, 0)),
          'risk', ABS(COALESCE(l2.risk, 0)),
          'in_cell', CASE WHEN (${opts.inCellPredicateSql}) THEN true ELSE false END
        ) ORDER BY l2.tenor_years)
        FROM arbs_usd_swap_tape_legs_v2 l2
        WHERE l2.package_id = p.package_id
          AND COALESCE(l2.contributes_to_flow, FALSE) = TRUE
      ) AS legs`
    : ''
  return `
    WITH eligible_packages AS (
      SELECT DISTINCT l.package_id
      FROM arbs_usd_swap_tape_legs_v2 l
      JOIN arbs_usd_swap_tape_packages_v2 p ON p.package_id = l.package_id
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND ${opts.bucketPredicateSql}
        AND ${opts.packageFilterSql}
        ${extraFilter}
        ${textFilter}
    )
    SELECT
      p.package_id,
      p.execution_start,
      p.tape_label,
      p.package_type,
      p.weighted_fixed_rate,
      p.total_risk,
      p.total_notional,
      p.venue,
      p.is_block_any${legsSubquery}
    FROM arbs_usd_swap_tape_packages_v2 p
    JOIN eligible_packages e ON e.package_id = p.package_id
    ORDER BY p.execution_start DESC
    LIMIT ${opts.limitParam}
  `
}

export interface RawIntradaySeasonalityRow {
  bucket_index: number | string
  minute_of_day: number | string
  current_value: number | string | null
  average_value: number | string | null
  observed_days: number | string
  as_of_ts: string | Date | null
}

const num = (v: unknown): number => {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}

export function shapeIntradaySeasonalityResponse(
  rows: ReadonlyArray<RawIntradaySeasonalityRow>,
  bucketMinutes: number = INTRADAY_SEASONALITY_BUCKET_MINUTES,
): VolumeGridIntradaySeasonality {
  const rawAsOf = rows.find((r) => r.as_of_ts != null)?.as_of_ts ?? null
  const asOfDate =
    rawAsOf instanceof Date
      ? (Number.isNaN(rawAsOf.getTime()) ? null : rawAsOf)
      : rawAsOf == null
        ? null
        : new Date(String(rawAsOf))
  const asOf =
    asOfDate && !Number.isNaN(asOfDate.getTime()) ? asOfDate.toISOString() : null
  const asOfMinuteOfDay = asOfDate ? easternMinuteOfDay(asOfDate) : null
  const currentBucketEnd =
    asOfMinuteOfDay == null
      ? null
      : Math.min(
          MINUTES_PER_DAY,
          Math.floor(asOfMinuteOfDay / bucketMinutes) * bucketMinutes + bucketMinutes,
        )
  const observedDays = rows.reduce(
    (max, r) => Math.max(max, Math.floor(num(r.observed_days))),
    0,
  )
  const points = rows.map((r) => {
    const minuteOfDay = Math.floor(num(r.minute_of_day))
    const currentRaw = num(r.current_value)
    const averageRaw =
      r.average_value == null || r.average_value === '' ? null : num(r.average_value)
    return {
      minuteOfDay,
      time: formatMinuteLabel(minuteOfDay),
      current:
        currentBucketEnd == null || minuteOfDay > currentBucketEnd
          ? null
          : currentRaw,
      average: averageRaw,
    }
  })
  return {
    bucketMinutes,
    observedDays,
    asOf,
    asOfMinuteOfDay,
    points,
  }
}

export { buildBucketPredicate, buildPackageTypeFilter }
