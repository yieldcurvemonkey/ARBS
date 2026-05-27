// ABOUTME: Pure helpers for /api/usd-swaps-tape-v2/volume-grid. Split out
// from route.ts so SQL construction, parameter parsing, percentile math,
// and totals aggregation can be unit-tested without spinning up a DB.
//
// Two window-comparison modes:
//   - time_of_day: today vs prior days at the same time-of-day in ET
//     (used for periods 'today' and '1h').
//   - rolling: today's last 24h or 7d vs prior 24h/7d windows shifted in
//     time (used for periods '24h' and '1w').
//
// Two view modes:
//   - volume (default): single-percentile colored cell with total
//   - idb_custy: split bar showing IDB vs CUSTY share of the cell total

import {
  buildBucketCaseSql,
  buildFomcBucketsFromLabels,
  buildPackageTypeFilter,
  buildVenueBucketsFromIdentifiers,
  FORWARD_SCHEMA_IDS,
  PACKAGE_TYPE_GROUP_IDS,
  resolveForwardSchema,
  resolveTenorSchema,
  TENOR_SCHEMA_IDS,
  type BucketDef,
  type ForwardSchemaId,
  type PackageTypeGroupId,
  type ResolvedSchema,
  type TenorSchemaId,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import {
  PLATFORM_CASE_SQL,
  summariseCells,
  rowToCell,
  buildPkgFamilySql,
  type RawVolumeGridRow,
} from '@/lib/usd-swaps-tape-v2/volumeGridSqlLib'
import type {
  VolumeGridCell,
  VolumeMetric,
  VolumePeriod,
  VolumeGridResponse,
  VolumeGridViewMode,
} from '@/features/usd-swaps-tape-v2/types/volume-grid.types'

export { computePercentile, summariseCells, type RawVolumeGridRow } from '@/lib/usd-swaps-tape-v2/volumeGridSqlLib'

export interface VolumeGridParams {
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  forwardSchema: ForwardSchemaId
  tenorSchema: TenorSchemaId
  packageType: PackageTypeGroupId
  viewMode: VolumeGridViewMode
  textFilter?: string
  collapseAxis?: 'tenor' | 'forward'
  customForwardBuckets?: BucketDef[]
  customTenorBuckets?: BucketDef[]
}

export type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string }

const VALID_METRICS: ReadonlySet<VolumeMetric> = new Set(['notional', 'dv01'])
const VALID_PERIODS: ReadonlySet<VolumePeriod> = new Set([
  'today',
  '1h',
  '24h',
  '1w',
  '2w',
  '3w',
  '1m',
  '3m',
])
const VALID_FORWARD_SCHEMAS: ReadonlySet<ForwardSchemaId> = new Set(FORWARD_SCHEMA_IDS)
const VALID_TENOR_SCHEMAS: ReadonlySet<TenorSchemaId> = new Set(TENOR_SCHEMA_IDS)
const VALID_PACKAGE_GROUPS: ReadonlySet<PackageTypeGroupId> = new Set(PACKAGE_TYPE_GROUP_IDS)
const VALID_VIEW_MODES: ReadonlySet<VolumeGridViewMode> = new Set(['volume', 'idb_custy'])
const VALID_COLLAPSE_AXES: ReadonlySet<string> = new Set(['tenor', 'forward'])

