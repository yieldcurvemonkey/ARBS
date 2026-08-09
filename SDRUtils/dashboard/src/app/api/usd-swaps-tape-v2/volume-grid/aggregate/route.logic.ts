import {
  buildPackageTypeFilter,
  resolveTenorSchema,
  buildBucketCaseSql,
  PACKAGE_TYPE_GROUP_IDS,
  type PackageTypeGroupId,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import {
  PLATFORM_CASE_SQL,
  buildPkgFamilySql,
  computePercentile,
  num,
} from '@/lib/usd-swaps-tape-v2/volumeGridSqlLib'
import {
  computeWindowBounds,
  timeOfDayInEt,
  type WindowBounds,
} from '../route.logic'
import type { VolumeMetric, VolumePeriod } from '@/features/usd-swaps-tape-v2/types/volume-grid.types'
import type {
  AggregateDailyPoint,
  AggregateDistributionEntry,
  AggregateSummary,
  AggregateVolumeResponse,
  StructureProjectionEntry,
} from '@/features/usd-swaps-tape-v2/types/aggregate-volume.types'
import {
  shapeIntradaySeasonalityResponse,
  type RawIntradaySeasonalityRow,
} from '../cell/route.logic'
import { TAPE_LEGS, TAPE_PACKAGES } from '@/lib/tape-tables'

export { computeWindowBounds }

// ---------------------------------------------------------------------------
// Parameter parsing
// ---------------------------------------------------------------------------

const VALID_METRICS: ReadonlySet<VolumeMetric> = new Set(['notional', 'dv01'])
const VALID_PERIODS: ReadonlySet<VolumePeriod> = new Set([
  'today', '1h', '24h', '1w', '2w', '3w', '1m', '3m',
])
const VALID_PACKAGE_GROUPS: ReadonlySet<PackageTypeGroupId> = new Set(PACKAGE_TYPE_GROUP_IDS)

export interface AggregateParams {
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  packageType: PackageTypeGroupId
  textFilter?: string
}

export type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string }

export function parseAggregateParams(search: URLSearchParams): ParseResult<AggregateParams> {
  const metricRaw = (search.get('metric') ?? 'dv01').toLowerCase()
  const periodRaw = (search.get('period') ?? 'today').toLowerCase()
  const packageTypeRaw = (search.get('packageType') ?? 'all').toLowerCase()
  const lookbackRaw = search.get('lookbackDays')

  if (!VALID_METRICS.has(metricRaw as VolumeMetric))
    return { ok: false, error: `metric must be one of ${[...VALID_METRICS].join(', ')}` }
  if (!VALID_PERIODS.has(periodRaw as VolumePeriod))
    return { ok: false, error: `period must be one of ${[...VALID_PERIODS].join(', ')}` }
  if (!VALID_PACKAGE_GROUPS.has(packageTypeRaw as PackageTypeGroupId))
    return { ok: false, error: `packageType must be one of ${PACKAGE_TYPE_GROUP_IDS.join(', ')}` }

  let lookbackDays = 90
  if (lookbackRaw != null) {
    const n = Number(lookbackRaw)
    if (!Number.isFinite(n) || n < 1 || n > 730)
      return { ok: false, error: 'lookbackDays must be 1..730' }
    lookbackDays = Math.floor(n)
  }

  return {
    ok: true,
    value: {
      metric: metricRaw as VolumeMetric,
      period: periodRaw as VolumePeriod,
      lookbackDays,
      packageType: packageTypeRaw as PackageTypeGroupId,
      textFilter: search.get('textFilter') ?? undefined,
    },
  }
}

// ---------------------------------------------------------------------------
// SQL helpers
// ---------------------------------------------------------------------------

interface BuiltSql {
  sql: string
  params: Array<string | number>
}

const ONE_DAY_MS = 24 * 60 * 60 * 1000

function buildTextFilterClause(
  params: Array<string | number>,
  textFilter?: string,
): string {
  if (!textFilter) return ''
  const idx = params.length + 1
  params.push(textFilter)
  return `AND (l.tape_label ILIKE '%' || $${idx}::text || '%' OR p.tape_label ILIKE '%' || $${idx}::text || '%')`
}

// ---------------------------------------------------------------------------
// Query 1: Daily timeseries
// ---------------------------------------------------------------------------

