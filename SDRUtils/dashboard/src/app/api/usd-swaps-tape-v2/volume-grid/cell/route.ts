// ABOUTME: GET /api/usd-swaps-tape-v2/volume-grid/cell.
// Returns daily volume timeseries + most-recent N packages for the bucket.

import { query } from '@/lib/db'
import { ServerLru } from '@/lib/usd-swaps-tape-v2/serverLru'
import { analyticsHandler } from '@/lib/usd-swaps-tape-v2/analyticsHandler'
import {
  buildBucketPredicate,
  buildPackageTypeFilter,
  resolveForwardSchema,
  resolveTenorSchema,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import {
  buildIntradaySeasonalitySql,
  buildRecentTradesSql,
  buildTimeseriesSql,
  easternDateKey,
  INTRADAY_SEASONALITY_BUCKET_MINUTES,
  parseVolumeGridCellParams,
  rangeToStartDate,
  shapeIntradaySeasonalityResponse,
  type RawIntradaySeasonalityRow,
} from './route.logic'
import type {
  VolumeGridCellResponse,
  VolumeGridCellRecentTrade,
  VolumeGridCellTimeseriesPoint,
} from '@/features/usd-swaps-tape-v2/types/volume-grid.types'

const LRU_MAX = Number(process.env.ANALYTICS_LRU_MAX ?? 2048)
const LRU_TTL = Number(process.env.ANALYTICS_LRU_TTL ?? 300_000)
const lru = new ServerLru<{ payload: unknown; etag: string }>({
  max: LRU_MAX,
  ttlMs: LRU_TTL,
})
const CACHE_HEADERS = { 'Cache-Control': 'private, max-age=300, stale-while-revalidate=600' } as const

const num = (v: unknown): number => {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}

async function produceVolumeGridCell(request: Request): Promise<{ status: number; payload: unknown }> {
  const { searchParams } = new URL(request.url)
  const now = new Date()
  const parsed = parseVolumeGridCellParams(searchParams, now)
  if (!parsed.ok) return { status: 400, payload: { error: parsed.error } }
  const p = parsed.value

  const forwardSchema = resolveForwardSchema(p.forwardSchema, now)
  const tenorSchema = resolveTenorSchema(p.tenorSchema)
  const rangeStart = rangeToStartDate(p.range, now)
  const predicate = buildBucketPredicate('l', forwardSchema, tenorSchema, p.fwd, p.tenor, 2)
  const pkgFilter = buildPackageTypeFilter(
    p.packageType, 'p', 2 + predicate.params.length,
  )

  const combinedExtra = [forwardSchema.extraFilterSql, tenorSchema.extraFilterSql]
    .filter(Boolean)
    .join(' AND ')
  const tsSql = buildTimeseriesSql({
    bucketPredicateSql: predicate.sql,
    packageFilterSql: pkgFilter.sql,
    schemaExtraFilterSql: combinedExtra || undefined,
  })
  const limitParamIndex = 2 + predicate.params.length + pkgFilter.params.length
  const tradesSql = buildRecentTradesSql({
    bucketPredicateSql: predicate.sql,
    packageFilterSql: pkgFilter.sql,
    schemaExtraFilterSql: combinedExtra || undefined,
    limitParam: `$${limitParamIndex}`,
  })
  const intradayPredicate = buildBucketPredicate(
    'l',
    forwardSchema,
    tenorSchema,
    p.fwd,
    p.tenor,
    4,
  )
  const intradayPkgFilter = buildPackageTypeFilter(
    p.packageType,
    'p',
    4 + intradayPredicate.params.length,
  )
  const intradaySql = buildIntradaySeasonalitySql({
    metric: p.metric,
    bucketPredicateSql: intradayPredicate.sql,
    packageFilterSql: intradayPkgFilter.sql,
    schemaExtraFilterSql: combinedExtra || undefined,
  })

  try {
    const tsParams = [rangeStart.toISOString(), ...predicate.params, ...pkgFilter.params]
    const tradesParams = [
      rangeStart.toISOString(),
      ...predicate.params,
      ...pkgFilter.params,
      p.recentLimit,
    ]
    const intradayParams = [
      easternDateKey(now),
      rangeStart.toISOString(),
      INTRADAY_SEASONALITY_BUCKET_MINUTES,
      ...intradayPredicate.params,
      ...intradayPkgFilter.params,
    ]

    const [tsResult, tradesResult, intradayResult] = await Promise.all([
      query<Record<string, unknown>>(tsSql, tsParams),
      query<Record<string, unknown>>(tradesSql, tradesParams),
      query<RawIntradaySeasonalityRow>(intradaySql, intradayParams),
    ])

    const timeseries: VolumeGridCellTimeseriesPoint[] = tsResult.rows.map((r) => ({
      day: typeof r.day === 'string' ? r.day : new Date(r.day as string).toISOString().slice(0, 10),
      notional: num(r.notional),
      dv01: num(r.dv01),
      tradeCount: num(r.trade_count),
      idbCount: num(r.idb_count),
      custyCount: num(r.custy_count),
    }))
    const recentTrades: VolumeGridCellRecentTrade[] = tradesResult.rows.map((r) => ({
      package_id: String(r.package_id),
      execution_start: typeof r.execution_start === 'string'
        ? r.execution_start
        : new Date(r.execution_start as string).toISOString(),
      tape_label: (r.tape_label as string | null) ?? null,
      package_type: (r.package_type as string | null) ?? null,
      weighted_fixed_rate: r.weighted_fixed_rate == null ? null : num(r.weighted_fixed_rate),
      total_risk: r.total_risk == null ? null : num(r.total_risk),
      total_notional: r.total_notional == null ? null : num(r.total_notional),
      venue: (r.venue as string | null) ?? null,
      is_block_any: (r.is_block_any as boolean | null) ?? null,
    }))
    const payload: VolumeGridCellResponse = {
      fwd: p.fwd,
      tenor: p.tenor,
      metric: p.metric,
      range: p.range,
      forwardSchema: p.forwardSchema,
      tenorSchema: p.tenorSchema,
      packageType: p.packageType,
      timeseries,
      intradaySeasonality: shapeIntradaySeasonalityResponse(
        intradayResult.rows,
        INTRADAY_SEASONALITY_BUCKET_MINUTES,
      ),
      recentTrades,
    }
    return { status: 200, payload }
  } catch (error) {
    console.error('usd-swaps-tape-v2/volume-grid/cell error', error)
    const message = error instanceof Error ? error.message : 'failed to fetch cell drill-down'
    return { status: 500, payload: { error: message } }
  }
}

export const GET = analyticsHandler(
  { lru, cacheHeaders: CACHE_HEADERS },
  produceVolumeGridCell,
)