export function parseVolumeGridParams(search: URLSearchParams): ParseResult<VolumeGridParams> {
  const metricRaw = (search.get('metric') ?? 'notional').toLowerCase()
  const periodRaw = (search.get('period') ?? 'today').toLowerCase()
  const forwardSchemaRaw = (search.get('forwardSchema') ?? 'default').toLowerCase()
  const tenorSchemaRaw = (search.get('tenorSchema') ?? 'default').toLowerCase()
  const packageTypeRaw = (search.get('packageType') ?? 'outright').toLowerCase()
  const viewModeRaw = (search.get('viewMode') ?? 'volume').toLowerCase()
  const lookbackRaw = search.get('lookbackDays')
  if (!VALID_METRICS.has(metricRaw as VolumeMetric)) {
    return { ok: false, error: `metric must be one of ${[...VALID_METRICS].join(', ')}` }
  }
  if (!VALID_PERIODS.has(periodRaw as VolumePeriod)) {
    return { ok: false, error: `period must be one of ${[...VALID_PERIODS].join(', ')}` }
  }
  if (!VALID_FORWARD_SCHEMAS.has(forwardSchemaRaw as ForwardSchemaId)) {
    return { ok: false, error: `forwardSchema must be one of ${FORWARD_SCHEMA_IDS.join(', ')}` }
  }
  if (!VALID_TENOR_SCHEMAS.has(tenorSchemaRaw as TenorSchemaId)) {
    return { ok: false, error: `tenorSchema must be one of ${TENOR_SCHEMA_IDS.join(', ')}` }
  }
  if (!VALID_PACKAGE_GROUPS.has(packageTypeRaw as PackageTypeGroupId)) {
    return { ok: false, error: `packageType must be one of ${PACKAGE_TYPE_GROUP_IDS.join(', ')}` }
  }
  if (!VALID_VIEW_MODES.has(viewModeRaw as VolumeGridViewMode)) {
    return { ok: false, error: `viewMode must be one of ${[...VALID_VIEW_MODES].join(', ')}` }
  }
  let lookbackDays = 90
  if (lookbackRaw != null) {
    const n = Number(lookbackRaw)
    if (!Number.isFinite(n) || n < 1 || n > 730) {
      return { ok: false, error: 'lookbackDays must be 1..730' }
    }
    lookbackDays = Math.floor(n)
  }
  const textFilter = search.get('textFilter') ?? undefined
  const collapseAxisRaw = search.get('collapseAxis') ?? undefined
  if (collapseAxisRaw != null && !VALID_COLLAPSE_AXES.has(collapseAxisRaw)) {
    return { ok: false, error: `collapseAxis must be one of ${[...VALID_COLLAPSE_AXES].join(', ')}` }
  }

  // Custom bucket parsing
  let customForwardBuckets: BucketDef[] | undefined
  if (forwardSchemaRaw === 'custom') {
    const raw = search.get('forwardBuckets')
    if (!raw) return { ok: false, error: 'forwardBuckets JSON is required when forwardSchema=custom' }
    try {
      const parsed = JSON.parse(raw)
      if (!Array.isArray(parsed) || parsed.length === 0) {
        return { ok: false, error: 'forwardBuckets must be a non-empty JSON array' }
      }
      customForwardBuckets = parsed as BucketDef[]
    } catch {
      return { ok: false, error: 'forwardBuckets must be valid JSON' }
    }
  }

  let customTenorBuckets: BucketDef[] | undefined
  if (tenorSchemaRaw === 'custom') {
    const raw = search.get('tenorBuckets')
    if (!raw) return { ok: false, error: 'tenorBuckets JSON is required when tenorSchema=custom' }
    try {
      const parsed = JSON.parse(raw)
      if (!Array.isArray(parsed) || parsed.length === 0) {
        return { ok: false, error: 'tenorBuckets must be a non-empty JSON array' }
      }
      customTenorBuckets = parsed as BucketDef[]
    } catch {
      return { ok: false, error: 'tenorBuckets must be valid JSON' }
    }
  }

  return {
    ok: true,
    value: {
      metric: metricRaw as VolumeMetric,
      period: periodRaw as VolumePeriod,
      lookbackDays,
      forwardSchema: forwardSchemaRaw as ForwardSchemaId,
      tenorSchema: tenorSchemaRaw as TenorSchemaId,
      packageType: packageTypeRaw as PackageTypeGroupId,
      viewMode: viewModeRaw as VolumeGridViewMode,
      textFilter,
      collapseAxis: collapseAxisRaw as 'tenor' | 'forward' | undefined,
      customForwardBuckets,
      customTenorBuckets,
    },
  }
}