export function buildDailyTimeseriesSql(opts: {
  metric: VolumeMetric
  lookbackDays: number
  packageType: PackageTypeGroupId
  textFilter?: string
  now: Date
}): BuiltSql {
  const metricCol = opts.metric === 'notional' ? 'gross_notional' : 'gross_dv01'
  const lookbackStart = new Date(opts.now.getTime() - opts.lookbackDays * ONE_DAY_MS)
  const pkgFilter = buildPackageTypeFilter(opts.packageType, 'p', 3)
  const params: Array<string | number> = [
    lookbackStart.toISOString(),
    opts.now.toISOString(),
    ...pkgFilter.params,
  ]
  const textFilterClause = buildTextFilterClause(params, opts.textFilter)

  const sql = `
    WITH legs AS (
      SELECT
        COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
        ABS(COALESCE(l.notional, 0)) AS gross_notional,
        ABS(COALESCE(l.risk, 0))     AS gross_dv01,
        ${PLATFORM_CASE_SQL} AS platform,
        ${buildPkgFamilySql('p')} AS pkg_family,
        l.tenor_years,
        p.is_block_any,
        (date_trunc('day', COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York'))::date AS day_et
      FROM ${TAPE_LEGS} l
      JOIN ${TAPE_PACKAGES} p ON p.package_id = l.package_id
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) <  $2::timestamptz
        AND ${pkgFilter.sql}
        ${textFilterClause}
    )
    SELECT
      day_et AS day,
      SUM(${metricCol}) AS total,
      COALESCE(SUM(${metricCol}) FILTER (WHERE platform = 'IDB'), 0) AS idb,
      COALESCE(SUM(${metricCol}) FILTER (WHERE platform = 'CUSTY'), 0) AS custy,
      COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'outright'), 0) AS outright,
      COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'curve'), 0) AS curve,
      COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'fly'), 0) AS fly,
      COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'invoice'), 0) AS invoice,
      COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'other'), 0) AS other_pkg,
      COUNT(*)::int AS trade_count,
      CASE WHEN COUNT(*) > 0 THEN SUM(${metricCol}) / COUNT(*) ELSE 0 END AS avg_trade_size,
      COUNT(*) FILTER (WHERE is_block_any = TRUE)::int AS block_count,
      COALESCE(SUM(${metricCol}) FILTER (WHERE is_block_any = TRUE), 0) AS block_volume,
      CASE WHEN SUM(gross_dv01) > 0
        THEN SUM(gross_dv01 * COALESCE(tenor_years, 0)) / SUM(gross_dv01)
        ELSE 0
      END AS weighted_avg_tenor
    FROM legs
    GROUP BY day_et
    ORDER BY day_et ASC
  `
  return { sql, params }
}

// ---------------------------------------------------------------------------
// Query 2: Summary with percentile + composition breakdowns
// ---------------------------------------------------------------------------

export function buildSummarySql(opts: {
  metric: VolumeMetric
  bounds: WindowBounds
  packageType: PackageTypeGroupId
  textFilter?: string
}): BuiltSql {
  return opts.bounds.kind === 'time_of_day'
    ? buildSummaryTimeOfDaySql(opts)
    : buildSummaryRollingSql(opts)
}

function buildSummaryTimeOfDaySql(opts: {
  metric: VolumeMetric
  bounds: WindowBounds
  packageType: PackageTypeGroupId
  textFilter?: string
}): BuiltSql {
  if (opts.bounds.kind !== 'time_of_day') throw new Error('expected time_of_day bounds')
  const metricCol = opts.metric === 'notional' ? 'gross_notional' : 'gross_dv01'
  const pkgFilter = buildPackageTypeFilter(opts.packageType, 'p', 6)
  const params: Array<string | number> = [
    opts.bounds.lookbackStart.toISOString(),
    opts.bounds.lookbackEnd.toISOString(),
    opts.bounds.todayDateEt,
    opts.bounds.todSecondsLo,
    opts.bounds.todSecondsHi,
    ...pkgFilter.params,
  ]
  const textFilterClause = buildTextFilterClause(params, opts.textFilter)

  const sql = `
    WITH legs AS (
      SELECT
        ABS(COALESCE(l.notional, 0)) AS gross_notional,
        ABS(COALESCE(l.risk, 0))     AS gross_dv01,
        ${PLATFORM_CASE_SQL} AS platform,
        ${buildPkgFamilySql('p')} AS pkg_family,
        l.tenor_years,
        p.is_block_any,
        (date_trunc('day', COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York'))::date AS day_et,
        EXTRACT(EPOCH FROM (
          (COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York')
          - date_trunc('day', COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York')
        )) AS tod_seconds_et
      FROM ${TAPE_LEGS} l
      JOIN ${TAPE_PACKAGES} p ON p.package_id = l.package_id
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) <  $2::timestamptz
        AND ${pkgFilter.sql}
        ${textFilterClause}
    ),
    filtered AS (
      SELECT * FROM legs
      WHERE tod_seconds_et >= $4::numeric AND tod_seconds_et <= $5::numeric
    ),
    prior_per_day AS (
      SELECT day_et,
        SUM(${metricCol}) AS val, COUNT(*)::int AS cnt,
        COALESCE(SUM(${metricCol}) FILTER (WHERE platform = 'IDB'), 0) AS idb,
        COALESCE(SUM(${metricCol}) FILTER (WHERE platform = 'CUSTY'), 0) AS custy,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'outright'), 0) AS outright,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'curve'), 0) AS curve,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'fly'), 0) AS fly,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'invoice'), 0) AS invoice,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'other'), 0) AS other_pkg
      FROM filtered WHERE day_et < $3::date GROUP BY day_et
    ),
    current_agg AS (
      SELECT
        COALESCE(SUM(${metricCol}), 0) AS val, COUNT(*)::int AS cnt,
        COALESCE(SUM(${metricCol}) FILTER (WHERE platform = 'IDB'), 0) AS idb,
        COALESCE(SUM(${metricCol}) FILTER (WHERE platform = 'CUSTY'), 0) AS custy,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'outright'), 0) AS outright,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'curve'), 0) AS curve,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'fly'), 0) AS fly,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'invoice'), 0) AS invoice,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'other'), 0) AS other_pkg,
        COUNT(*) FILTER (WHERE is_block_any = TRUE)::int AS block_count,
        COALESCE(SUM(${metricCol}) FILTER (WHERE is_block_any = TRUE), 0) AS block_volume,
        CASE WHEN SUM(gross_dv01) > 0
          THEN SUM(gross_dv01 * COALESCE(tenor_years, 0)) / SUM(gross_dv01)
          ELSE 0
        END AS weighted_avg_tenor
      FROM filtered WHERE day_et = $3::date
    )
    SELECT
      c.val AS current_total, c.cnt AS trade_count,
      c.idb AS current_idb, c.custy AS current_custy,
      c.outright AS current_outright, c.curve AS current_curve,
      c.fly AS current_fly, c.invoice AS current_invoice, c.other_pkg AS current_other,
      c.block_count, c.block_volume, c.weighted_avg_tenor,
      COALESCE((SELECT array_agg(val ORDER BY val) FROM prior_per_day), ARRAY[]::numeric[]) AS prior_totals,
      COALESCE((SELECT array_agg(cnt ORDER BY cnt) FROM prior_per_day), ARRAY[]::int[]) AS prior_trade_counts,
      COALESCE((SELECT AVG(val) FROM prior_per_day), 0) AS adv,
      COALESCE((SELECT AVG(idb) FROM prior_per_day), 0) AS hist_idb,
      COALESCE((SELECT AVG(custy) FROM prior_per_day), 0) AS hist_custy,
      COALESCE((SELECT AVG(outright) FROM prior_per_day), 0) AS hist_outright,
      COALESCE((SELECT AVG(curve) FROM prior_per_day), 0) AS hist_curve,
      COALESCE((SELECT AVG(fly) FROM prior_per_day), 0) AS hist_fly,
      COALESCE((SELECT AVG(invoice) FROM prior_per_day), 0) AS hist_invoice,
      COALESCE((SELECT AVG(other_pkg) FROM prior_per_day), 0) AS hist_other
    FROM current_agg c
  `
  return { sql, params }
}

