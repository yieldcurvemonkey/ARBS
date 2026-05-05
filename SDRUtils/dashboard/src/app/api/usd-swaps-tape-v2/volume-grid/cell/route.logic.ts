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
  type ForwardSchemaId,
  type PackageTypeGroupId,
  type TenorSchemaId,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import type {
  VolumeCellRange,
  VolumeMetric,
} from '@/features/usd-swaps-tape-v2/types/volume-grid.types'

export interface VolumeGridCellParams {
  fwd: string
  tenor: string
  metric: VolumeMetric
  range: VolumeCellRange
  recentLimit: number
  forwardSchema: ForwardSchemaId
  tenorSchema: TenorSchemaId
  packageType: PackageTypeGroupId
}

export type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string }

const VALID_METRICS: ReadonlySet<VolumeMetric> = new Set(['notional', 'dv01'])
const VALID_RANGES: ReadonlySet<VolumeCellRange> = new Set(['1M', '3M', '6M', '1Y'])
const VALID_FORWARD_SCHEMAS: ReadonlySet<ForwardSchemaId> = new Set(FORWARD_SCHEMA_IDS)
const VALID_TENOR_SCHEMAS: ReadonlySet<TenorSchemaId> = new Set(TENOR_SCHEMA_IDS)
const VALID_PACKAGE_GROUPS: ReadonlySet<PackageTypeGroupId> = new Set(PACKAGE_TYPE_GROUP_IDS)

export function parseVolumeGridCellParams(
  search: URLSearchParams,
  now: Date = new Date(),
): ParseResult<VolumeGridCellParams> {
  const fwd = search.get('fwd')
  const tenor = search.get('tenor')
  if (!fwd) return { ok: false, error: 'fwd is required' }
  if (!tenor) return { ok: false, error: 'tenor is required' }
  const forwardSchemaRaw = (search.get('forwardSchema') ?? 'default').toLowerCase()
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
  // Years-kind schemas have a fixed bucket list; fomc-label schemas
  // accept any string matching the SDR fomc_meeting_label format.
  if (forwardSchema.kind === 'fomc_label') {
    if (!/^[A-Z]{3}\d{2}$/.test(fwd)) {
      return { ok: false, error: `fwd must be a FOMC meeting label like 'APR26' (got ${fwd})` }
    }
  } else if (!forwardSchema.buckets.some((b) => b.id === fwd)) {
    return { ok: false, error: `unknown fwd: ${fwd} (schema=${forwardSchema.id})` }
  }
  if (!tenorSchema.buckets.some((b) => b.id === tenor)) {
    return { ok: false, error: `unknown tenor: ${tenor} (schema=${tenorSchema.id})` }
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
}): string {
  const extraFilter = opts.schemaExtraFilterSql ? `AND ${opts.schemaExtraFilterSql}` : ''
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

export function buildRecentTradesSql(opts: {
  bucketPredicateSql: string
  packageFilterSql: string
  schemaExtraFilterSql?: string
  limitParam: string // e.g. '$8'
}): string {
  const extraFilter = opts.schemaExtraFilterSql ? `AND ${opts.schemaExtraFilterSql}` : ''
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
      p.is_block_any
    FROM arbs_usd_swap_tape_packages_v2 p
    JOIN eligible_packages e ON e.package_id = p.package_id
    ORDER BY p.execution_start DESC
    LIMIT ${opts.limitParam}
  `
}

export { buildBucketPredicate, buildPackageTypeFilter }