export type WindowBounds =
  | {
      kind: 'time_of_day'
      lookbackStart: Date
      lookbackEnd: Date
      todayDateEt: string
      todSecondsLo: number
      todSecondsHi: number
    }
  | {
      kind: 'rolling'
      lookbackStart: Date
      lookbackEnd: Date
      currentStart: Date
      windowIdSql: string
    }

const ONE_HOUR_MS = 60 * 60 * 1000
const ONE_DAY_MS = 24 * ONE_HOUR_MS
const ONE_HOUR_S = 60 * 60

function rollingBounds(
  now: Date,
  lookbackDays: number,
  windowDays: number,
  windowIdSql: string,
): Extract<WindowBounds, { kind: 'rolling' }> {
  const effectiveLookbackDays = Math.max(lookbackDays, windowDays * 4)
  return {
    kind: 'rolling',
    lookbackStart: new Date(now.getTime() - effectiveLookbackDays * ONE_DAY_MS),
    lookbackEnd: now,
    currentStart: new Date(now.getTime() - windowDays * ONE_DAY_MS),
    windowIdSql,
  }
}

export function timeOfDayInEt(now: Date): { dateEt: string; todSeconds: number } {
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
  const parts = fmt.formatToParts(now)
  const get = (type: string): string => parts.find((p) => p.type === type)?.value ?? '0'
  const year = get('year')
  const month = get('month')
  const day = get('day')
  const hour = parseInt(get('hour'), 10) % 24
  const minute = parseInt(get('minute'), 10)
  const second = parseInt(get('second'), 10)
  return {
    dateEt: `${year}-${month}-${day}`,
    todSeconds: hour * 3600 + minute * 60 + second,
  }
}

export function computeWindowBounds(
  period: VolumePeriod,
  lookbackDays: number,
  now: Date = new Date(),
): WindowBounds {
  const lookbackEnd = now
  switch (period) {
    case 'today': {
      const { dateEt, todSeconds } = timeOfDayInEt(now)
      // Weekend auto-detection: if today is Saturday or Sunday in ET,
      // use the previous Friday instead (no trades on weekends).
      const etDate = new Date(dateEt + 'T12:00:00')
      const dow = etDate.getUTCDay() // 0=Sun, 6=Sat
      let effectiveDateEt = dateEt
      let effectiveTodSecondsHi = todSeconds
      if (dow === 0) { // Sunday → use Friday
        const fri = new Date(etDate.getTime() - 2 * 24 * 60 * 60 * 1000)
        effectiveDateEt = fri.toISOString().slice(0, 10)
        effectiveTodSecondsHi = 24 * 3600 // full day
      } else if (dow === 6) { // Saturday → use Friday
        const fri = new Date(etDate.getTime() - 1 * 24 * 60 * 60 * 1000)
        effectiveDateEt = fri.toISOString().slice(0, 10)
        effectiveTodSecondsHi = 24 * 3600 // full day
      }
      const lookbackStart = new Date(now.getTime() - lookbackDays * ONE_DAY_MS)
      return {
        kind: 'time_of_day', lookbackStart, lookbackEnd,
        todayDateEt: effectiveDateEt, todSecondsLo: 0, todSecondsHi: effectiveTodSecondsHi,
      }
    }
    case '1h': {
      const { dateEt, todSeconds } = timeOfDayInEt(now)
      const etDate = new Date(dateEt + 'T12:00:00')
      const dow = etDate.getUTCDay()
      if (dow === 0 || dow === 6) {
        // Weekend: fall back to full Friday
        const daysBack = dow === 0 ? 2 : 1
        const fri = new Date(etDate.getTime() - daysBack * 24 * 60 * 60 * 1000)
        const effectiveDateEt = fri.toISOString().slice(0, 10)
        const lookbackStart = new Date(now.getTime() - lookbackDays * ONE_DAY_MS)
        return {
          kind: 'time_of_day', lookbackStart, lookbackEnd,
          todayDateEt: effectiveDateEt, todSecondsLo: 0, todSecondsHi: 24 * 3600,
        }
      }
      const lookbackStart = new Date(now.getTime() - lookbackDays * ONE_DAY_MS)
      return {
        kind: 'time_of_day', lookbackStart, lookbackEnd,
        todayDateEt: dateEt,
        todSecondsLo: Math.max(0, todSeconds - ONE_HOUR_S),
        todSecondsHi: todSeconds,
      }
    }
    case '24h': {
      return rollingBounds(
        now,
        lookbackDays,
        1,
        `date_trunc('day', ts AT TIME ZONE 'America/New_York')`,
      )
    }
    case '1w': {
      // Caller's lookbackDays flows through; rollingBounds enforces a
      // 4× floor (28 days) so the percentile still sees ≥ 4 prior
      // weekly windows even if the trader picks a small lookback.
      return rollingBounds(
        now,
        lookbackDays,
        7,
        `date_trunc('week', ts AT TIME ZONE 'America/New_York')`,
      )
    }
    case '2w': {
      return rollingBounds(
        now,
        lookbackDays,
        14,
        `floor(EXTRACT(EPOCH FROM (ts - $1::timestamptz)) / ${14 * 24 * 3600})`,
      )
    }
    case '3w': {
      return rollingBounds(
        now,
        lookbackDays,
        21,
        `floor(EXTRACT(EPOCH FROM (ts - $1::timestamptz)) / ${21 * 24 * 3600})`,
      )
    }
    case '1m': {
      return rollingBounds(
        now,
        lookbackDays,
        30,
        `date_trunc('month', ts AT TIME ZONE 'America/New_York')`,
      )
    }
    case '3m': {
      return rollingBounds(
        now,
        lookbackDays,
        90,
        `date_trunc('quarter', ts AT TIME ZONE 'America/New_York')`,
      )
    }
  }
}

