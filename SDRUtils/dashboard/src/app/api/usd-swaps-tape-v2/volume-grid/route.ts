// ABOUTME: GET /api/usd-swaps-tape-v2/volume-grid
// Returns the forward x tenor matrix of {current, baseline, percentile}
// per (metric, period, schemas, packageType). Server LRU + ETag.

import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { ServerLru } from '@/lib/usd-swaps-tape-v2/serverLru'
import { computeEtag, matchesIfNoneMatch } from '@/lib/usd-swaps-tape-v2/etag'
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

const LRU_MAX = Number(process.env.ANALYTICS_LRU_MAX ?? 512)
const lru = new ServerLru<{ payload: unknown; etag: string }>({
  max: LRU_MAX,
  ttlMs: 60_000,
})

const CACHE_HEADERS = {
  'Cache-Control': 'private, max-age=60, must-revalidate',
} as const

function cacheKey(url: URL): string {
  const params = new URLSearchParams(url.search)
  const sorted = [...params.entries()].sort()
  return JSON.stringify(sorted)
}

export async function GET(request: Request) {
  const url = new URL(request.url)
  const ifNoneMatch = request.headers.get('If-None-Match')
  const key = cacheKey(url)
  const hit = lru.get(key)
  if (hit) {
    if (matchesIfNoneMatch(hit.etag, ifNoneMatch)) {
      return new Response(null, { status: 304, headers: { ETag: hit.etag, ...CACHE_HEADERS } })
    }
    return NextResponse.json(hit.payload, { headers: { ETag: hit.etag, ...CACHE_HEADERS } })
  }

  const parsed = parseVolumeGridParams(url.searchParams)
  if (!parsed.ok) return NextResponse.json({ error: parsed.error }, { status: 400 })

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
    const etag = computeEtag(payload)
    lru.set(key, { payload, etag })
    if (matchesIfNoneMatch(etag, ifNoneMatch)) {
      return new Response(null, { status: 304, headers: { ETag: etag, ...CACHE_HEADERS } })
    }
    return NextResponse.json(payload, { headers: { ETag: etag, ...CACHE_HEADERS } })
  } catch (error) {
    console.error('usd-swaps-tape-v2/volume-grid error', error)
    const message = error instanceof Error ? error.message : 'failed to fetch volume grid'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
