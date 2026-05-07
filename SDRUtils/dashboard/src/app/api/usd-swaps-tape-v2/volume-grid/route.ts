// ABOUTME: GET /api/usd-swaps-tape-v2/volume-grid
// Returns the forward x tenor matrix of {current, baseline, percentile}
// per (metric, period, schemas, packageType). Server LRU + ETag + Server-Timing.

import { query } from '@/lib/db'
import { ServerLru } from '@/lib/usd-swaps-tape-v2/serverLru'
import { analyticsHandler } from '@/lib/usd-swaps-tape-v2/analyticsHandler'
import {
  resolveForwardSchema,
  resolveTenorSchema,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import {
  buildVolumeGridSql,
  computeWindowBounds,
  parseVolumeGridParams,
  shapeVolumeGridResponse,
  type RawVolumeGridRow,
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

async function produceVolumeGrid(request: Request): Promise<{ status: number; payload: unknown }> {
  const { searchParams } = new URL(request.url)
  const parsed = parseVolumeGridParams(searchParams)
  if (!parsed.ok) return { status: 400, payload: { error: parsed.error } }

  const now = new Date()
  const bounds = computeWindowBounds(parsed.value.period, parsed.value.lookbackDays, now)
  const forwardSchema = resolveForwardSchema(parsed.value.forwardSchema, now)
  const tenorSchema = resolveTenorSchema(parsed.value.tenorSchema)
  const built = buildVolumeGridSql({
    metric: parsed.value.metric,
    forwardSchema,
    tenorSchema,
    packageType: parsed.value.packageType,
    bounds,
  })

  try {
    const { rows } = await query<RawVolumeGridRow>(built.sql, built.params)
    const payload = shapeVolumeGridResponse(rows, parsed.value, forwardSchema, tenorSchema)
    return { status: 200, payload }
  } catch (error) {
    console.error('usd-swaps-tape-v2/volume-grid error', error)
    const message = error instanceof Error ? error.message : 'failed to fetch volume grid'
    return { status: 500, payload: { error: message } }
  }
}

export const GET = analyticsHandler(
  { lru, cacheHeaders: CACHE_HEADERS },
  produceVolumeGrid,
)