export interface SqlBuildContext {
  metric: VolumeMetric
  forwardSchema: ResolvedSchema
  tenorSchema: ResolvedSchema
  packageType: PackageTypeGroupId
  bounds: WindowBounds
  textFilter?: string
  collapseAxis?: 'tenor' | 'forward'
}

export interface BuiltSql {
  sql: string
  params: Array<string | number>
}

// PLATFORM_CASE_SQL imported from volumeGridSqlLib

/**
 * Build the fwd-bucket SQL expression for a forward schema. For years-
 * kind schemas this is a CASE on `forward_start_years` boundaries. For
 * fomc-label schemas it just reads `fomc_meeting_label` directly.
 */
function buildForwardBucketSql(forwardSchema: ResolvedSchema, alias: string): string {
  if (forwardSchema.kind === 'fomc_label') {
    return `${alias}.fomc_meeting_label`
  }
  return buildBucketCaseSql(alias, 'forward_start_years', forwardSchema.buckets)
}

/**
 * Build the tenor- (column-axis) bucket SQL expression. For year-range
 * schemas this is a CASE on `tenor_years`. For venue schemas it just
 * reads `platform_identifier` directly.
 */
function buildTenorBucketSql(tenorSchema: ResolvedSchema, alias: string): string {
  if (tenorSchema.kind === 'venue') {
    return `${alias}.platform_identifier`
  }
  return buildBucketCaseSql(alias, 'tenor_years', tenorSchema.buckets)
}

/**
 * Test whether a row's fwd-bucket id is "valid" for the schema. For
 * years schemas, we drop 'other'. For fomc, any non-null label is fine.
 */
function fwdBucketIsValidSqlPredicate(forwardSchema: ResolvedSchema): string {
  return forwardSchema.kind === 'fomc_label'
    ? `fwd_bucket IS NOT NULL`
    : `fwd_bucket <> 'other'`
}

function tenorBucketIsValidSqlPredicate(tenorSchema: ResolvedSchema): string {
  return tenorSchema.kind === 'venue'
    ? `tenor_bucket IS NOT NULL`
    : `tenor_bucket <> 'other'`
}

