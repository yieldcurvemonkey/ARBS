// ABOUTME: GET /api/usd-swaps-tape-v2/volume-grid/cell.
// Returns daily volume timeseries + most-recent N packages for the bucket.

import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { ServerLru } from '@/lib/usd-swaps-tape-v2/serverLru'
import { computeEtag, matchesIfNoneMatch } from '@/lib/usd-swaps-tape-v2/etag'
import {
  buildBucketPredicate,
  buildRecentTradesSql,
  buildTimeseriesSql,
  parseVolumeGridCellParams,
  rangeToStartDate,
} from './route.logic'
import type {
  VolumeGridCellResponse,
  VolumeGridCellRecentTrade,
  VolumeGridCellTimeseriesPoint,
} from '@/features/usd-swaps-tape-v2/types/volume-grid.types'

const LRU_MAX = Number(process.env.ANALYTICS_LRU_MAX ?? 512)
const lru = new ServerLru<{ payload: unknown; etag: string }>({
  max: LRU_MAX,
  ttlMs: 60_000,
})
const CACHE_HEADERS = { 'Cache-Control': 'private, max-age=60, must-revalidate' } as const

const cacheKey = (url: URL): string => {
  const sorted = [...new URLSearchParams(url.search).entries()].sort()
  return JSON.stringify(sorted)
}

const num = (v: unknown): number => {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
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

  const parsed = parseVolumeGridCellParams(url.searchParams)
  if (!parsed.ok) return NextResponse.json({ error: parsed.error }, { status: 400 })
  const p = parsed.value

  const rangeStart = rangeToStartDate(p.range)
  const predicate = buildBucketPredicate('l', p.fwd, p.tenor, 2)

  const tsSql = buildTimeseriesSql().replace('%BUCKET_PREDICATE%', predicate.sql)
  const tradesSql = buildRecentTradesSql()
    .replace('%BUCKET_PREDICATE%', predicate.sql)
    .replace('%LIMIT_PLACEHOLDER%', `$${2 + predicate.params.length}`)

  try {
    const tsParams = [rangeStart.toISOString(), ...predicate.params]
    const tradesParams = [rangeStart.toISOString(), ...predicate.params, p.recentLimit]

    const [tsResult, tradesResult] = await Promise.all([
      query<Record<string, unknown>>(tsSql, tsParams),
      query<Record<string, unknown>>(tradesSql, tradesParams),
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
      fwd: p.fwd as VolumeGridCellResponse['fwd'],
      tenor: p.tenor as VolumeGridCellResponse['tenor'],
      metric: p.metric, range: p.range,
      timeseries, recentTrades,
    }
    const etag = computeEtag(payload)
    lru.set(key, { payload, etag })
    if (matchesIfNoneMatch(etag, ifNoneMatch)) {
      return new Response(null, { status: 304, headers: { ETag: etag, ...CACHE_HEADERS } })
    }
    return NextResponse.json(payload, { headers: { ETag: etag, ...CACHE_HEADERS } })
  } catch (error) {
    console.error('usd-swaps-tape-v2/volume-grid/cell error', error)
    const message = error instanceof Error ? error.message : 'failed to fetch cell drill-down'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
