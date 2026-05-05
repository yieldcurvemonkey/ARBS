// ABOUTME: Pure helpers for /volume-grid/cell. SQL templates take the
// parameter-binding indices as a starting offset so callers thread their
// own bind list cleanly.

import {
  buildBucketPredicate,
  FORWARD_BUCKETS,
  TENOR_BUCKETS,
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
}

export type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string }

const VALID_METRICS: ReadonlySet<VolumeMetric> = new Set(['notional', 'dv01'])
const VALID_RANGES: ReadonlySet<VolumeCellRange> = new Set(['1M', '3M', '6M', '1Y'])

export function parseVolumeGridCellParams(
  search: URLSearchParams,
): ParseResult<VolumeGridCellParams> {
  const fwd = search.get('fwd')
  const tenor = search.get('tenor')
  if (!fwd) return { ok: false, error: 'fwd is required' }
  if (!tenor) return { ok: false, error: 'tenor is required' }
  if (!FORWARD_BUCKETS.some((b) => b.id === fwd)) return { ok: false, error: `unknown fwd: ${fwd}` }
  if (!TENOR_BUCKETS.some((b) => b.id === tenor)) return { ok: false, error: `unknown tenor: ${tenor}` }
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
  return { ok: true, value: { fwd, tenor, metric, range, recentLimit } }
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

export function buildTimeseriesSql(): string {
  // Bind order: $1=range_start, $2..N=bucket predicate params.
  return `
    WITH legs AS (
      SELECT
        COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
        ABS(COALESCE(l.notional, 0)) AS notional,
        ABS(COALESCE(l.risk, 0))     AS dv01,
        l.venue
      FROM arbs_usd_swap_tape_legs_v2 l
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND %BUCKET_PREDICATE%
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

export function buildRecentTradesSql(): string {
  // Bind order: $1=range_start, $2..N=bucket predicate params, $LAST=limit.
  return `
    WITH eligible_packages AS (
      SELECT DISTINCT l.package_id
      FROM arbs_usd_swap_tape_legs_v2 l
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND %BUCKET_PREDICATE%
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
    LIMIT %LIMIT_PLACEHOLDER%
  `
}

export { buildBucketPredicate }
