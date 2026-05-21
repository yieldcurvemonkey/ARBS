// ABOUTME: GET /api/usd-swaps-tape-v2/volume-grid/structure
// Returns forward x structure matrix for curve/fly packages with
// {current, baseline, percentile} per cell. Same cache/ETag/timing
// pattern as the standard volume-grid endpoint.

import { query } from '@/lib/db'
import { ServerLru } from '@/lib/usd-swaps-tape-v2/serverLru'
import { analyticsHandler } from '@/lib/usd-swaps-tape-v2/analyticsHandler'
import {
  buildStructureGridSql,
  computeWindowBounds,
  parseStructureGridParams,
  resolveStructureForwardSchema,
  shapeStructureGridResponse,
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

async function produceStructureGrid(request: Request): Promise<{ status: number; payload: unknown }> {
  const { searchParams } = new URL(request.url)
  const parsed = parseStructureGridParams(searchParams)
  if (!parsed.ok) return { status: 400, payload: { error: parsed.error } }

  const now = new Date()
  const bounds = computeWindowBounds(parsed.value.period, parsed.value.lookbackDays, now)
  const forwardSchema = resolveStructureForwardSchema(parsed.value.forwardSchema, now)

  const built = buildStructureGridSql({
    structureType: parsed.value.structureType,
    structures: parsed.value.structures,
    metric: parsed.value.metric,
    forwardSchema,
    bounds,
    textFilter: parsed.value.textFilter,
  })

  try {
    const { rows } = await query<RawVolumeGridRow>(built.sql, built.params)
    const payload = shapeStructureGridResponse(rows, parsed.value, forwardSchema)
    return { status: 200, payload }
  } catch (error) {
    console.error('usd-swaps-tape-v2/volume-grid/structure error', error)
    const message = error instanceof Error ? error.message : 'failed to fetch structure grid'
    return { status: 500, payload: { error: message } }
  }
}

export const GET = analyticsHandler(
  { lru, cacheHeaders: CACHE_HEADERS },
  produceStructureGrid,
)
