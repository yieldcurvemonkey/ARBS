import { query } from '@/lib/db'
import { ServerLru } from '@/lib/usd-swaps-tape-v2/serverLru'
import { analyticsHandler } from '@/lib/usd-swaps-tape-v2/analyticsHandler'
import {
  buildAggregateIntradaySql,
  buildDailyTimeseriesSql,
  buildSummarySql,
  buildTenorDistributionSql,
  computeWindowBounds,
  parseAggregateParams,
  shapeAggregateResponse,
} from './route.logic'

const LRU_MAX = Number(process.env.ANALYTICS_LRU_MAX ?? 2048)
const LRU_TTL = Number(process.env.ANALYTICS_LRU_TTL ?? 300_000)
const lru = new ServerLru<{ payload: unknown; etag: string }>({
  max: LRU_MAX,
  ttlMs: LRU_TTL,
})

const CACHE_HEADERS = {
  'Cache-Control': 'private, max-age=300, stale-while-revalidate=600',
} as const

async function produceAggregateVolume(request: Request): Promise<{ status: number; payload: unknown }> {
  const { searchParams } = new URL(request.url)
  const parsed = parseAggregateParams(searchParams)
  if (!parsed.ok) return { status: 400, payload: { error: parsed.error } }

  const now = new Date()
  const bounds = computeWindowBounds(parsed.value.period, parsed.value.lookbackDays, now)

  const dailySql = buildDailyTimeseriesSql({
    metric: parsed.value.metric,
    lookbackDays: parsed.value.lookbackDays,
    packageType: parsed.value.packageType,
    textFilter: parsed.value.textFilter,
    now,
  })
  const summarySql = buildSummarySql({
    metric: parsed.value.metric,
    bounds,
    packageType: parsed.value.packageType,
    textFilter: parsed.value.textFilter,
  })
  const intradaySql = buildAggregateIntradaySql({
    metric: parsed.value.metric,
    lookbackDays: parsed.value.lookbackDays,
    packageType: parsed.value.packageType,
    textFilter: parsed.value.textFilter,
    now,
  })
  const tenorDistSql = buildTenorDistributionSql({
    metric: parsed.value.metric,
    bounds,
    packageType: parsed.value.packageType,
    textFilter: parsed.value.textFilter,
  })

  try {
    const [dailyResult, summaryResult, intradayResult, tenorDistResult] = await Promise.all([
      query(dailySql.sql, dailySql.params),
      query(summarySql.sql, summarySql.params),
      query(intradaySql.sql, intradaySql.params),
      query(tenorDistSql.sql, tenorDistSql.params),
    ])

    const payload = shapeAggregateResponse(
      dailyResult.rows as never[],
      summaryResult.rows as never[],
      intradayResult.rows as never[],
      tenorDistResult.rows as never[],
      parsed.value,
    )
    return { status: 200, payload }
  } catch (error) {
    console.error('usd-swaps-tape-v2/volume-grid/aggregate error', error)
    const message = error instanceof Error ? error.message : 'failed to fetch aggregate volume'
    return { status: 500, payload: { error: message } }
  }
}

export const GET = analyticsHandler(
  { lru, cacheHeaders: CACHE_HEADERS },
  produceAggregateVolume,
)