function buildSummaryRollingSql(opts: {
  metric: VolumeMetric
  bounds: WindowBounds
  packageType: PackageTypeGroupId
  textFilter?: string
}): BuiltSql {
  if (opts.bounds.kind !== 'rolling') throw new Error('expected rolling bounds')
  const metricCol = opts.metric === 'notional' ? 'gross_notional' : 'gross_dv01'
  const pkgFilter = buildPackageTypeFilter(opts.packageType, 'p', 4)
  const params: Array<string | number> = [
    opts.bounds.lookbackStart.toISOString(),
    opts.bounds.lookbackEnd.toISOString(),
    opts.bounds.currentStart.toISOString(),
    ...pkgFilter.params,
  ]
  const textFilterClause = buildTextFilterClause(params, opts.textFilter)

  const sql = `
    WITH legs AS (
      SELECT
        COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
        ABS(COALESCE(l.notional, 0)) AS gross_notional,
        ABS(COALESCE(l.risk, 0))     AS gross_dv01,
        ${PLATFORM_CASE_SQL} AS platform,
        ${buildPkgFamilySql('p')} AS pkg_family,
        l.tenor_years,
        p.is_block_any
      FROM ${TAPE_LEGS} l
      JOIN ${TAPE_PACKAGES} p ON p.package_id = l.package_id
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) <  $2::timestamptz
        AND ${pkgFilter.sql}
        ${textFilterClause}
    ),
    windowed AS (
      SELECT *,
        CASE WHEN ts >= $3::timestamptz THEN 'current' ELSE 'baseline' END AS window_kind,
        ${opts.bounds.windowIdSql} AS window_id
      FROM legs
    ),
    prior_per_window AS (
      SELECT window_id,
        SUM(${metricCol}) AS val, COUNT(*)::int AS cnt,
        COALESCE(SUM(${metricCol}) FILTER (WHERE platform = 'IDB'), 0) AS idb,
        COALESCE(SUM(${metricCol}) FILTER (WHERE platform = 'CUSTY'), 0) AS custy,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'outright'), 0) AS outright,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'curve'), 0) AS curve,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'fly'), 0) AS fly,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'invoice'), 0) AS invoice,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'other'), 0) AS other_pkg
      FROM windowed WHERE window_kind = 'baseline' GROUP BY window_id
    ),
    current_agg AS (
      SELECT
        COALESCE(SUM(${metricCol}), 0) AS val, COUNT(*)::int AS cnt,
        COALESCE(SUM(${metricCol}) FILTER (WHERE platform = 'IDB'), 0) AS idb,
        COALESCE(SUM(${metricCol}) FILTER (WHERE platform = 'CUSTY'), 0) AS custy,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'outright'), 0) AS outright,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'curve'), 0) AS curve,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'fly'), 0) AS fly,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'invoice'), 0) AS invoice,
        COALESCE(SUM(${metricCol}) FILTER (WHERE pkg_family = 'other'), 0) AS other_pkg,
        COUNT(*) FILTER (WHERE is_block_any = TRUE)::int AS block_count,
        COALESCE(SUM(${metricCol}) FILTER (WHERE is_block_any = TRUE), 0) AS block_volume,
        CASE WHEN SUM(gross_dv01) > 0
          THEN SUM(gross_dv01 * COALESCE(tenor_years, 0)) / SUM(gross_dv01)
          ELSE 0
        END AS weighted_avg_tenor
      FROM windowed WHERE window_kind = 'current'
    )
    SELECT
      c.val AS current_total, c.cnt AS trade_count,
      c.idb AS current_idb, c.custy AS current_custy,
      c.outright AS current_outright, c.curve AS current_curve,
      c.fly AS current_fly, c.invoice AS current_invoice, c.other_pkg AS current_other,
      c.block_count, c.block_volume, c.weighted_avg_tenor,
      COALESCE((SELECT array_agg(val ORDER BY val) FROM prior_per_window), ARRAY[]::numeric[]) AS prior_totals,
      COALESCE((SELECT array_agg(cnt ORDER BY cnt) FROM prior_per_window), ARRAY[]::int[]) AS prior_trade_counts,
      COALESCE((SELECT AVG(val) FROM prior_per_window), 0) AS adv,
      COALESCE((SELECT AVG(idb) FROM prior_per_window), 0) AS hist_idb,
      COALESCE((SELECT AVG(custy) FROM prior_per_window), 0) AS hist_custy,
      COALESCE((SELECT AVG(outright) FROM prior_per_window), 0) AS hist_outright,
      COALESCE((SELECT AVG(curve) FROM prior_per_window), 0) AS hist_curve,
      COALESCE((SELECT AVG(fly) FROM prior_per_window), 0) AS hist_fly,
      COALESCE((SELECT AVG(invoice) FROM prior_per_window), 0) AS hist_invoice,
      COALESCE((SELECT AVG(other_pkg) FROM prior_per_window), 0) AS hist_other
    FROM current_agg c
  `
  return { sql, params }
}

