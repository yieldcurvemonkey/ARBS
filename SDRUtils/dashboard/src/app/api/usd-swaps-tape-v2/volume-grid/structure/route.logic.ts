// ABOUTME: Pure helpers for /api/usd-swaps-tape-v2/volume-grid/structure.
// Mirrors the standard volume-grid route.logic.ts but operates on curve/fly
// packages rather than individual legs. Joins legs to structure definitions
// (e.g. "2s10s"), extracts the risk leg (long for curves, belly for flies),
// and computes the same percentile/baseline analytics.

import {
  buildBucketCaseSql,
  computeStructureDefaultForwardBuckets,
  PACKAGE_TYPE_GROUPS,
  resolveForwardSchema,
  type BucketDef,
  type ForwardSchemaId,
  type ResolvedSchema,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import {
  summariseCells,
  rowToCell,
  type RawVolumeGridRow,
} from '@/lib/usd-swaps-tape-v2/volumeGridSqlLib'
import {
  computeWindowBounds,
  type WindowBounds,
} from '../route.logic'
import type { VolumeGridCell } from '@/features/usd-swaps-tape-v2/types/volume-grid.types'
import type {
  StructureType,
  StructureDef,
  StructureGridResponse,
} from '@/features/usd-swaps-tape-v2/types/structure-grid.types'
import { TAPE_LEGS, TAPE_PACKAGES } from '@/lib/tape-tables'

export type { WindowBounds } from '../route.logic'
export { computeWindowBounds } from '../route.logic'

// Re-export for tests
export { type RawVolumeGridRow } from '@/lib/usd-swaps-tape-v2/volumeGridSqlLib'

// -----------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------

export type VolumePeriod = 'today' | '1h' | '24h' | '1w' | '2w' | '3w' | '1m' | '3m'
export type VolumeMetric = 'notional' | 'dv01'

/** Accepted forwardSchema values for the structure endpoint. */
export type StructureForwardSchemaId = 'structure_default' | ForwardSchemaId

export interface StructureGridParams {
  structureType: StructureType
  structures: StructureDef[]
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  forwardSchema: StructureForwardSchemaId
  textFilter?: string
}

export type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string }

// -----------------------------------------------------------------------
// Param parsing
// -----------------------------------------------------------------------

const VALID_STRUCTURE_TYPES: ReadonlySet<StructureType> = new Set(['curve', 'fly'])
const VALID_METRICS: ReadonlySet<VolumeMetric> = new Set(['notional', 'dv01'])
const VALID_PERIODS: ReadonlySet<VolumePeriod> = new Set([
  'today', '1h', '24h', '1w', '2w', '3w', '1m', '3m',
])
const VALID_FORWARD_SCHEMAS: ReadonlySet<string> = new Set([
  'structure_default', 'default', 'legacy', 'imm16', 'fomc', 'custom',
])

