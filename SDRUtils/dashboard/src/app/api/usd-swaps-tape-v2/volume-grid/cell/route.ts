// ABOUTME: GET /api/usd-swaps-tape-v2/volume-grid/cell.
// Returns daily volume timeseries + most-recent N packages for the bucket.

import { query } from '@/lib/db'
import { ServerLru } from '@/lib/usd-swaps-tape-v2/serverLru'
import { analyticsHandler } from '@/lib/usd-swaps-tape-v2/analyticsHandler'
import {
  buildBucketPredicate,
  buildPackageTypeFilter,
  PACKAGE_TYPE_GROUPS,
  resolveForwardSchema,
  resolveTenorSchema,
  type BucketDef,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import {
  buildIntradaySeasonalitySql,
  buildRecentTradesSql,
  buildStructureIntradaySeasonalitySql,
  buildStructureRecentTradesSql,
  buildStructureTimeseriesSql,
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
  if (p.customForwardBuckets) {
    ;(forwardSchema as { buckets: ReadonlyArray<BucketDef> }).buckets = p.customForwardBuckets
  }
  const tenorSchema = resolveTenorSchema(p.tenorSchema)
  if (p.customTenorBuckets) {
    ;(tenorSchema as { buckets: ReadonlyArray<BucketDef> }).buckets = p.customTenorBuckets
  }
  const rangeStart = rangeToStartDate(p.range, now)

  // ---------------------------------------------------------------
  // Structure mode — uses structure_match / risk_leg CTEs instead of
  // standard bucket predicates.
  // ---------------------------------------------------------------
  if (p.structureType && p.structureTenors) {
    return produceStructureCell(p, forwardSchema, rangeStart, now)
  }

  // ---------------------------------------------------------------
  // Standard (non-structure) mode
  // ---------------------------------------------------------------

  // When tenor is undefined (FOMC collapseAxis=tenor case), build a
  // forward-only predicate that skips the tenor constraint entirely.
  let effectivePredicate: { sql: string; params: Array<number | string> }
  let effectiveInCellPredicate: { sql: string; params: Array<number | string> }
  if (p.tenor) {
    effectivePredicate = buildBucketPredicate('l', forwardSchema, tenorSchema, p.fwd, p.tenor, 2)
    effectiveInCellPredicate = buildBucketPredicate('l2', forwardSchema, tenorSchema, p.fwd, p.tenor, 2)
  } else {
    // FOMC no-tenor case: only constrain on the forward bucket (fomc_meeting_label)
    const pi = 2
    effectivePredicate = { sql: `l.fomc_meeting_label = $${pi}`, params: [p.fwd] }
    effectiveInCellPredicate = { sql: `l2.fomc_meeting_label = $${pi}`, params: [p.fwd] }
  }

  const pkgFilter = buildPackageTypeFilter(
    p.packageType, 'p', 2 + effectivePredicate.params.length,
  )

  // Build textFilter SQL clause if textFilter is set.
  let textFilterSql: string | undefined
  let textFilterParams: string[] = []
  if (p.textFilter) {
    const textParamIndex = 2 + effectivePredicate.params.length + pkgFilter.params.length
    textFilterSql = `(l.tape_label ILIKE '%' || $${textParamIndex}::text || '%' OR p.tape_label ILIKE '%' || $${textParamIndex}::text || '%')`
    textFilterParams = [p.textFilter]
  }

  const combinedExtra = [forwardSchema.extraFilterSql, tenorSchema.extraFilterSql]
    .filter(Boolean)
    .join(' AND ')
  const tsSql = buildTimeseriesSql({
    bucketPredicateSql: effectivePredicate.sql,
    packageFilterSql: pkgFilter.sql,
    schemaExtraFilterSql: combinedExtra || undefined,
    textFilterSql,
  })
  const limitParamIndex = 2 + effectivePredicate.params.length + pkgFilter.params.length + textFilterParams.length
  const tradesSql = buildRecentTradesSql({
    bucketPredicateSql: effectivePredicate.sql,
    packageFilterSql: pkgFilter.sql,
    schemaExtraFilterSql: combinedExtra || undefined,
    textFilterSql,
    limitParam: `$${limitParamIndex}`,
    inCellPredicateSql: effectiveInCellPredicate.sql,
  })

  // Intraday query uses different param offsets (starts at $4)
  let intradayEffectivePredicate: { sql: string; params: Array<number | string> }
  if (p.tenor) {
    intradayEffectivePredicate = buildBucketPredicate('l', forwardSchema, tenorSchema, p.fwd, p.tenor, 4)
  } else {
    intradayEffectivePredicate = { sql: `l.fomc_meeting_label = $4`, params: [p.fwd] }
  }
  const intradayPkgFilter = buildPackageTypeFilter(
    p.packageType,
    'p',
    4 + intradayEffectivePredicate.params.length,
  )
  let intradayTextFilterSql: string | undefined
  let intradayTextFilterParams: string[] = []
  if (p.textFilter) {
    const intradayTextParamIndex = 4 + intradayEffectivePredicate.params.length + intradayPkgFilter.params.length
    intradayTextFilterSql = `(l.tape_label ILIKE '%' || $${intradayTextParamIndex}::text || '%' OR p.tape_label ILIKE '%' || $${intradayTextParamIndex}::text || '%')`
    intradayTextFilterParams = [p.textFilter]
  }
  const intradaySql = buildIntradaySeasonalitySql({
    metric: p.metric,
    bucketPredicateSql: intradayEffectivePredicate.sql,
    packageFilterSql: intradayPkgFilter.sql,
    schemaExtraFilterSql: combinedExtra || undefined,
    textFilterSql: intradayTextFilterSql,
  })

  try {
    const tsParams = [rangeStart.toISOString(), ...effectivePredicate.params, ...pkgFilter.params, ...textFilterParams]
    const tradesParams = [
      rangeStart.toISOString(),
      ...effectivePredicate.params,
      ...pkgFilter.params,
      ...textFilterParams,
      p.recentLimit,
    ]
    const intradayParams = [
      easternDateKey(now),
      rangeStart.toISOString(),
      INTRADAY_SEASONALITY_BUCKET_MINUTES,
      ...intradayEffectivePredicate.params,
      ...intradayPkgFilter.params,
      ...intradayTextFilterParams,
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
      ptsVwap: r.pts_vwap == null ? null : num(r.pts_vwap),
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
      legs: Array.isArray(r.legs)
        ? (r.legs as Array<Record<string, unknown>>).map((leg) => ({
            tenorYears: num(leg.tenor_years),
            forwardStartYears: num(leg.forward_start_years),
            notional: num(leg.notional),
            risk: num(leg.risk),
            inCell: leg.in_cell === true,
          }))
        : null,
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

// -----------------------------------------------------------------
// Structure-mode cell handler
// -----------------------------------------------------------------

import type {
  VolumeGridCellParams,
} from './route.logic'
import type { ResolvedSchema } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import type { StructureType } from '@/features/usd-swaps-tape-v2/types/structure-grid.types'

async function produceStructureCell(
  p: VolumeGridCellParams,
  forwardSchema: ResolvedSchema,
  rangeStart: Date,
  now: Date,
): Promise<{ status: number; payload: unknown }> {
  const structureType = p.structureType!
  const tenors = p.structureTenors!
  const tolerance = p.structureTolerance ?? 0.125

  // Resolve package types for this structure kind
  const pkgTypes = structureType === 'curve'
    ? [...PACKAGE_TYPE_GROUPS.curve, ...PACKAGE_TYPE_GROUPS.spreadover_curve]
    : [...PACKAGE_TYPE_GROUPS.fly, ...PACKAGE_TYPE_GROUPS.spreadover_fly]

  // Build forward predicate for the risk leg (references forward_start_years
  // from the structure_match CTE — no table alias needed).
  // For the timeseries/intraday queries, the forward constraint is applied
  // inside the risk_leg CTE where columns are unqualified from structure_match.
  const fwdBucket = forwardSchema.buckets.find((b) => b.id === p.fwd)

  let fwdPredicateParts: string[] = []
  if (forwardSchema.kind === 'fomc_label') {
    // FOMC schema not typical for structures, but support it
    fwdPredicateParts = ['fomc_meeting_label IS NOT NULL']
  } else if (fwdBucket) {
    if (fwdBucket.lo == null) {
      if (fwdBucket.hi != null) {
        fwdPredicateParts.push(`(forward_start_years IS NULL OR forward_start_years < ${fwdBucket.hi})`)
      } else {
        fwdPredicateParts.push('TRUE')
      }
    } else {
      fwdPredicateParts.push(`forward_start_years >= ${fwdBucket.lo}`)
      if (fwdBucket.hi != null) {
        fwdPredicateParts.push(`forward_start_years < ${fwdBucket.hi}`)
      }
    }
  } else {
    fwdPredicateParts = ['TRUE']
  }
  const fwdPredicateSql = fwdPredicateParts.join(' AND ')

  // Build package type placeholders. For timeseries/intraday:
  // $1 = rangeStart, then pkg types. For intraday: $1=currentDay, $2=rangeStart, $3=bucketMinutes, then pkg types.
  const tsPkgStartIdx = 2
  const tsPkgPlaceholders = pkgTypes.map((_, i) => `$${tsPkgStartIdx + i}`).join(', ')

  // Text filter for timeseries (param index after pkg types)
  let tsTextFilterSql: string | undefined
  const tsTextFilterParams: string[] = []
  if (p.textFilter) {
    const textIdx = tsPkgStartIdx + pkgTypes.length
    tsTextFilterSql = `(l.tape_label ILIKE '%' || $${textIdx}::text || '%' OR p.tape_label ILIKE '%' || $${textIdx}::text || '%')`
    tsTextFilterParams.push(p.textFilter)
  }

  const tsSql = buildStructureTimeseriesSql({
    structureType,
    tenors,
    tolerance,
    fwdPredicateSql,
    pkgTypePlaceholders: tsPkgPlaceholders,
    textFilterSql: tsTextFilterSql,
  })

  // Intraday params: $1=currentDay, $2=rangeStart, $3=bucketMinutes, then pkg types starting at $4
  const intradayPkgStartIdx = 4
  const intradayPkgPlaceholders = pkgTypes.map((_, i) => `$${intradayPkgStartIdx + i}`).join(', ')

  let intradayTextFilterSql: string | undefined
  const intradayTextFilterParams: string[] = []
  if (p.textFilter) {
    const textIdx = intradayPkgStartIdx + pkgTypes.length
    intradayTextFilterSql = `(l.tape_label ILIKE '%' || $${textIdx}::text || '%' OR p.tape_label ILIKE '%' || $${textIdx}::text || '%')`
    intradayTextFilterParams.push(p.textFilter)
  }

  const intradaySql = buildStructureIntradaySeasonalitySql({
    metric: p.metric,
    structureType,
    tenors,
    tolerance,
    fwdPredicateSql,
    pkgTypePlaceholders: intradayPkgPlaceholders,
    textFilterSql: intradayTextFilterSql,
  })

  // Recent trades: $1=rangeStart, then pkg types starting at $2, then limit
  const tradesPkgStartIdx = 2
  const tradesPkgPlaceholders = pkgTypes.map((_, i) => `$${tradesPkgStartIdx + i}`).join(', ')

  let tradesTextFilterSql: string | undefined
  const tradesTextFilterParams: string[] = []
  if (p.textFilter) {
    const textIdx = tradesPkgStartIdx + pkgTypes.length
    tradesTextFilterSql = `(l.tape_label ILIKE '%' || $${textIdx}::text || '%' OR p.tape_label ILIKE '%' || $${textIdx}::text || '%')`
    tradesTextFilterParams.push(p.textFilter)
  }

  const limitParamIdx = tradesPkgStartIdx + pkgTypes.length + tradesTextFilterParams.length
  const tradesSql = buildStructureRecentTradesSql({
    structureType,
    tenors,
    tolerance,
    fwdPredicateSql: fwdPredicateSql
      .replace(/forward_start_years/g, 'sm.forward_start_years')
      .replace(/fomc_meeting_label/g, 'sm.fomc_meeting_label'),
    pkgTypePlaceholders: tradesPkgPlaceholders,
    textFilterSql: tradesTextFilterSql,
    limitParam: `$${limitParamIdx}`,
  })

  try {
    const tsParams: Array<string | number> = [
      rangeStart.toISOString(),
      ...pkgTypes,
      ...tsTextFilterParams,
    ]
    const intradayParams: Array<string | number> = [
      easternDateKey(now),
      rangeStart.toISOString(),
      INTRADAY_SEASONALITY_BUCKET_MINUTES,
      ...pkgTypes,
      ...intradayTextFilterParams,
    ]
    const tradesParams: Array<string | number> = [
      rangeStart.toISOString(),
      ...pkgTypes,
      ...tradesTextFilterParams,
      p.recentLimit,
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
      ptsVwap: r.pts_vwap == null ? null : num(r.pts_vwap),
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
      legs: Array.isArray(r.legs)
        ? (r.legs as Array<Record<string, unknown>>).map((leg) => ({
            tenorYears: num(leg.tenor_years),
            forwardStartYears: num(leg.forward_start_years),
            notional: num(leg.notional),
            risk: num(leg.risk),
            inCell: leg.in_cell === true,
            isRiskLeg: leg.is_risk_leg === true ? true : undefined,
          }))
        : null,
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
    console.error('usd-swaps-tape-v2/volume-grid/cell structure-mode error', error)
    const message = error instanceof Error ? error.message : 'failed to fetch structure cell drill-down'
    return { status: 500, payload: { error: message } }
  }
}

export const GET = analyticsHandler(
  { lru, cacheHeaders: CACHE_HEADERS },
  produceVolumeGridCell,
)
