import { NextResponse } from 'next/server'
import { ServerLru } from './serverLru'
import { computeEtag, matchesIfNoneMatch } from './etag'

export interface AnalyticsRouteConfig {
  lru: ServerLru<{ payload: unknown; etag: string }>
  cacheHeaders: Record<string, string>
}

export type ProduceFn = (
  request: Request,
) => Promise<{ status: number; payload: unknown }>

export function cacheKey(url: URL): string {
  const params = new URLSearchParams(url.search)
  const sorted = [...params.entries()].sort()
  return JSON.stringify(sorted)
}

export function analyticsHandler(
  config: AnalyticsRouteConfig,
  produce: ProduceFn,
) {
  return async function GET(request: Request) {
    const totalStart = performance.now()
    const url = new URL(request.url)
    const ifNoneMatch = request.headers.get('If-None-Match')
    const key = cacheKey(url)

    const lruStart = performance.now()
    const hit = config.lru.get(key)
    const lruMs = performance.now() - lruStart

    if (hit) {
      const timing = `lru;dur=${lruMs.toFixed(1)};desc="hit", total;dur=${(performance.now() - totalStart).toFixed(1)}`
      if (matchesIfNoneMatch(hit.etag, ifNoneMatch)) {
        return new Response(null, {
          status: 304,
          headers: { ETag: hit.etag, 'Server-Timing': timing, ...config.cacheHeaders },
        })
      }
      return NextResponse.json(hit.payload, {
        headers: { ETag: hit.etag, 'Server-Timing': timing, ...config.cacheHeaders },
      })
    }

    const dbStart = performance.now()
    const { status, payload } = await produce(request)
    const dbMs = performance.now() - dbStart

    if (status === 200) {
      const etag = computeEtag(payload)
      config.lru.set(key, { payload, etag })
      const timing = `db;dur=${dbMs.toFixed(1)}, lru;dur=${lruMs.toFixed(1)};desc="miss", total;dur=${(performance.now() - totalStart).toFixed(1)}`
      if (matchesIfNoneMatch(etag, ifNoneMatch)) {
        return new Response(null, {
          status: 304,
          headers: { ETag: etag, 'Server-Timing': timing, ...config.cacheHeaders },
        })
      }
      return NextResponse.json(payload, {
        status,
        headers: { ETag: etag, 'Server-Timing': timing, ...config.cacheHeaders },
      })
    }

    const timing = `db;dur=${dbMs.toFixed(1)}, total;dur=${(performance.now() - totalStart).toFixed(1)}`
    return NextResponse.json(payload, {
      status,
      headers: { 'Server-Timing': timing },
    })
  }
}