/**
 * Combine the forward + tenor schemas' optional `extraFilterSql` into a
 * single AND-joined fragment, or empty string if neither has one.
 */
function combinedExtraFilter(forwardSchema: ResolvedSchema, tenorSchema: ResolvedSchema): string {
  const parts = [forwardSchema.extraFilterSql, tenorSchema.extraFilterSql].filter(Boolean)
  return parts.length === 0 ? '' : `AND ${parts.join(' AND ')}`
}

/**
 * Build the SQL for a time-of-day comparison ('today' / '1h').
 *
 * Bind order:
 *   $1 = lookbackStart timestamptz
 *   $2 = lookbackEnd   timestamptz
 *   $3 = todayDateEt   date
 *   $4 = todSecondsLo  numeric
 *   $5 = todSecondsHi  numeric
 *   $6.. (when packageType filter active) = package_type values
 */
export function buildVolumeGridSqlTimeOfDay(ctx: SqlBuildContext): BuiltSql {
  if (ctx.bounds.kind !== 'time_of_day') throw new Error('expected time_of_day bounds')
  const fwdBucketExpr = ctx.collapseAxis === 'forward'
    ? `'_all_'`
    : buildForwardBucketSql(ctx.forwardSchema, 'l')
  const tenorBucketExpr = ctx.collapseAxis === 'tenor'
    ? `'_all_'`
    : buildTenorBucketSql(ctx.tenorSchema, 'l')
  const metricCol = ctx.metric === 'notional' ? 'gross_notional' : 'gross_dv01'
  const pkgFilter = buildPackageTypeFilter(ctx.packageType, 'p', 6)
  const extraFilter = combinedExtraFilter(ctx.forwardSchema, ctx.tenorSchema)
  const params: Array<string | number> = [
    ctx.bounds.lookbackStart.toISOString(),
    ctx.bounds.lookbackEnd.toISOString(),
    ctx.bounds.todayDateEt,
    ctx.bounds.todSecondsLo,
    ctx.bounds.todSecondsHi,
    ...pkgFilter.params,
  ]
  // textFilter comes after package type params
  let textFilterClause = ''
  if (ctx.textFilter != null) {
    const textParamIdx = params.length + 1
    params.push(ctx.textFilter)
    textFilterClause = `AND (l.tape_label ILIKE '%' || $${textParamIdx}::text || '%' OR p.tape_label ILIKE '%' || $${textParamIdx}::text || '%')`
  }
  const sql = `
    WITH legs AS (
      SELECT
        COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
        ABS(COALESCE(l.notional, 0)) AS gross_notional,
        ABS(COALESCE(l.risk, 0))     AS gross_dv01,
        ${fwdBucketExpr} AS fwd_bucket,
        ${tenorBucketExpr} AS tenor_bucket,
        ${PLATFORM_CASE_SQL} AS platform,
        ${buildPkgFamilySql('p')} AS pkg_family,
        (date_trunc('day', COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York'))::date AS day_et,
        EXTRACT(EPOCH FROM (
          (COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York')
          - date_trunc('day', COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York')
        )) AS tod_seconds_et
      FROM arbs_usd_swap_tape_legs_v2 l
      JOIN arbs_usd_swap_tape_packages_v2 p ON p.package_id = l.package_id
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) <  $2::timestamptz
        AND ${pkgFilter.sql}
        ${extraFilter}
        ${textFilterClause}
    ),
    bucketed AS (
      SELECT * FROM legs
      WHERE ${ctx.collapseAxis === 'forward' ? 'TRUE' : fwdBucketIsValidSqlPredicate(ctx.forwardSchema)}
        AND ${ctx.collapseAxis === 'tenor' ? 'TRUE' : tenorBucketIsValidSqlPredicate(ctx.tenorSchema)}
        AND tod_seconds_et >= $4::numeric
        AND tod_seconds_et <= $5::numeric
    ),
    prior_per_day AS (
      SELECT fwd_bucket, tenor_bucket, day_et,
        SUM(${metricCol}) AS window_value
      FROM bucketed
      WHERE day_et < $3::date
      GROUP BY fwd_bucket, tenor_bucket, day_et
    ),
    prior_summary AS (
      SELECT fwd_bucket, tenor_bucket,
        array_agg(window_value ORDER BY window_value) AS prior_array,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY window_value) AS p25,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY window_value) AS p50,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY window_value) AS p75,
        MIN(window_value) AS pmin,
        MAX(window_value) AS pmax,
        COUNT(*)::int AS n
      FROM prior_per_day
      GROUP BY fwd_bucket, tenor_bucket
    ),
    current_agg AS (
      SELECT fwd_bucket, tenor_bucket,
        SUM(${metricCol}) AS current_value,
        SUM(${metricCol}) FILTER (WHERE platform = 'IDB')   AS idb_current,
        SUM(${metricCol}) FILTER (WHERE platform = 'CUSTY') AS custy_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'outright') AS outright_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'curve')    AS curve_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'fly')      AS fly_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'invoice')  AS invoice_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'other')    AS other_current,
        COUNT(*)::int AS trade_count,
        MAX(ts) AS last_ts
      FROM bucketed
      WHERE day_et = $3::date
      GROUP BY fwd_bucket, tenor_bucket
    )
    SELECT
      COALESCE(c.fwd_bucket, p.fwd_bucket)     AS fwd,
      COALESCE(c.tenor_bucket, p.tenor_bucket) AS tenor,
      COALESCE(c.current_value, 0)             AS current_value,
      COALESCE(c.idb_current, 0)               AS idb_current,
      COALESCE(c.custy_current, 0)             AS custy_current,
      COALESCE(c.outright_current, 0)          AS outright_current,
      COALESCE(c.curve_current, 0)             AS curve_current,
      COALESCE(c.fly_current, 0)               AS fly_current,
      COALESCE(c.invoice_current, 0)           AS invoice_current,
      COALESCE(c.other_current, 0)             AS other_current,
      COALESCE(c.trade_count, 0)               AS trade_count,
      COALESCE(p.prior_array, ARRAY[]::numeric[]) AS prior_array,
      COALESCE(p.p25, 0)  AS p25,
      COALESCE(p.p50, 0)  AS p50,
      COALESCE(p.p75, 0)  AS p75,
      COALESCE(p.pmin, 0) AS pmin,
      COALESCE(p.pmax, 0) AS pmax,
      COALESCE(p.n, 0)    AS n,
      MAX(c.last_ts) OVER () AS as_of_ts
    FROM current_agg c
    FULL OUTER JOIN prior_summary p USING (fwd_bucket, tenor_bucket)
  `
  return { sql, params }
}