// ---------------------------------------------------------------------------
// Query 3: Aggregate intraday cumulative curve
// ---------------------------------------------------------------------------

export function buildAggregateIntradaySql(opts: {
  metric: VolumeMetric
  lookbackDays: number
  packageType: PackageTypeGroupId
  textFilter?: string
  now: Date
}): BuiltSql {
  const metricCol = opts.metric === 'notional' ? 'notional' : 'dv01'
  const { dateEt } = timeOfDayInEt(opts.now)
  const etDate = new Date(dateEt + 'T12:00:00')
  const dow = etDate.getUTCDay()
  let effectiveDateEt = dateEt
  if (dow === 0) {
    const fri = new Date(etDate.getTime() - 2 * ONE_DAY_MS)
    effectiveDateEt = fri.toISOString().slice(0, 10)
  } else if (dow === 6) {
    const fri = new Date(etDate.getTime() - 1 * ONE_DAY_MS)
    effectiveDateEt = fri.toISOString().slice(0, 10)
  }

  const lookbackStart = new Date(opts.now.getTime() - opts.lookbackDays * ONE_DAY_MS)
  const bucketMinutes = 1
  const pkgFilter = buildPackageTypeFilter(opts.packageType, 'p', 4)
  const params: Array<string | number> = [
    effectiveDateEt,
    lookbackStart.toISOString(),
    bucketMinutes,
    ...pkgFilter.params,
  ]
  const textFilterClause = buildTextFilterClause(params, opts.textFilter)

  const sql = `
    WITH params AS (
      SELECT $1::date AS current_day, $3::int AS bucket_minutes, (1440 / $3::int)::int AS bucket_count
    ),
    buckets AS (
      SELECT generate_series(0, (SELECT bucket_count - 1 FROM params))::int AS bucket_index
    ),
    legs AS (
      SELECT
        COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
        ABS(COALESCE(l.notional, 0)) AS notional,
        ABS(COALESCE(l.risk, 0))     AS dv01,
        date_trunc('day', COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York')::date AS day_et,
        LEAST(
          (SELECT bucket_count - 1 FROM params),
          GREATEST(0, floor(
            EXTRACT(EPOCH FROM (
              (COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York')
              - date_trunc('day', COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York')
            )) / ((SELECT bucket_minutes FROM params) * 60)
          )::int)
        ) AS bucket_index
      FROM ${TAPE_LEGS} l
      JOIN ${TAPE_PACKAGES} p ON p.package_id = l.package_id
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $2::timestamptz
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) <
          (($1::date + INTERVAL '1 day')::timestamp AT TIME ZONE 'America/New_York')
        AND ${pkgFilter.sql}
        ${textFilterClause}
    ),
    daily_bucket AS (
      SELECT day_et, bucket_index, SUM(${metricCol}) AS bucket_value FROM legs GROUP BY day_et, bucket_index
    ),
    baseline_days AS (
      SELECT DISTINCT day_et FROM daily_bucket WHERE day_et < (SELECT current_day FROM params)
    ),
    baseline_grid AS (
      SELECT d.day_et, b.bucket_index FROM baseline_days d CROSS JOIN buckets b
    ),
    baseline_cumulative AS (
      SELECT bucket_index, AVG(cumulative_value) AS average_value FROM (
        SELECT g.day_et, g.bucket_index,
          SUM(COALESCE(db.bucket_value, 0)) OVER (
            PARTITION BY g.day_et ORDER BY g.bucket_index
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          ) AS cumulative_value
        FROM baseline_grid g
        LEFT JOIN daily_bucket db ON db.day_et = g.day_et AND db.bucket_index = g.bucket_index
      ) s GROUP BY bucket_index
    ),
    current_grid AS (
      SELECT (SELECT current_day FROM params) AS day_et, b.bucket_index FROM buckets b
    ),
    current_cumulative AS (
      SELECT g.bucket_index,
        SUM(COALESCE(db.bucket_value, 0)) OVER (
          ORDER BY g.bucket_index ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS current_value
      FROM current_grid g
      LEFT JOIN daily_bucket db ON db.day_et = g.day_et AND db.bucket_index = g.bucket_index
    ),
    current_asof AS (
      SELECT MAX(ts) AS as_of_ts FROM legs WHERE day_et = (SELECT current_day FROM params)
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
  return { sql, params }
}

// ---------------------------------------------------------------------------
// Query 4: Tenor distribution
// ---------------------------------------------------------------------------

export function buildTenorDistributionSql(opts: {
  metric: VolumeMetric
  bounds: WindowBounds
  packageType: PackageTypeGroupId
  textFilter?: string
}): BuiltSql {
  return opts.bounds.kind === 'time_of_day'
    ? buildTenorDistTimeOfDaySql(opts)
    : buildTenorDistRollingSql(opts)
}

function buildTenorDistTimeOfDaySql(opts: {
  metric: VolumeMetric
  bounds: WindowBounds
  packageType: PackageTypeGroupId
  textFilter?: string
}): BuiltSql {
  if (opts.bounds.kind !== 'time_of_day') throw new Error('expected time_of_day bounds')
  const metricCol = opts.metric === 'notional' ? 'gross_notional' : 'gross_dv01'
  const tenorSchema = resolveTenorSchema('default')
  const tenorBucketExpr = buildBucketCaseSql('l', 'tenor_years', tenorSchema.buckets)
  const pkgFilter = buildPackageTypeFilter(opts.packageType, 'p', 6)
  const params: Array<string | number> = [
    opts.bounds.lookbackStart.toISOString(),
    opts.bounds.lookbackEnd.toISOString(),
    opts.bounds.todayDateEt,
    opts.bounds.todSecondsLo,
    opts.bounds.todSecondsHi,
    ...pkgFilter.params,
  ]
  const textFilterClause = buildTextFilterClause(params, opts.textFilter)

  const sql = `
    WITH legs AS (
      SELECT
        ABS(COALESCE(l.notional, 0)) AS gross_notional,
        ABS(COALESCE(l.risk, 0))     AS gross_dv01,
        ${tenorBucketExpr} AS tenor_bucket,
        (date_trunc('day', COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York'))::date AS day_et,
        EXTRACT(EPOCH FROM (
          (COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York')
          - date_trunc('day', COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York')
        )) AS tod_seconds_et
      FROM ${TAPE_LEGS} l
      JOIN ${TAPE_PACKAGES} p ON p.package_id = l.package_id
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) <  $2::timestamptz
        AND ${pkgFilter.sql}
        ${textFilterClause}
    ),
    filtered AS (
      SELECT * FROM legs
      WHERE tenor_bucket <> 'other'
        AND tod_seconds_et >= $4::numeric AND tod_seconds_et <= $5::numeric
    ),
    current_by_tenor AS (
      SELECT tenor_bucket, SUM(${metricCol}) AS val
      FROM filtered WHERE day_et = $3::date GROUP BY tenor_bucket
    ),
    prior_by_tenor AS (
      SELECT tenor_bucket, AVG(day_total) AS avg_val FROM (
        SELECT day_et, tenor_bucket, SUM(${metricCol}) AS day_total
        FROM filtered WHERE day_et < $3::date GROUP BY day_et, tenor_bucket
      ) sub GROUP BY tenor_bucket
    )
    SELECT
      COALESCE(c.tenor_bucket, p.tenor_bucket) AS tenor,
      COALESCE(c.val, 0) AS current_val,
      COALESCE(p.avg_val, 0) AS historical_avg
    FROM current_by_tenor c
    FULL OUTER JOIN prior_by_tenor p ON c.tenor_bucket = p.tenor_bucket
    ORDER BY tenor
  `
  return { sql, params }
}

function buildTenorDistRollingSql(opts: {
  metric: VolumeMetric
  bounds: WindowBounds
  packageType: PackageTypeGroupId
  textFilter?: string
}): BuiltSql {
  if (opts.bounds.kind !== 'rolling') throw new Error('expected rolling bounds')
  const metricCol = opts.metric === 'notional' ? 'gross_notional' : 'gross_dv01'
  const tenorSchema = resolveTenorSchema('default')
  const tenorBucketExpr = buildBucketCaseSql('l', 'tenor_years', tenorSchema.buckets)
  const pkgFilter = buildPackageTypeFilter(opts.packageType, 'p', 4)
  const params: Array<string | number> = [
    opts.bounds.lookbackStart.toISOString(),
    opts.bounds.lookbackEnd.toISOString(),
    opts.bounds.currentStart.toISOString(),
    ...pkgFilter.params,
  ]
  const textFilterClause = buildTextFilterClause(params, opts.textFilter)

  const sql = `
    WITH legs AS (
      SELECT
        COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
        ABS(COALESCE(l.notional, 0)) AS gross_notional,
        ABS(COALESCE(l.risk, 0))     AS gross_dv01,
        ${tenorBucketExpr} AS tenor_bucket
      FROM ${TAPE_LEGS} l
      JOIN ${TAPE_PACKAGES} p ON p.package_id = l.package_id
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) <  $2::timestamptz
        AND ${pkgFilter.sql}
        ${textFilterClause}
    ),
    filtered AS (
      SELECT *, CASE WHEN ts >= $3::timestamptz THEN 'current' ELSE 'baseline' END AS window_kind,
        ${opts.bounds.windowIdSql} AS window_id
      FROM legs WHERE tenor_bucket <> 'other'
    ),
    current_by_tenor AS (
      SELECT tenor_bucket, SUM(${metricCol}) AS val
      FROM filtered WHERE window_kind = 'current' GROUP BY tenor_bucket
    ),
    prior_by_tenor AS (
      SELECT tenor_bucket, AVG(window_total) AS avg_val FROM (
        SELECT window_id, tenor_bucket, SUM(${metricCol}) AS window_total
        FROM filtered WHERE window_kind = 'baseline' GROUP BY window_id, tenor_bucket
      ) sub GROUP BY tenor_bucket
    )
    SELECT
      COALESCE(c.tenor_bucket, p.tenor_bucket) AS tenor,
      COALESCE(c.val, 0) AS current_val,
      COALESCE(p.avg_val, 0) AS historical_avg
    FROM current_by_tenor c
    FULL OUTER JOIN prior_by_tenor p ON c.tenor_bucket = p.tenor_bucket
    ORDER BY tenor
  `
  return { sql, params }
}

// ---------------------------------------------------------------------------
// Query 5: Structure breakdown (per-structure projection table)
// ---------------------------------------------------------------------------

const STRUCTURE_TYPE_CASE = `CASE
    WHEN p.package_type = 'OUTRIGHT' THEN 'Outright'
    WHEN p.package_type IN ('SPREADOVER', 'MATCHED_MATURITY') THEN 'Spreadover'
    WHEN p.package_type = 'CURVE' THEN 'Curve'
    WHEN p.package_type IN ('SPREADOVER_CURVE', 'MATCHED_MATURITY_CURVE') THEN 'Sprd Curve'
    WHEN p.package_type = 'FLY' THEN 'Fly'
    WHEN p.package_type IN ('SPREADOVER_FLY', 'MATCHED_MATURITY_FLY') THEN 'Sprd Fly'
    ELSE 'Other'
  END`

const TENOR_LABEL_SINGLE = `CASE
    WHEN tenor_years < 1 THEN ROUND(tenor_years * 12)::int::text || 'M'
    ELSE ROUND(tenor_years)::int::text || 'Y'
  END`

const TENOR_LABEL_MULTI = `CASE
    WHEN tenor_years < 1 THEN ROUND(tenor_years * 12)::int::text || 'M'
    ELSE ROUND(tenor_years)::int::text || 's'
  END`

export function buildStructureBreakdownSql(opts: {
  metric: VolumeMetric
  lookbackDays: number
  packageType: PackageTypeGroupId
  textFilter?: string
  now: Date
}): BuiltSql {
  const metricCol = opts.metric === 'notional' ? 'gross_notional' : 'gross_dv01'
  const lookbackStart = new Date(opts.now.getTime() - opts.lookbackDays * ONE_DAY_MS)
  const { dateEt } = timeOfDayInEt(opts.now)
  const pkgFilter = buildPackageTypeFilter(opts.packageType, 'p', 4)
  const params: Array<string | number> = [
    lookbackStart.toISOString(),
    opts.now.toISOString(),
    dateEt,
    ...pkgFilter.params,
  ]
  const textFilterClause = buildTextFilterClause(params, opts.textFilter)

  const sql = `
    WITH base_legs AS (
      SELECT
        l.package_id,
        COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
        ABS(COALESCE(l.notional, 0)) AS gross_notional,
        ABS(COALESCE(l.risk, 0))     AS gross_dv01,
        l.tenor_years,
        l.platform_identifier,
        l.fixed_rate,
        p.package_transaction_spread,
        ${STRUCTURE_TYPE_CASE} AS structure_type,
        (date_trunc('day', COALESCE(l.original_execution_timestamp, l.execution_timestamp)
          AT TIME ZONE 'America/New_York'))::date AS day_et
      FROM ${TAPE_LEGS} l
      JOIN ${TAPE_PACKAGES} p ON p.package_id = l.package_id
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) <  $2::timestamptz
        AND COALESCE(l.forward_start_years, 0) < 0.0192
        AND ${pkgFilter.sql}
        ${textFilterClause}
    ),
    pkg_structure AS (
      SELECT
        package_id,
        structure_type,
        COUNT(*) AS n_tenors,
        CASE WHEN COUNT(*) = 1 THEN
          MAX(${TENOR_LABEL_SINGLE})
        ELSE
          STRING_AGG(${TENOR_LABEL_MULTI}, '' ORDER BY tenor_years)
        END AS tenor_key
      FROM (
        SELECT DISTINCT ON (package_id, ROUND(tenor_years::numeric, 0))
          package_id, structure_type, tenor_years
        FROM base_legs
        ORDER BY package_id, ROUND(tenor_years::numeric, 0), tenor_years
      ) deduped
      GROUP BY package_id, structure_type
    ),
    tagged AS (
      SELECT
        bl.*,
        ps.tenor_key || ' ' || ps.structure_type AS structure_key,
        CASE WHEN ps.n_tenors = 1 THEN bl.fixed_rate
             ELSE bl.package_transaction_spread
        END AS trade_level
      FROM base_legs bl
      JOIN pkg_structure ps USING (package_id)
    ),
    daily_struct AS (
      SELECT
        structure_key,
        day_et,
        SUM(${metricCol}) AS volume,
        COUNT(*)::int AS trade_count,
        MAX(ts) AS last_ts,
        (ARRAY_AGG(platform_identifier ORDER BY ts DESC))[1] AS latest_platform,
        (ARRAY_AGG(trade_level ORDER BY ts DESC))[1] AS last_level
      FROM tagged
      GROUP BY structure_key, day_et
    ),
    today_stats AS (
      SELECT * FROM daily_struct WHERE day_et = $3::date
    ),
    hist_avgs AS (
      SELECT
        structure_key,
        AVG(volume) FILTER (WHERE day_et >= ($3::date - 7) AND day_et < $3::date) AS adv_1w,
        AVG(volume) FILTER (WHERE day_et >= ($3::date - 30) AND day_et < $3::date) AS adv_1m
      FROM daily_struct
      WHERE day_et < $3::date
      GROUP BY structure_key
    )
    SELECT
      COALESCE(t.structure_key, h.structure_key) AS structure_key,
      COALESCE(t.volume, 0) AS today_volume,
      COALESCE(t.trade_count, 0) AS today_count,
      t.last_ts AS last_trade_time,
      t.latest_platform,
      t.last_level,
      COALESCE(h.adv_1w, 0) AS adv_1w,
      COALESCE(h.adv_1m, 0) AS adv_1m
    FROM today_stats t
    FULL OUTER JOIN hist_avgs h USING (structure_key)
    ORDER BY COALESCE(t.volume, 0) + COALESCE(h.adv_1m, 0) DESC
    LIMIT 100
  `
  return { sql, params }
}

// ---------------------------------------------------------------------------
// Response shaping
// ---------------------------------------------------------------------------

interface RawDailyRow {
  day: string | Date
  total: number | string
  idb: number | string
  custy: number | string
  outright: number | string
  curve: number | string
  fly: number | string
  invoice: number | string
  other_pkg: number | string
  trade_count: number | string
  avg_trade_size: number | string
  block_count: number | string
  block_volume: number | string
  weighted_avg_tenor: number | string
}

interface RawSummaryRow {
  current_total: number | string
  trade_count: number | string
  current_idb: number | string
  current_custy: number | string
  current_outright: number | string
  current_curve: number | string
  current_fly: number | string
  current_invoice: number | string
  current_other: number | string
  block_count: number | string
  block_volume: number | string
  weighted_avg_tenor: number | string
  prior_totals: Array<number | string>
  prior_trade_counts: Array<number | string>
  adv: number | string
  hist_idb: number | string
  hist_custy: number | string
  hist_outright: number | string
  hist_curve: number | string
  hist_fly: number | string
  hist_invoice: number | string
  hist_other: number | string
}

interface RawTenorDistRow {
  tenor: string
  current_val: number | string
  historical_avg: number | string
}

interface RawStructureBreakdownRow {
  structure_key: string
  today_volume: number | string
  today_count: number | string
  last_trade_time: string | Date | null
  latest_platform: string | null
  last_level: number | string | null
  adv_1w: number | string
  adv_1m: number | string
}

const TENOR_ORDER: ReadonlyArray<{ id: string; label: string }> = [
  { id: '1m_3m', label: '1M-3M' },
  { id: '6m_12m', label: '6M-12M' },
  { id: '1y_18m', label: '1Y-18M' },
  { id: '18m_2y', label: '18M-2Y' },
  { id: '2y', label: '2Y' },
  { id: '3y', label: '3Y' },
  { id: '4y', label: '4Y' },
  { id: '5y', label: '5Y' },
  { id: '6y_7y', label: '6Y-7Y' },
  { id: '8y_9y', label: '8Y-9Y' },
  { id: '10y', label: '10Y' },
  { id: '10y_12y', label: '10Y-12Y' },
  { id: '12y_15y', label: '12Y-15Y' },
  { id: '15y_20y', label: '15Y-20Y' },
  { id: '20y_25y', label: '20Y-25Y' },
  { id: '30y_plus', label: '25Y-30Y+' },
]
const TENOR_LABEL_MAP = Object.fromEntries(TENOR_ORDER.map((t) => [t.id, t.label]))
const TENOR_INDEX_MAP = Object.fromEntries(TENOR_ORDER.map((t, i) => [t.id, i]))

function makePkgMixEntry(
  id: string,
  label: string,
  current: number,
  hist: number,
  totalCurrent: number,
  totalHist: number,
): AggregateDistributionEntry {
  return {
    id, label, current, historicalAvg: hist,
    share: totalCurrent > 0 ? (current / totalCurrent) * 100 : 0,
    historicalShare: totalHist > 0 ? (hist / totalHist) * 100 : 0,
  }
}

export function shapeAggregateResponse(
  dailyRows: ReadonlyArray<RawDailyRow>,
  summaryRows: ReadonlyArray<RawSummaryRow>,
  intradayRows: ReadonlyArray<RawIntradaySeasonalityRow>,
  tenorDistRows: ReadonlyArray<RawTenorDistRow>,
  structureRows: ReadonlyArray<RawStructureBreakdownRow>,
  params: AggregateParams,
): AggregateVolumeResponse {
  const dailySeries: AggregateDailyPoint[] = dailyRows.map((r) => ({
    day: r.day instanceof Date ? r.day.toISOString().slice(0, 10) : String(r.day),
    total: num(r.total),
    idb: num(r.idb),
    custy: num(r.custy),
    outright: num(r.outright),
    curve: num(r.curve),
    fly: num(r.fly),
    invoice: num(r.invoice),
    other: num(r.other_pkg),
    tradeCount: num(r.trade_count),
    avgTradeSize: num(r.avg_trade_size),
    blockCount: num(r.block_count),
    blockVolume: num(r.block_volume),
    weightedAvgTenor: num(r.weighted_avg_tenor),
  }))

  const s = summaryRows[0]
  const currentTotal = s ? num(s.current_total) : 0
  const tradeCount = s ? num(s.trade_count) : 0
  const priorTotals = s ? s.prior_totals.map(num) : []
  const priorTradeCounts = s ? s.prior_trade_counts.map(num) : []
  const adv = s ? num(s.adv) : 0

  const summary: AggregateSummary = {
    currentTotal,
    percentileRank: computePercentile(currentTotal, priorTotals),
    adv,
    currentVsAdv: adv > 0 ? currentTotal / adv : 0,
    tradeCount,
    tradeCountPercentile: computePercentile(tradeCount, priorTradeCounts),
    blockCount: s ? num(s.block_count) : 0,
    blockVolume: s ? num(s.block_volume) : 0,
    weightedAvgTenor: s ? num(s.weighted_avg_tenor) : 0,
  }

  const intradayCurve = shapeIntradaySeasonalityResponse(intradayRows)

  const tenorDistribution: AggregateDistributionEntry[] = tenorDistRows
    .filter((r) => r.tenor && r.tenor !== 'other')
    .map((r) => {
      const current = num(r.current_val)
      const hist = num(r.historical_avg)
      return {
        id: r.tenor,
        label: TENOR_LABEL_MAP[r.tenor] ?? r.tenor,
        current,
        historicalAvg: hist,
        share: currentTotal > 0 ? (current / currentTotal) * 100 : 0,
        historicalShare: adv > 0 ? (hist / adv) * 100 : 0,
      }
    })
    .sort((a, b) => (TENOR_INDEX_MAP[a.id] ?? 99) - (TENOR_INDEX_MAP[b.id] ?? 99))

  const cOutright = s ? num(s.current_outright) : 0
  const cCurve = s ? num(s.current_curve) : 0
  const cFly = s ? num(s.current_fly) : 0
  const cInvoice = s ? num(s.current_invoice) : 0
  const cOther = s ? num(s.current_other) : 0
  const hOutright = s ? num(s.hist_outright) : 0
  const hCurve = s ? num(s.hist_curve) : 0
  const hFly = s ? num(s.hist_fly) : 0
  const hInvoice = s ? num(s.hist_invoice) : 0
  const hOther = s ? num(s.hist_other) : 0
  const totalHist = hOutright + hCurve + hFly + hInvoice + hOther

  const packageMix: AggregateDistributionEntry[] = [
    makePkgMixEntry('outright', 'Outright', cOutright, hOutright, currentTotal, totalHist),
    makePkgMixEntry('curve', 'Curve', cCurve, hCurve, currentTotal, totalHist),
    makePkgMixEntry('fly', 'Fly', cFly, hFly, currentTotal, totalHist),
    makePkgMixEntry('invoice', 'Invoice', cInvoice, hInvoice, currentTotal, totalHist),
    makePkgMixEntry('other', 'Other', cOther, hOther, currentTotal, totalHist),
  ]

  const cIdb = s ? num(s.current_idb) : 0
  const cCusty = s ? num(s.current_custy) : 0
  const hIdb = s ? num(s.hist_idb) : 0
  const hCusty = s ? num(s.hist_custy) : 0
  const totalVenueHist = hIdb + hCusty
  const venueSplit = {
    idb: makePkgMixEntry('idb', 'IDB (D2D)', cIdb, hIdb, currentTotal, totalVenueHist),
    custy: makePkgMixEntry('custy', 'CUSTY (D2C)', cCusty, hCusty, currentTotal, totalVenueHist),
  }

  const structureProjection: StructureProjectionEntry[] = structureRows.map((r) => {
    const lt = r.last_trade_time
    let lastTradeTime: string | null = null
    if (lt != null) {
      lastTradeTime = lt instanceof Date ? lt.toISOString() : String(lt)
    }
    return {
      structureKey: r.structure_key,
      todayVolume: num(r.today_volume),
      todayCount: num(r.today_count),
      lastTradeTime,
      latestPlatform: r.latest_platform ?? null,
      lastLevel: r.last_level != null ? num(r.last_level) : null,
      adv1w: num(r.adv_1w),
      adv1m: num(r.adv_1m),
    }
  })

  const asOf = new Date().toISOString()

  return {
    asOf,
    metric: params.metric,
    period: params.period,
    lookbackDays: params.lookbackDays,
    packageType: params.packageType,
    dailySeries,
    summary,
    intradayCurve,
    tenorDistribution,
    packageMix,
    venueSplit,
    structureProjection,
  }
}