export function parseStructureGridParams(
  search: URLSearchParams,
): ParseResult<StructureGridParams> {
  // structureType — required
  const structureTypeRaw = search.get('structureType')
  if (structureTypeRaw == null) {
    return { ok: false, error: 'structureType is required' }
  }
  if (!VALID_STRUCTURE_TYPES.has(structureTypeRaw as StructureType)) {
    return { ok: false, error: `structureType must be one of ${[...VALID_STRUCTURE_TYPES].join(', ')}` }
  }

  // structures — required JSON array
  const structuresRaw = search.get('structures')
  if (structuresRaw == null) {
    return { ok: false, error: 'structures is required' }
  }
  let structures: StructureDef[]
  try {
    const parsed = JSON.parse(structuresRaw)
    if (!Array.isArray(parsed) || parsed.length === 0) {
      return { ok: false, error: 'structures must be a non-empty JSON array' }
    }
    structures = parsed as StructureDef[]
  } catch {
    return { ok: false, error: 'structures must be valid JSON' }
  }

  const metricRaw = (search.get('metric') ?? 'dv01').toLowerCase()
  if (!VALID_METRICS.has(metricRaw as VolumeMetric)) {
    return { ok: false, error: `metric must be one of ${[...VALID_METRICS].join(', ')}` }
  }

  const periodRaw = (search.get('period') ?? 'today').toLowerCase()
  if (!VALID_PERIODS.has(periodRaw as VolumePeriod)) {
    return { ok: false, error: `period must be one of ${[...VALID_PERIODS].join(', ')}` }
  }

  let lookbackDays = 90
  const lookbackRaw = search.get('lookbackDays')
  if (lookbackRaw != null) {
    const n = Number(lookbackRaw)
    if (!Number.isFinite(n) || n < 1 || n > 730) {
      return { ok: false, error: 'lookbackDays must be 1..730' }
    }
    lookbackDays = Math.floor(n)
  }

  const forwardSchemaRaw = (search.get('forwardSchema') ?? 'structure_default').toLowerCase()
  if (!VALID_FORWARD_SCHEMAS.has(forwardSchemaRaw)) {
    return { ok: false, error: `forwardSchema must be one of ${[...VALID_FORWARD_SCHEMAS].join(', ')}` }
  }

  const textFilter = search.get('textFilter') ?? undefined

  return {
    ok: true,
    value: {
      structureType: structureTypeRaw as StructureType,
      structures,
      metric: metricRaw as VolumeMetric,
      period: periodRaw as VolumePeriod,
      lookbackDays,
      forwardSchema: forwardSchemaRaw as StructureForwardSchemaId,
      textFilter,
    },
  }
}

// -----------------------------------------------------------------------
// Forward schema resolution
// -----------------------------------------------------------------------

export function resolveStructureForwardSchema(
  id: StructureForwardSchemaId,
  now: Date = new Date(),
): ResolvedSchema {
  if (id === 'structure_default') {
    const buckets = computeStructureDefaultForwardBuckets(now)
    return { id, label: 'Structure Default', buckets, kind: 'years' }
  }
  return resolveForwardSchema(id as ForwardSchemaId, now)
}

// -----------------------------------------------------------------------
// Package type lists per structure type
// -----------------------------------------------------------------------

const CURVE_PACKAGE_TYPES: ReadonlyArray<string> = [
  ...PACKAGE_TYPE_GROUPS.curve,
  ...PACKAGE_TYPE_GROUPS.spreadover_curve,
]

const FLY_PACKAGE_TYPES: ReadonlyArray<string> = [
  ...PACKAGE_TYPE_GROUPS.fly,
  ...PACKAGE_TYPE_GROUPS.spreadover_fly,
]

function packageTypesForStructure(type: StructureType): ReadonlyArray<string> {
  return type === 'curve' ? CURVE_PACKAGE_TYPES : FLY_PACKAGE_TYPES
}

// -----------------------------------------------------------------------
// Platform CASE SQL (unqualified column names for risk_leg CTE)
// -----------------------------------------------------------------------

/**
 * PLATFORM_CASE_SQL that references unqualified `venue` and
 * `platform_identifier` columns — suitable for use inside the `bucketed`
 * CTE where the source is the `risk_leg` CTE (no table alias prefix).
 */
const PLATFORM_CASE_UNQUALIFIED = `
  CASE
    WHEN UPPER(COALESCE(venue, '')) = 'D2D' THEN 'IDB'
    WHEN UPPER(COALESCE(platform_identifier, '')) IN
      ('BGCD', 'DWSF', 'IGDL', 'ISWV', 'TPSE', 'TSEF') THEN 'IDB'
    ELSE 'CUSTY'
  END
`

/**
 * pkg_family CASE using unqualified `package_type` from risk_leg CTE.
 */
const PKG_FAMILY_CASE_UNQUALIFIED = `CASE
    WHEN package_type IN ('OUTRIGHT','SPREADOVER','MATCHED_MATURITY') THEN 'outright'
    WHEN package_type IN ('CURVE','SPREADOVER_CURVE','MATCHED_MATURITY_CURVE') THEN 'curve'
    WHEN package_type IN ('FLY','SPREADOVER_FLY','MATCHED_MATURITY_FLY') THEN 'fly'
    ELSE 'other'
  END`