/**
 * Build the SQL for a rolling-window comparison ('24h' / '1w').
 */
export function buildVolumeGridSqlRolling(ctx: SqlBuildContext): BuiltSql {
  if (ctx.bounds.kind !== 'rolling') throw new Error('expected rolling bounds')
  const fwdBucketExpr = ctx.collapseAxis === 'forward'
    ? `'_all_'`
    : buildForwardBucketSql(ctx.forwardSchema, 'l')
  const tenorBucketExpr = ctx.collapseAxis === 'tenor'
    ? `'_all_'`
    : buildTenorBucketSql(ctx.tenorSchema, 'l')
  const metricCol = ctx.metric === 'notional' ? 'gross_notional' : 'gross_dv01'
  const pkgFilter = buildPackageTypeFilter(ctx.packageType, 'p', 4)
  const extraFilter = combinedExtraFilter(ctx.forwardSchema, ctx.tenorSchema)
  const params: Array<string | number> = [
    ctx.bounds.lookbackStart.toISOString(),
    ctx.bounds.lookbackEnd.toISOString(),
    ctx.bounds.currentStart.toISOString(),
    ...pkgFilter.params,
  ]
  // textFilter comes after package type params
  let textFilterClause = ''
  if (ctx.textFilter != null) {
    const textParamIdx = params.length + 1
    params.push(ctx.textFilter)
    textFilterClause = `AND (l.tape_label ILIKE '%' || $${textParamIdx}::text || '%' OR p.tape_label ILIKE '%' || $${textParamIdx}::text || '%')`
  }
  const sql = `
    WITH legs AS (
      SELECT
        COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
        ABS(COALESCE(l.notional, 0)) AS gross_notional,
        ABS(COALESCE(l.risk, 0))     AS gross_dv01,
        ${fwdBucketExpr} AS fwd_bucket,
        ${tenorBucketExpr} AS tenor_bucket,
        ${PLATFORM_CASE_SQL} AS platform,
        ${buildPkgFamilySql('p')} AS pkg_family
      FROM arbs_usd_swap_tape_legs_v2 l
      JOIN arbs_usd_swap_tape_packages_v2 p ON p.package_id = l.package_id
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) <  $2::timestamptz
        AND ${pkgFilter.sql}
        ${extraFilter}
        ${textFilterClause}
    ),
    bucketed AS (
      SELECT * FROM legs
      WHERE ${ctx.collapseAxis === 'forward' ? 'TRUE' : fwdBucketIsValidSqlPredicate(ctx.forwardSchema)}
        AND ${ctx.collapseAxis === 'tenor' ? 'TRUE' : tenorBucketIsValidSqlPredicate(ctx.tenorSchema)}
    ),
    windowed AS (
      SELECT *,
        CASE
          WHEN ts >= $3::timestamptz THEN 'current'
          ELSE 'baseline'
        END AS window_kind,
        ${ctx.bounds.windowIdSql} AS baseline_window_id
      FROM bucketed
    ),
    prior_per_window AS (
      SELECT fwd_bucket, tenor_bucket, baseline_window_id,
        SUM(${metricCol}) AS window_value
      FROM windowed
      WHERE window_kind = 'baseline'
      GROUP BY fwd_bucket, tenor_bucket, baseline_window_id
    ),
    prior_summary AS (
      SELECT fwd_bucket, tenor_bucket,
        array_agg(window_value ORDER BY window_value) AS prior_array,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY window_value) AS p25,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY window_value) AS p50,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY window_value) AS p75,
        MIN(window_value) AS pmin,
        MAX(window_value) AS pmax,
        COUNT(*)::int AS n
      FROM prior_per_window
      GROUP BY fwd_bucket, tenor_bucket
    ),
    current_agg AS (
      SELECT fwd_bucket, tenor_bucket,
        SUM(${metricCol}) AS current_value,
        SUM(${metricCol}) FILTER (WHERE platform = 'IDB')   AS idb_current,
        SUM(${metricCol}) FILTER (WHERE platform = 'CUSTY') AS custy_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'outright') AS outright_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'curve')    AS curve_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'fly')      AS fly_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'invoice')  AS invoice_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'other')    AS other_current,
        COUNT(*)::int AS trade_count,
        MAX(ts) AS last_ts
      FROM windowed
      WHERE window_kind = 'current'
      GROUP BY fwd_bucket, tenor_bucket
    )
    SELECT
      COALESCE(c.fwd_bucket, p.fwd_bucket)     AS fwd,
      COALESCE(c.tenor_bucket, p.tenor_bucket) AS tenor,
      COALESCE(c.current_value, 0)             AS current_value,
      COALESCE(c.idb_current, 0)               AS idb_current,
      COALESCE(c.custy_current, 0)             AS custy_current,
      COALESCE(c.outright_current, 0)          AS outright_current,
      COALESCE(c.curve_current, 0)             AS curve_current,
      COALESCE(c.fly_current, 0)               AS fly_current,
      COALESCE(c.invoice_current, 0)           AS invoice_current,
      COALESCE(c.other_current, 0)             AS other_current,
      COALESCE(c.trade_count, 0)               AS trade_count,
      COALESCE(p.prior_array, ARRAY[]::numeric[]) AS prior_array,
      COALESCE(p.p25, 0)  AS p25,
      COALESCE(p.p50, 0)  AS p50,
      COALESCE(p.p75, 0)  AS p75,
      COALESCE(p.pmin, 0) AS pmin,
      COALESCE(p.pmax, 0) AS pmax,
      COALESCE(p.n, 0)    AS n,
      MAX(c.last_ts) OVER () AS as_of_ts
    FROM current_agg c
    FULL OUTER JOIN prior_summary p USING (fwd_bucket, tenor_bucket)
  `
  return { sql, params }
}

export function buildVolumeGridSql(ctx: SqlBuildContext): BuiltSql {
  return ctx.bounds.kind === 'time_of_day'
    ? buildVolumeGridSqlTimeOfDay(ctx)
    : buildVolumeGridSqlRolling(ctx)
}

// computePercentile imported from volumeGridSqlLib

// summariseCells imported from volumeGridSqlLib

// RawVolumeGridRow imported from volumeGridSqlLib

// num imported from volumeGridSqlLib

export function shapeVolumeGridResponse(
  rows: ReadonlyArray<RawVolumeGridRow>,
  params: VolumeGridParams,
  forwardSchema: ResolvedSchema,
  tenorSchema: ResolvedSchema,
): VolumeGridResponse {
  // When an axis is collapsed, override with a single-bucket axis.
  const collapsedForwardBucket = { id: '_all_', label: 'All', lo: null as number | null, hi: null as number | null }
  const collapsedTenorBucket = { id: '_all_', label: 'All', lo: null as number | null, hi: null as number | null }

  // Dynamic-bucket schemas (FOMC for forward, venue for tenor) only know
  // their buckets once the rows come back from SQL — discover them.
  const resolvedForward: ResolvedSchema =
    params.collapseAxis === 'forward'
      ? { ...forwardSchema, buckets: [collapsedForwardBucket] }
      : forwardSchema.kind === 'fomc_label'
        ? {
            ...forwardSchema,
            buckets: buildFomcBucketsFromLabels(
              Array.from(new Set(rows.map((r) => r.fwd).filter((s): s is string => !!s))),
              { now: new Date(), limit: 16 },
            ),
          }
        : forwardSchema

  const resolvedTenor: ResolvedSchema =
    params.collapseAxis === 'tenor'
      ? { ...tenorSchema, buckets: [collapsedTenorBucket] }
      : tenorSchema.kind === 'venue'
        ? {
            ...tenorSchema,
            buckets: buildVenueBucketsFromIdentifiers(
              Array.from(new Set(rows.map((r) => r.tenor).filter((s): s is string => !!s))),
            ),
          }
        : tenorSchema

  const validFwd = new Set(resolvedForward.buckets.map((b) => b.id))
  const validTenor = new Set(resolvedTenor.buckets.map((b) => b.id))

  const cells: VolumeGridCell[] = rows
    .filter((r) => validFwd.has(r.fwd) && validTenor.has(r.tenor))
    .map(rowToCell)
  const totals = summariseCells(cells)
  const asOf = (() => {
    const raw = rows[0]?.as_of_ts
    if (!raw) return new Date().toISOString()
    if (raw instanceof Date) return raw.toISOString()
    return new Date(String(raw)).toISOString()
  })()
  return {
    asOf,
    metric: params.metric,
    period: params.period,
    lookbackDays: params.lookbackDays,
    forwardSchema: params.forwardSchema,
    tenorSchema: params.tenorSchema,
    packageType: params.packageType,
    viewMode: params.viewMode,
    axes: {
      forward: {
        id: resolvedForward.id,
        label: resolvedForward.label,
        buckets: resolvedForward.buckets.map((b) => ({ id: b.id, label: b.label })),
      },
      tenor: {
        id: resolvedTenor.id,
        label: resolvedTenor.label,
        buckets: resolvedTenor.buckets.map((b) => ({ id: b.id, label: b.label })),
      },
    },
    cells,
    totals,
  }
}