// -----------------------------------------------------------------------
// SQL builders
// -----------------------------------------------------------------------

export interface StructureSqlBuildContext {
  structureType: StructureType
  structures: StructureDef[]
  metric: VolumeMetric
  forwardSchema: ResolvedSchema
  bounds: WindowBounds
  textFilter?: string
}

export interface BuiltSql {
  sql: string
  params: Array<string | number>
}

/**
 * Build the VALUES(...) clause for the structure_defs CTE from the
 * array of structure definitions.
 */
function buildStructureDefsValuesSql(structures: StructureDef[]): string {
  return structures
    .map((s) => {
      const tenorArray = `ARRAY[${s.tenors.map((t) => `${t}::numeric`).join(', ')}]`
      return `('${s.id}', ${s.tenors.length}, ${tenorArray}, ${s.tolerance})`
    })
    .join(',\n      ')
}

/**
 * Build the forward-bucket CASE expression for the structure endpoint.
 * Uses unqualified `forward_start_years` since the source is the
 * risk_leg CTE.
 */
function buildStructureFwdBucketSql(forwardSchema: ResolvedSchema): string {
  if (forwardSchema.kind === 'fomc_label') {
    return `fomc_meeting_label`
  }
  // buildBucketCaseSql prefixes column refs with `alias.` — pass a
  // placeholder alias then strip the `__fwd__.` prefix to get bare
  // column references usable inside the risk_leg CTE.
  return buildBucketCaseSql('__fwd__', 'forward_start_years', forwardSchema.buckets)
    .replace(/__fwd__\./g, '')
}

function fwdBucketIsValidSqlPredicate(forwardSchema: ResolvedSchema): string {
  return forwardSchema.kind === 'fomc_label'
    ? `fwd_bucket IS NOT NULL`
    : `fwd_bucket <> 'other'`
}

/**
 * Risk leg rank expression: for curves pick the max-tenor leg (= leg_count),
 * for flies pick the belly (rank 2 of 3 sorted by ascending tenor).
 */
function riskLegRank(structureType: StructureType): string {
  return structureType === 'curve' ? 'leg_count' : '2'
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
 *   $6.. = package_type values
 */
export function buildStructureSqlTimeOfDay(ctx: StructureSqlBuildContext): BuiltSql {
  if (ctx.bounds.kind !== 'time_of_day') throw new Error('expected time_of_day bounds')

  const pkgTypes = packageTypesForStructure(ctx.structureType)
  const metricCol = ctx.metric === 'notional' ? 'notional_leg_value' : 'risk_leg_value'
  const fwdBucketExpr = buildStructureFwdBucketSql(ctx.forwardSchema)
  const structureDefsValues = buildStructureDefsValuesSql(ctx.structures)

  // Build params
  const params: Array<string | number> = [
    ctx.bounds.lookbackStart.toISOString(),
    ctx.bounds.lookbackEnd.toISOString(),
    ctx.bounds.todayDateEt,
    ctx.bounds.todSecondsLo,
    ctx.bounds.todSecondsHi,
  ]

  // Package type placeholders starting at $6
  const pkgPlaceholders = pkgTypes.map((_, i) => `$${6 + i}`).join(', ')
  params.push(...pkgTypes)

  // Text filter
  let textFilterClause = ''
  if (ctx.textFilter != null) {
    const textParamIdx = params.length + 1
    params.push(ctx.textFilter)
    textFilterClause = `AND p.tape_label ILIKE '%' || $${textParamIdx}::text || '%'`
  }

  const sql = `
    WITH structure_defs(structure_id, expected_legs, tenor_array, tolerance) AS (
      VALUES ${structureDefsValues}
    ),
    packages AS (
      SELECT p.package_id, p.execution_start, p.tape_label,
             p.package_type
      FROM ${TAPE_PACKAGES} p
      WHERE p.package_type IN (${pkgPlaceholders})
        AND p.execution_start >= $1::timestamptz
        AND p.execution_start < $2::timestamptz
        ${textFilterClause}
    ),
    structure_match AS (
      SELECT p.package_id, p.execution_start, l.venue, l.platform_identifier,
             p.package_type, s.structure_id, s.expected_legs,
             l.tenor_years, ABS(COALESCE(l.risk, 0)) AS risk_val,
             ABS(COALESCE(l.notional, 0)) AS notional_val,
             l.forward_start_years,
             ROW_NUMBER() OVER (
               PARTITION BY p.package_id, s.structure_id
               ORDER BY l.tenor_years ASC
             ) AS leg_rank,
             COUNT(*) OVER (
               PARTITION BY p.package_id, s.structure_id
             ) AS leg_count
      FROM packages p
      JOIN ${TAPE_LEGS} l ON l.package_id = p.package_id
        AND COALESCE(l.contributes_to_flow, FALSE) = TRUE
      CROSS JOIN structure_defs s
      WHERE EXISTS (
        SELECT 1 FROM unnest(s.tenor_array) AS t(v)
        WHERE l.tenor_years BETWEEN t.v - s.tolerance AND t.v + s.tolerance
      )
    ),
    risk_leg AS (
      SELECT package_id, structure_id,
        risk_val AS risk_leg_value, notional_val AS notional_leg_value,
        forward_start_years, execution_start AS ts,
        venue, platform_identifier, package_type
      FROM structure_match
      WHERE leg_count = expected_legs
        AND leg_rank = ${riskLegRank(ctx.structureType)}
    ),
    bucketed AS (
      SELECT *,
        ${fwdBucketExpr} AS fwd_bucket,
        structure_id AS tenor_bucket,
        ${PLATFORM_CASE_UNQUALIFIED} AS platform,
        ${PKG_FAMILY_CASE_UNQUALIFIED} AS pkg_family,
        (date_trunc('day', ts AT TIME ZONE 'America/New_York'))::date AS day_et,
        EXTRACT(EPOCH FROM (
          (ts AT TIME ZONE 'America/New_York')
          - date_trunc('day', ts AT TIME ZONE 'America/New_York')
        )) AS tod_seconds_et
      FROM risk_leg
    ),
    filtered AS (
      SELECT * FROM bucketed
      WHERE ${fwdBucketIsValidSqlPredicate(ctx.forwardSchema)}
        AND tod_seconds_et >= $4::numeric
        AND tod_seconds_et <= $5::numeric
    ),
    prior_per_day AS (
      SELECT fwd_bucket, tenor_bucket, day_et,
        SUM(${metricCol}) AS window_value
      FROM filtered
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
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'other')    AS other_current,
        COUNT(*)::int AS trade_count,
        MAX(ts) AS last_ts
      FROM filtered
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
 * Build the SQL for a rolling-window comparison ('24h' / '1w' / '2w' / '3w' / '1m' / '3m').
 *
 * Bind order:
 *   $1 = lookbackStart timestamptz
 *   $2 = lookbackEnd   timestamptz
 *   $3 = currentStart  timestamptz
 *   $4.. = package_type values
 */
export function buildStructureSqlRolling(ctx: StructureSqlBuildContext): BuiltSql {
  if (ctx.bounds.kind !== 'rolling') throw new Error('expected rolling bounds')

  const pkgTypes = packageTypesForStructure(ctx.structureType)
  const metricCol = ctx.metric === 'notional' ? 'notional_leg_value' : 'risk_leg_value'
  const fwdBucketExpr = buildStructureFwdBucketSql(ctx.forwardSchema)
  const structureDefsValues = buildStructureDefsValuesSql(ctx.structures)

  const params: Array<string | number> = [
    ctx.bounds.lookbackStart.toISOString(),
    ctx.bounds.lookbackEnd.toISOString(),
    ctx.bounds.currentStart.toISOString(),
  ]

  // Package type placeholders starting at $4
  const pkgPlaceholders = pkgTypes.map((_, i) => `$${4 + i}`).join(', ')
  params.push(...pkgTypes)

  // Text filter
  let textFilterClause = ''
  if (ctx.textFilter != null) {
    const textParamIdx = params.length + 1
    params.push(ctx.textFilter)
    textFilterClause = `AND p.tape_label ILIKE '%' || $${textParamIdx}::text || '%'`
  }

  const sql = `
    WITH structure_defs(structure_id, expected_legs, tenor_array, tolerance) AS (
      VALUES ${structureDefsValues}
    ),
    packages AS (
      SELECT p.package_id, p.execution_start, p.tape_label,
             p.package_type
      FROM ${TAPE_PACKAGES} p
      WHERE p.package_type IN (${pkgPlaceholders})
        AND p.execution_start >= $1::timestamptz
        AND p.execution_start < $2::timestamptz
        ${textFilterClause}
    ),
    structure_match AS (
      SELECT p.package_id, p.execution_start, l.venue, l.platform_identifier,
             p.package_type, s.structure_id, s.expected_legs,
             l.tenor_years, ABS(COALESCE(l.risk, 0)) AS risk_val,
             ABS(COALESCE(l.notional, 0)) AS notional_val,
             l.forward_start_years,
             ROW_NUMBER() OVER (
               PARTITION BY p.package_id, s.structure_id
               ORDER BY l.tenor_years ASC
             ) AS leg_rank,
             COUNT(*) OVER (
               PARTITION BY p.package_id, s.structure_id
             ) AS leg_count
      FROM packages p
      JOIN ${TAPE_LEGS} l ON l.package_id = p.package_id
        AND COALESCE(l.contributes_to_flow, FALSE) = TRUE
      CROSS JOIN structure_defs s
      WHERE EXISTS (
        SELECT 1 FROM unnest(s.tenor_array) AS t(v)
        WHERE l.tenor_years BETWEEN t.v - s.tolerance AND t.v + s.tolerance
      )
    ),
    risk_leg AS (
      SELECT package_id, structure_id,
        risk_val AS risk_leg_value, notional_val AS notional_leg_value,
        forward_start_years, execution_start AS ts,
        venue, platform_identifier, package_type
      FROM structure_match
      WHERE leg_count = expected_legs
        AND leg_rank = ${riskLegRank(ctx.structureType)}
    ),
    bucketed AS (
      SELECT *,
        ${fwdBucketExpr} AS fwd_bucket,
        structure_id AS tenor_bucket,
        ${PLATFORM_CASE_UNQUALIFIED} AS platform,
        ${PKG_FAMILY_CASE_UNQUALIFIED} AS pkg_family
      FROM risk_leg
    ),
    windowed AS (
      SELECT *,
        CASE
          WHEN ts >= $3::timestamptz THEN 'current'
          ELSE 'baseline'
        END AS window_kind,
        ${ctx.bounds.windowIdSql} AS baseline_window_id
      FROM bucketed
      WHERE ${fwdBucketIsValidSqlPredicate(ctx.forwardSchema)}
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

export function buildStructureGridSql(ctx: StructureSqlBuildContext): BuiltSql {
  return ctx.bounds.kind === 'time_of_day'
    ? buildStructureSqlTimeOfDay(ctx)
    : buildStructureSqlRolling(ctx)
}

// -----------------------------------------------------------------------
// Response shaping
// -----------------------------------------------------------------------

export function shapeStructureGridResponse(
  rows: ReadonlyArray<RawVolumeGridRow>,
  params: StructureGridParams,
  forwardSchema: ResolvedSchema,
): StructureGridResponse {
  const validFwd = new Set(forwardSchema.buckets.map((b) => b.id))
  const validStructure = new Set(params.structures.map((s) => s.id))

  const cells: VolumeGridCell[] = rows
    .filter((r) => validFwd.has(r.fwd) && validStructure.has(r.tenor))
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
    structureType: params.structureType,
    forwardSchema: params.forwardSchema,
    axes: {
      forward: {
        id: forwardSchema.id,
        label: forwardSchema.label,
        buckets: forwardSchema.buckets.map((b) => ({ id: b.id, label: b.label })),
      },
      structure: {
        id: 'structures',
        label: 'Structures',
        buckets: params.structures.map((s) => ({ id: s.id, label: s.label })),
      },
    },
    cells,
    totals,
  }
}
