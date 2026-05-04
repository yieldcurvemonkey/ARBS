# USD Swaps Tape v2 — Analytics Dock Fetching Optimisation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL — use `superpowers:executing-plans` to implement this plan task-by-task. Each task is bite-sized, TDD-shaped, and ends in its own commit, mirroring the cadence of PR #285 / PR #286.

**Goal:** Replace bespoke analytics-dock caching with SWR + IndexedDB persistence; add server-side LRU + ETag; decouple orthogonal display options from cache keys; prefetch on row hover. Hook contracts preserved so tabs are unchanged.

**Architecture:** Read-only SWR-based fetch layer in front of three existing API routes. Routes gain in-memory LRU + ETag emission; client gains a custom IndexedDB-backed SWR cache provider; orthogonal options (`useGrossDv01`, `excludeLargeCusty`) move into the payload so they don't bust the cache; row-hover prefetch behind a feature flag. Hook contracts (`useAnalyticsTimeseries` / `useRarityData` / `useExtremesData`) preserved.

**Tech Stack:** TypeScript, React 19, Next.js 15, Jest 30, Tailwind, PrimeReact 10, **`swr` (new dep)**. **`fake-indexeddb` (new dev dep)** for IDB tests.

**Date.** 2026-05-04
**Companion design.** [docs/plans/2026-05-04-analytics-fetching-design.md](2026-05-04-analytics-fetching-design.md)
**Routes affected.** `/usd-swaps`, API routes under `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/{analytics-timeseries,rarity,extremes}/route.ts`.
**Feature module.** `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/`
**Cross-workstream sequencing.** WS2's Phase A passthrough refactor lands first; this plan assumes the AnalyticsPanel surface is stable.

---

## Working directory commands

All paths relative to repo root. Dashboard tests:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2
```

Targeted test patterns:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=serverLru
cd SDRUtils/dashboard && npm test -- --testPathPatterns=etag
cd SDRUtils/dashboard && npm test -- --testPathPatterns=analyticsCacheKeys
cd SDRUtils/dashboard && npm test -- --testPathPatterns=IndexedDBCacheProvider
cd SDRUtils/dashboard && npm test -- --testPathPatterns=useAnalyticsPrefetch
```

Lint:

```bash
cd SDRUtils/dashboard && npm run lint
```

Dev server (no Turbopack — Turbopack fails inside the worktree junction; see PR #285 verification log):

```bash
cd SDRUtils/dashboard && PORT=3001 npx next dev
```

---

## Phase A — Server-side LRU + ETag

Three routes (`analytics-timeseries`, `rarity`, `extremes`) gain an in-memory LRU and an ETag emission wrapper. Client behavior is byte-for-byte unchanged when LRU is empty / `If-None-Match` is missing.

### Task A1: `ServerLru` helper (TDD)

**Files.**
- Create: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/serverLru.ts`
- Create: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/__tests__/serverLru.test.ts`

**Step 1. Write the failing test.**

```ts
import { describe, expect, it, beforeEach, afterEach, jest } from '@jest/globals'
import { ServerLru } from '../serverLru'

describe('ServerLru', () => {
  beforeEach(() => jest.useFakeTimers())
  afterEach(() => jest.useRealTimers())

  it('hits within TTL', () => {
    const lru = new ServerLru<string>({ max: 4, ttlMs: 60_000 })
    lru.set('k', 'v')
    expect(lru.get('k')).toBe('v')
  })

  it('expires after TTL', () => {
    const lru = new ServerLru<string>({ max: 4, ttlMs: 60_000 })
    lru.set('k', 'v')
    jest.advanceTimersByTime(61_000)
    expect(lru.get('k')).toBeUndefined()
  })

  it('evicts oldest when over max', () => {
    const lru = new ServerLru<string>({ max: 2, ttlMs: 60_000 })
    lru.set('a', 'va')
    lru.set('b', 'vb')
    lru.set('c', 'vc')
    expect(lru.get('a')).toBeUndefined()
    expect(lru.get('b')).toBe('vb')
    expect(lru.get('c')).toBe('vc')
  })

  it('promotes on get (LRU semantics)', () => {
    const lru = new ServerLru<string>({ max: 2, ttlMs: 60_000 })
    lru.set('a', 'va')
    lru.set('b', 'vb')
    lru.get('a')
    lru.set('c', 'vc')
    expect(lru.get('a')).toBe('va')
    expect(lru.get('b')).toBeUndefined()
  })
})
```

**Step 2. Run, expect failures.**

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=serverLru 2>&1 | tail -10
```

Expected: module-not-found errors.

**Step 3. Implement.**

```ts
// ABOUTME: Tiny per-route in-memory LRU with TTL. Used by USD swaps
// tape v2 analytics routes to memoise warehouse aggregations within a
// short window so that a focused-row toggle returning to a recently-
// viewed bucket reuses the prior response.

type Entry<V> = { value: V; expiresAt: number }

export interface ServerLruOptions {
  max: number
  ttlMs: number
}

export class ServerLru<V> {
  private map = new Map<string, Entry<V>>()
  constructor(private opts: ServerLruOptions) {}

  get(key: string): V | undefined {
    const entry = this.map.get(key)
    if (!entry) return undefined
    if (entry.expiresAt < Date.now()) {
      this.map.delete(key)
      return undefined
    }
    this.map.delete(key)
    this.map.set(key, entry)
    return entry.value
  }

  set(key: string, value: V): void {
    if (this.map.has(key)) this.map.delete(key)
    this.map.set(key, { value, expiresAt: Date.now() + this.opts.ttlMs })
    while (this.map.size > this.opts.max) {
      const oldest = this.map.keys().next().value
      if (oldest === undefined) break
      this.map.delete(oldest)
    }
  }

  size(): number { return this.map.size }
}
```

**Step 4. Run, expect green.**

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=serverLru 2>&1 | tail -10
```

**Step 5. Commit.**

```bash
git add SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/serverLru.ts \
        SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/__tests__/serverLru.test.ts
git commit -m "feat(usd-swaps-tape): in-memory LRU+TTL helper for analytics routes"
```

---

### Task A2: `etag` helper (TDD)

**Files.**
- Create: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/etag.ts`
- Create: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/__tests__/etag.test.ts`

**Step 1. Write the failing test.**

```ts
import { describe, expect, it } from '@jest/globals'
import { computeEtag, matchesIfNoneMatch } from '../etag'

describe('computeEtag', () => {
  it('is deterministic for identical input', () => {
    const a = computeEtag({ x: 1, y: [2, 3] })
    const b = computeEtag({ x: 1, y: [2, 3] })
    expect(a).toBe(b)
  })

  it('differs for different input', () => {
    expect(computeEtag({ x: 1 })).not.toBe(computeEtag({ x: 2 }))
  })

  it('quotes the value (HTTP wire format)', () => {
    expect(computeEtag({ x: 1 })).toMatch(/^"[a-f0-9]{40}"$/)
  })
})

describe('matchesIfNoneMatch', () => {
  it('returns true on exact match', () => {
    const tag = computeEtag({ x: 1 })
    expect(matchesIfNoneMatch(tag, tag)).toBe(true)
  })

  it('returns true for wildcard "*"', () => {
    expect(matchesIfNoneMatch('"abc"', '*')).toBe(true)
  })

  it('returns false on mismatch', () => {
    expect(matchesIfNoneMatch('"abc"', '"def"')).toBe(false)
  })

  it('returns false when If-None-Match is missing', () => {
    expect(matchesIfNoneMatch('"abc"', null)).toBe(false)
  })

  it('handles comma-separated If-None-Match values', () => {
    expect(matchesIfNoneMatch('"b"', '"a", "b", "c"')).toBe(true)
  })
})
```

**Step 2. Run, expect failures.**

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=etag 2>&1 | tail -10
```

**Step 3. Implement.**

```ts
// ABOUTME: ETag computation + If-None-Match matching for analytics
// routes. Computes a sha-1 of the JSON-serialised payload; wraps in
// HTTP-quoted form. Strong validators only (no W/ weak ETags).

import { createHash } from 'node:crypto'

export function computeEtag(payload: unknown): string {
  const sha = createHash('sha1').update(JSON.stringify(payload)).digest('hex')
  return `"${sha}"`
}

export function matchesIfNoneMatch(
  etag: string,
  ifNoneMatch: string | null,
): boolean {
  if (!ifNoneMatch) return false
  const trimmed = ifNoneMatch.trim()
  if (trimmed === '*') return true
  return trimmed.split(',').map((s) => s.trim()).includes(etag)
}
```

**Step 4. Run, expect green.**

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=etag 2>&1 | tail -10
```

**Step 5. Commit.**

```bash
git add SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/etag.ts \
        SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/__tests__/etag.test.ts
git commit -m "feat(usd-swaps-tape): ETag + If-None-Match helpers for analytics routes"
```

---

### Task A3: Wrap `analytics-timeseries/route.ts` with LRU + ETag (TDD)

**Files.**
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/analytics-timeseries/route.ts`
- Create or extend: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/analytics-timeseries/__tests__/route.cache.test.ts`

**Step 1. Write the failing test.**

```ts
import { describe, expect, it } from '@jest/globals'
import { GET } from '../route'

function req(qs: string, headers: Record<string, string> = {}): Request {
  return new Request(`http://t/api/usd-swaps-tape-v2/analytics-timeseries?${qs}`, {
    method: 'GET',
    headers,
  })
}

describe('analytics-timeseries route — LRU + ETag', () => {
  it('emits ETag + Cache-Control on success', async () => {
    const r = await GET(req('value=USD/SOFR-OIS/COMPOUND&groupBy=canonical&range=1M&view=DAILY_CLOSE'))
    expect(r.status).toBe(200)
    expect(r.headers.get('ETag')).toMatch(/^"[a-f0-9]{40}"$/)
    expect(r.headers.get('Cache-Control')).toBe('private, max-age=60, must-revalidate')
  })

  it('returns 304 on If-None-Match match', async () => {
    const first = await GET(req('value=USD/SOFR-OIS/COMPOUND&groupBy=canonical&range=1M&view=DAILY_CLOSE'))
    const tag = first.headers.get('ETag')!
    const second = await GET(
      req('value=USD/SOFR-OIS/COMPOUND&groupBy=canonical&range=1M&view=DAILY_CLOSE',
          { 'If-None-Match': tag })
    )
    expect(second.status).toBe(304)
    expect(await second.text()).toBe('')
  })

  it('LRU hit serves second request without SQL', async () => {
    // Spy: count SQL calls inside the route's warehouse client.
    // (Implementation in Step 3 pulls SQL into a mockable helper.)
  })
})
```

**Step 2. Run, expect failures (no ETag header today).**

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=analytics-timeseries.*route.cache 2>&1 | tail -10
```

**Step 3. Implement the wrapper.**

Add at top of `analytics-timeseries/route.ts` (below existing imports):

```ts
import { ServerLru } from '@/lib/usd-swaps-tape-v2/serverLru'
import { computeEtag, matchesIfNoneMatch } from '@/lib/usd-swaps-tape-v2/etag'

const LRU_MAX = Number(process.env.ANALYTICS_LRU_MAX ?? 512)
const lru = new ServerLru<{ payload: unknown; etag: string }>({
  max: LRU_MAX,
  ttlMs: 60_000,
})

function cacheKey(url: URL): string {
  const params = new URLSearchParams(url.search)
  const sorted = [...params.entries()].sort()
  return JSON.stringify(sorted)
}
```

Wrap the existing `GET` body. Refactor:

```ts
export async function GET(request: Request) {
  const url = new URL(request.url)
  const key = cacheKey(url)
  const ifNoneMatch = request.headers.get('If-None-Match')

  const hit = lru.get(key)
  if (hit) {
    if (matchesIfNoneMatch(hit.etag, ifNoneMatch)) {
      return new Response(null, {
        status: 304,
        headers: {
          ETag: hit.etag,
          'Cache-Control': 'private, max-age=60, must-revalidate',
        },
      })
    }
    return Response.json(hit.payload, {
      headers: {
        ETag: hit.etag,
        'Cache-Control': 'private, max-age=60, must-revalidate',
      },
    })
  }

  // ── existing route body — produces `payload` ──
  const payload = await /* existing aggregation */ produceAnalyticsTimeseries(url)

  const etag = computeEtag(payload)
  lru.set(key, { payload, etag })

  if (matchesIfNoneMatch(etag, ifNoneMatch)) {
    return new Response(null, {
      status: 304,
      headers: { ETag: etag, 'Cache-Control': 'private, max-age=60, must-revalidate' },
    })
  }
  return Response.json(payload, {
    headers: { ETag: etag, 'Cache-Control': 'private, max-age=60, must-revalidate' },
  })
}
```

The existing route body is extracted into a helper `produceAnalyticsTimeseries(url)` so the wrapper is testable in isolation. Move the existing body verbatim into that helper; keep the SQL exactly as-is.

**Step 4. Run, expect green.**

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=analytics-timeseries 2>&1 | tail -20
```

**Step 5. Commit.**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/analytics-timeseries/
git commit -m "feat(usd-swaps-tape): LRU+ETag wrapper on analytics-timeseries route"
```

---

### Task A4: Wrap `rarity/route.ts` with LRU + ETag

Same shape as A3, applied to `rarity/route.ts`. Mechanical: extract existing handler body into a helper `produceRarity(url)`, wrap with the `lru` + `cacheKey` + `If-None-Match` flow above.

Test file: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/rarity/__tests__/route.cache.test.ts` — mirror A3 with rarity-shaped params.

**Commit.** `feat(usd-swaps-tape): LRU+ETag wrapper on rarity route`

---

### Task A5: Wrap `extremes/route.ts` with LRU + ETag

Same shape, applied to `extremes/route.ts`. Test mirrors A3 / A4.

**Commit.** `feat(usd-swaps-tape): LRU+ETag wrapper on extremes route`

---

### Task A6: Document `ANALYTICS_LRU_MAX` env var

**Files.**
- Modify: `SDRUtils/dashboard/.env.example` (add `ANALYTICS_LRU_MAX=512` with a comment)
- Modify: `SDRUtils/dashboard/README.md` (document the env var if relevant)

**Step 1.** Add the env var to `.env.example`:

```
# Per-route LRU bound for analytics-dock routes.
# 512 ≈ 75 MB worst case at rarity payload size; safe for ~3 users.
ANALYTICS_LRU_MAX=512
```

**Step 2.** Run lint to make sure nothing broke:

```bash
cd SDRUtils/dashboard && npm run lint 2>&1 | tail -10
```

**Step 3.** Commit.

```bash
git add SDRUtils/dashboard/.env.example SDRUtils/dashboard/README.md
git commit -m "docs(usd-swaps-tape): document ANALYTICS_LRU_MAX env var"
```

---

## Phase B — SWR + IndexedDB cache provider + hook swaps

### Task B1: Install SWR + fake-indexeddb

**Step 1.**

```bash
cd SDRUtils/dashboard && npm install swr@^2.2.0
cd SDRUtils/dashboard && npm install --save-dev fake-indexeddb@^6.0.0
```

**Step 2.** Verify `package.json` reflects the new deps; run `npm test -- --testPathPatterns=usd-swaps-tape-v2` once to confirm nothing else broke.

**Step 3.** Commit.

```bash
git add SDRUtils/dashboard/package.json SDRUtils/dashboard/package-lock.json
git commit -m "chore(deps): add swr and fake-indexeddb"
```

---

### Task B2: `analyticsCacheKeys` helper (TDD)

**Files.**
- Create: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/analyticsCacheKeys.ts`
- Create: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/__tests__/analyticsCacheKeys.test.ts`

**Step 1. Write the failing test.**

```ts
import { describe, expect, it } from '@jest/globals'
import {
  timeseriesKey,
  rarityKey,
  extremesKey,
  type AnalyticsCacheKey,
} from '../analyticsCacheKeys'

describe('analyticsCacheKeys', () => {
  it('timeseriesKey is stable across runs', () => {
    const a = timeseriesKey({
      bucket: 'canonical:USD/SOFR-OIS/COMPOUND',
      view: 'DAILY_CLOSE', range: '1M',
      groupBy: 'canonical', groupValueOverride: 'USD/SOFR-OIS/COMPOUND',
      options: { tolerance: 0.5 },
    })
    const b = timeseriesKey({
      bucket: 'canonical:USD/SOFR-OIS/COMPOUND',
      view: 'DAILY_CLOSE', range: '1M',
      groupBy: 'canonical', groupValueOverride: 'USD/SOFR-OIS/COMPOUND',
      options: { tolerance: 0.5 },
    })
    expect(a).toEqual(b)
  })

  it('does NOT include orthogonal display options in key', () => {
    const a = timeseriesKey({
      bucket: 'x', view: 'DAILY_CLOSE', range: '1M',
      groupBy: 'tape_label', groupValueOverride: null,
      options: { useGrossDv01: true, excludeLargeCusty: true },
    })
    const b = timeseriesKey({
      bucket: 'x', view: 'DAILY_CLOSE', range: '1M',
      groupBy: 'tape_label', groupValueOverride: null,
      options: { useGrossDv01: false, excludeLargeCusty: false },
    })
    expect(a).toEqual(b)
  })

  it('different buckets produce different keys', () => {
    const a = timeseriesKey({
      bucket: 'a', view: 'DAILY_CLOSE', range: '1M',
      groupBy: 'tape_label', groupValueOverride: null, options: {},
    })
    const b = timeseriesKey({
      bucket: 'b', view: 'DAILY_CLOSE', range: '1M',
      groupBy: 'tape_label', groupValueOverride: null, options: {},
    })
    expect(a).not.toEqual(b)
  })

  it('rarityKey and extremesKey have stable shapes', () => {
    const r: AnalyticsCacheKey = rarityKey({
      bucket: 'x', groupBy: 'tape_label', groupValueOverride: null,
      options: { lookback: 90, primaryTol: 0.5, sizeTol: 0.2, binMetric: 'fixed_rate' },
    })
    expect(r[0]).toBe('usd-swaps-tape-v2')
    expect(r[1]).toBe('rarity')

    const e: AnalyticsCacheKey = extremesKey({
      bucket: 'x', groupBy: 'tape_label', groupValueOverride: null,
      options: { primaryTol: 0.5, sizeTol: 0.2 },
    })
    expect(e[1]).toBe('extremes')
  })
})
```

**Step 2. Run, expect failures.**

**Step 3. Implement.**

```ts
// ABOUTME: SWR cache key constructors for the three analytics-dock
// routes. Keys are deeply composite (route + bucket + view + range +
// groupBy + groupValueOverride + optionsHash) so future option fields
// can be added without invalidating the schema. Orthogonal display
// toggles (useGrossDv01, excludeLargeCusty) are stripped before
// hashing — they don't change the warehouse query result, only how
// the client renders it.

import { createHash } from 'node:crypto'

export type AnalyticsCacheKey = readonly [
  namespace: 'usd-swaps-tape-v2',
  route: 'analytics-timeseries' | 'rarity' | 'extremes',
  bucket: string,
  view: string | null,
  range: string,
  groupBy: string,
  groupValueOverride: string | null,
  optionsHash: string,
]

const ORTHOGONAL_DISPLAY_OPTIONS = new Set([
  'useGrossDv01',
  'excludeLargeCusty',
])

function hashOptions(options: Record<string, unknown>): string {
  const filtered = Object.entries(options)
    .filter(([k]) => !ORTHOGONAL_DISPLAY_OPTIONS.has(k))
    .sort(([a], [b]) => a.localeCompare(b))
  return createHash('sha1').update(JSON.stringify(filtered)).digest('hex').slice(0, 16)
}

export interface TimeseriesKeyArgs {
  bucket: string
  view: 'INTRADAY' | 'DAILY_CLOSE'
  range: '1D' | '1W' | '1M' | '1Y' | 'CUSTOM'
  groupBy: string
  groupValueOverride: string | null
  options: Record<string, unknown>
}

export function timeseriesKey(a: TimeseriesKeyArgs): AnalyticsCacheKey {
  return [
    'usd-swaps-tape-v2',
    'analytics-timeseries',
    a.bucket, a.view, a.range, a.groupBy, a.groupValueOverride,
    hashOptions(a.options),
  ] as const
}

export interface RarityKeyArgs {
  bucket: string
  groupBy: string
  groupValueOverride: string | null
  options: Record<string, unknown>
}

export function rarityKey(a: RarityKeyArgs): AnalyticsCacheKey {
  return [
    'usd-swaps-tape-v2',
    'rarity',
    a.bucket, null, '1Y', a.groupBy, a.groupValueOverride,
    hashOptions(a.options),
  ] as const
}

export interface ExtremesKeyArgs {
  bucket: string
  groupBy: string
  groupValueOverride: string | null
  options: Record<string, unknown>
}

export function extremesKey(a: ExtremesKeyArgs): AnalyticsCacheKey {
  return [
    'usd-swaps-tape-v2',
    'extremes',
    a.bucket, null, '1Y', a.groupBy, a.groupValueOverride,
    hashOptions(a.options),
  ] as const
}
```

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git add SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/analyticsCacheKeys.ts \
        SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/__tests__/analyticsCacheKeys.test.ts
git commit -m "feat(usd-swaps-tape): SWR cache-key constructors for analytics routes"
```

---

### Task B3: `SwrFetcher` with ETag handling (TDD)

**Files.**
- Create: `SDRUtils/dashboard/src/lib/swr/SwrFetcher.ts`
- Create: `SDRUtils/dashboard/src/lib/swr/__tests__/SwrFetcher.test.ts`

**Step 1. Write the failing test.**

```ts
import { describe, expect, it, beforeEach, jest } from '@jest/globals'
import { createFetcher } from '../SwrFetcher'

describe('SwrFetcher', () => {
  beforeEach(() => { (global as any).fetch = jest.fn() })

  it('returns parsed JSON on 200', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), {
        status: 200, headers: { ETag: '"abc"' },
      })
    )
    const fetcher = createFetcher()
    const r = await fetcher('/api/x')
    expect(r).toEqual({ ok: true })
  })

  it('caches ETag for next request via If-None-Match', async () => {
    const fetcher = createFetcher()
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      new Response(JSON.stringify({ v: 1 }), {
        status: 200, headers: { ETag: '"abc"' },
      })
    )
    await fetcher('/api/x')

    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      new Response(null, { status: 304 })
    )
    const r = await fetcher('/api/x')

    expect((global.fetch as jest.Mock).mock.calls[1][1].headers['If-None-Match']).toBe('"abc"')
    expect(r).toEqual({ v: 1 }) // 304 reuses prior payload
  })

  it('throws on non-200/304 responses', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(new Response('err', { status: 500 }))
    const fetcher = createFetcher()
    await expect(fetcher('/api/x')).rejects.toThrow(/500/)
  })
})
```

**Step 2. Run, expect failures.**

**Step 3. Implement.**

```ts
// ABOUTME: ETag-aware fetch wrapper for SWR. Retains the last seen
// ETag + payload per URL; sends If-None-Match on subsequent fetches;
// returns the cached payload on 304. Errors on any other non-200.

interface CacheEntry<T> { etag: string; payload: T }

export function createFetcher() {
  const cache = new Map<string, CacheEntry<unknown>>()
  return async function fetcher<T>(url: string): Promise<T> {
    const prior = cache.get(url)
    const headers: Record<string, string> = {}
    if (prior?.etag) headers['If-None-Match'] = prior.etag

    const response = await fetch(url, { headers })

    if (response.status === 304 && prior) return prior.payload as T

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status} ${response.statusText}`)
    }

    const payload = (await response.json()) as T
    const etag = response.headers.get('ETag')
    if (etag) cache.set(url, { etag, payload })
    return payload
  }
}
```

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git add SDRUtils/dashboard/src/lib/swr/SwrFetcher.ts \
        SDRUtils/dashboard/src/lib/swr/__tests__/SwrFetcher.test.ts
git commit -m "feat(swr): ETag-aware fetcher with 304 payload reuse"
```

---

### Task B4: `IndexedDBCacheProvider` (TDD)

**Files.**
- Create: `SDRUtils/dashboard/src/lib/swr/IndexedDBCacheProvider.ts`
- Create: `SDRUtils/dashboard/src/lib/swr/__tests__/IndexedDBCacheProvider.test.ts`

**Step 1. Write the failing test.**

```ts
import 'fake-indexeddb/auto'
import { describe, expect, it, beforeEach } from '@jest/globals'
import { createIndexedDBCacheProvider } from '../IndexedDBCacheProvider'

describe('IndexedDBCacheProvider', () => {
  beforeEach(async () => {
    await new Promise<void>((res) => {
      const r = indexedDB.deleteDatabase('arbs-swr-cache')
      r.onsuccess = () => res()
      r.onerror = () => res()
    })
  })

  it('round-trips set/get/delete', async () => {
    const provider = await createIndexedDBCacheProvider({ maxEntries: 200 })
    provider.set('k', { foo: 'bar' })
    expect(provider.get('k')).toEqual({ foo: 'bar' })
    provider.delete('k')
    expect(provider.get('k')).toBeUndefined()
  })

  it('persists across re-creates', async () => {
    const a = await createIndexedDBCacheProvider({ maxEntries: 200 })
    a.set('k', { v: 1 })
    await new Promise((r) => setTimeout(r, 50)) // flush
    const b = await createIndexedDBCacheProvider({ maxEntries: 200 })
    expect(b.get('k')).toEqual({ v: 1 })
  })

  it('evicts oldest when over maxEntries', async () => {
    const provider = await createIndexedDBCacheProvider({ maxEntries: 2 })
    provider.set('a', 1); provider.set('b', 2); provider.set('c', 3)
    await new Promise((r) => setTimeout(r, 50))
    expect(provider.get('a')).toBeUndefined()
    expect(provider.get('b')).toBe(2)
    expect(provider.get('c')).toBe(3)
  })

  it('iterator + keys + clear', async () => {
    const provider = await createIndexedDBCacheProvider({ maxEntries: 10 })
    provider.set('x', 1); provider.set('y', 2)
    expect([...provider.keys()].sort()).toEqual(['x', 'y'])
    provider.clear()
    expect([...provider.keys()]).toEqual([])
  })
})
```

**Step 2. Run, expect failures.**

**Step 3. Implement.**

```ts
// ABOUTME: SWR cache provider backed by IndexedDB. Keeps an in-memory
// shadow Map for synchronous reads (SWR requires sync get); persists
// asynchronously in the background. Evicts oldest entries beyond
// maxEntries via a per-set insertion-order list.

interface Entry { key: string; value: unknown; ts: number }
interface Options { maxEntries: number }

const DB_NAME = 'arbs-swr-cache'
const STORE = 'entries'

async function openDb(): Promise<IDBDatabase> {
  return new Promise((res, rej) => {
    const req = indexedDB.open(DB_NAME, 1)
    req.onupgradeneeded = () => {
      req.result.createObjectStore(STORE, { keyPath: 'key' })
    }
    req.onsuccess = () => res(req.result)
    req.onerror = () => rej(req.error)
  })
}

async function loadAll(db: IDBDatabase): Promise<Entry[]> {
  return new Promise((res, rej) => {
    const tx = db.transaction(STORE, 'readonly')
    const req = tx.objectStore(STORE).getAll()
    req.onsuccess = () => res(req.result as Entry[])
    req.onerror = () => rej(req.error)
  })
}

export async function createIndexedDBCacheProvider(opts: Options) {
  const db = await openDb()
  const memory = new Map<string, unknown>()
  const order: string[] = []

  for (const e of await loadAll(db)) {
    memory.set(e.key, e.value)
    order.push(e.key)
  }

  const persist = (key: string, value: unknown) => {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).put({ key, value, ts: Date.now() })
  }
  const drop = (key: string) => {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).delete(key)
  }

  return {
    get: (key: string) => memory.get(key),
    set: (key: string, value: unknown) => {
      if (memory.has(key)) {
        const idx = order.indexOf(key)
        if (idx >= 0) order.splice(idx, 1)
      }
      memory.set(key, value)
      order.push(key)
      persist(key, value)
      while (order.length > opts.maxEntries) {
        const oldest = order.shift()!
        memory.delete(oldest)
        drop(oldest)
      }
    },
    delete: (key: string) => {
      memory.delete(key)
      const idx = order.indexOf(key)
      if (idx >= 0) order.splice(idx, 1)
      drop(key)
    },
    clear: () => {
      memory.clear()
      order.length = 0
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).clear()
    },
    keys: () => memory.keys(),
    [Symbol.iterator]: () => memory.entries(),
  }
}
```

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git add SDRUtils/dashboard/src/lib/swr/IndexedDBCacheProvider.ts \
        SDRUtils/dashboard/src/lib/swr/__tests__/IndexedDBCacheProvider.test.ts
git commit -m "feat(swr): IndexedDB-backed cache provider with in-memory shadow"
```

---

### Task B5: Mount `SWRConfig` at dashboard root

**Files.**
- Modify: `SDRUtils/dashboard/src/app/layout.tsx` (or whichever component owns the dashboard root provider tree — confirm via grep before editing)

**Step 1.** Locate the root provider tree:

```bash
grep -rn "SWRConfig\|QueryClient\|ReactQuery" SDRUtils/dashboard/src/app SDRUtils/dashboard/src/components 2>&1 | tail -20
```

If no provider exists, the layout file is the right place. If a provider tree already exists, mount inside it.

**Step 2.** Add the SWRConfig wrapping the children. Use a client component shell:

```tsx
// SDRUtils/dashboard/src/app/SwrProvider.tsx (new file)
'use client'

import { SWRConfig } from 'swr'
import { useEffect, useState, type ReactNode } from 'react'
import { createIndexedDBCacheProvider } from '@/lib/swr/IndexedDBCacheProvider'
import { createFetcher } from '@/lib/swr/SwrFetcher'

export function SwrProvider({ children }: { children: ReactNode }) {
  const [provider, setProvider] = useState<Map<string, unknown> | null>(null)

  useEffect(() => {
    let mounted = true
    createIndexedDBCacheProvider({ maxEntries: 200 }).then((p) => {
      if (mounted) setProvider(p as unknown as Map<string, unknown>)
    })
    return () => { mounted = false }
  }, [])

  if (!provider) return <>{children}</> // pre-hydrate render — fine

  return (
    <SWRConfig
      value={{
        provider: () => provider,
        fetcher: createFetcher(),
        revalidateOnFocus: false,
        dedupingInterval: 5000,
      }}
    >
      {children}
    </SWRConfig>
  )
}
```

Then in `layout.tsx`:

```tsx
import { SwrProvider } from './SwrProvider'

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html>
      <body>
        <SwrProvider>{children}</SwrProvider>
      </body>
    </html>
  )
}
```

**Step 3.** Smoke-run:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2 2>&1 | tail -10
cd SDRUtils/dashboard && npm run lint 2>&1 | tail -10
```

Expected: all green. The SWRConfig is unused yet (no hooks consume it).

**Step 4.** Commit.

```bash
git add SDRUtils/dashboard/src/app/SwrProvider.tsx SDRUtils/dashboard/src/app/layout.tsx
git commit -m "feat(dashboard): mount SWRConfig with IndexedDB-backed cache"
```

---

### Task B6: Swap `useRarityData` internals to SWR (TDD)

Rarity is the heaviest payload (~120 KB) — biggest cache-hit win, so swap it first.

**Files.**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useRarityData.ts`
- Modify or create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useRarityData.swr.test.ts`

**Step 1. Write a behavior test that exercises caching.**

```ts
import 'fake-indexeddb/auto'
import { describe, expect, it } from '@jest/globals'
import { renderHook, waitFor } from '@testing-library/react'
import { useRarityData } from '../useRarityData'
// ... mocks for fetch + SWRConfig wrapper around renderHook

describe('useRarityData (SWR-backed)', () => {
  it('preserves the existing return shape (bins, stats, metricRows, recency)', async () => {
    const { result } = renderHook(() => useRarityData(focusedFixture, optsFixture), {
      wrapper: SWRWrapper,
    })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current).toMatchObject({
      bins: expect.any(Array),
      stats: expect.any(Object),
      metricRows: expect.any(Object),
      recency: expect.any(Object),
      loading: false,
      error: null,
    })
  })

  it('does not refetch when only orthogonal options change', async () => { /* ... */ })
  it('refetches when bucket changes', async () => { /* ... */ })
})
```

**Step 2. Run, expect failures.**

**Step 3. Implement.** Replace the body of `useRarityData` with an SWR-based version. Preserve the return shape and the `refetch` function (mapped to SWR's `mutate`).

```ts
import useSWR from 'swr'
import { rarityKey } from '@/lib/usd-swaps-tape-v2/analyticsCacheKeys'
// ... rest of imports

export function useRarityData(focused: FocusedTrade | null, options: RarityOptions) {
  const enabled = focused != null
  const key = enabled
    ? rarityKey({ bucket: deriveBucket(focused), groupBy: options.groupBy,
                  groupValueOverride: options.groupValueOverride ?? null,
                  options })
    : null
  const url = enabled ? buildRarityUrl(focused, options) : null

  const { data, error, isLoading, mutate } = useSWR(
    key,
    () => fetch(url!).then((r) => r.json()), // (handled by SwrFetcher in production)
  )

  return {
    bins: data?.bins ?? [],
    stats: data?.stats ?? null,
    metricRows: data?.metricRows ?? null,
    recency: data?.recency ?? null,
    loading: isLoading,
    error: error ? String(error) : null,
    refetch: () => mutate(),
  }
}
```

The `buildRarityUrl(focused, options)` helper encapsulates the existing URL construction; extract it from the original `useRarityData` body verbatim.

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useRarityData.ts \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useRarityData.swr.test.ts
git commit -m "refactor(usd-swaps-tape): useRarityData backed by SWR"
```

---

### Task B7: Swap `useExtremesData` internals to SWR

Same shape as B6, applied to `useExtremesData.ts`. Helper: `buildExtremesUrl(focused, options)` extracted.

**Commit.** `refactor(usd-swaps-tape): useExtremesData backed by SWR`

---

### Task B8: Swap `useAnalyticsTimeseries` internals to SWR + remove bespoke Map cache

Same shape as B6. Two notable details:

1. `useAnalyticsTimeseries` has separate daily + intraday fetches; SWR handles each as its own key.
2. Delete the bespoke `Map`-cache scaffolding (the `cache: Map<string, CacheEntry>` at `useAnalyticsTimeseries.ts:49`).

**Commit.** `refactor(usd-swaps-tape): useAnalyticsTimeseries on SWR; remove bespoke Map cache`

---

## Phase C — Orthogonal-option payload split

`useGrossDv01` and `excludeLargeCusty` toggle which numbers the chart shows but not which warehouse aggregation runs. Move them into the payload so the cache survives toggling.

### Task C1: Extend `analytics-timeseries` route to compute both gross+net + with/without large-custy

**Files.**
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/analytics-timeseries/route.ts`
- Extend: `analytics-timeseries/__tests__/route.test.ts` (or new file `route.orthogonal.test.ts`)

**Step 1. Pin the new payload shape with a test.**

```ts
it('returns four metric variants in one payload', async () => {
  const r = await GET(req('value=USD/SOFR-OIS/COMPOUND&groupBy=canonical&range=1M&view=DAILY_CLOSE'))
  const json = await r.json()
  expect(json.points[0]).toMatchObject({
    idbDv01_gross: expect.any(Number),
    idbDv01_net: expect.any(Number),
    custyDv01_gross: expect.any(Number),
    custyDv01_net: expect.any(Number),
    custyDv01_gross_excl_large: expect.any(Number),
    custyDv01_net_excl_large: expect.any(Number),
  })
})
```

**Step 2. Run, expect failures.**

**Step 3. Implement.** In the SQL aggregation CTE, compute both `SUM(ABS(risk))` (gross) and `SUM(risk)` (net). Compute the large-custy filter as a separate sum. Return all four series per point. Drop the request-side `useGrossDv01` / `excludeLargeCusty` parameters from SQL filtering — the client now toggles which series to render.

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/analytics-timeseries/
git commit -m "feat(usd-swaps-tape): analytics-timeseries returns gross+net+filtered in single payload"
```

---

### Task C2: Client toggle reads from extended payload; remove options from cache key

**Files.**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/TimeseriesTab.tsx`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useAnalyticsTimeseries.ts`

**Step 1. Pin via test that toggling does not refetch.**

```ts
it('toggling useGrossDv01 does not trigger network request', async () => { /* ... */ })
it('toggling excludeLargeCusty does not trigger network request', async () => { /* ... */ })
```

**Step 2. Run, expect failures.**

**Step 3. Implement.** Update `TimeseriesTab` to derive the rendered series from `point.idbDv01_gross` vs `point.idbDv01_net` (etc.) based on the toggle state. Update `useAnalyticsTimeseries` to drop the orthogonal options from the URL it constructs (already excluded from the key by `analyticsCacheKeys`).

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/TimeseriesTab.tsx \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useAnalyticsTimeseries.ts
git commit -m "feat(usd-swaps-tape): client toggles useGrossDv01/excludeLargeCusty from payload"
```

---

### Task C3: Verify rarity / extremes don't have analogous orthogonal options

Quick audit — confirm that `useRarityData` and `useExtremesData` have no analogous toggles that bust their cache. If any are found, extend the same pattern. Document in a comment in `analyticsCacheKeys.ts` if no further action is needed.

**Commit (if no further changes).** `docs(usd-swaps-tape): note that rarity/extremes have no orthogonal toggles`

---

## Phase D — IndexedDB persistence

The cache provider already persists from Phase B4. This phase wires in eviction tuning + hydrate-on-mount + a regression test that verifies persistence across simulated reloads.

### Task D1: Eviction policy tuning + maxEntries tuneable via env

**Files.**
- Modify: `SDRUtils/dashboard/src/lib/swr/IndexedDBCacheProvider.ts`
- Modify: `SDRUtils/dashboard/src/app/SwrProvider.tsx`

**Step 1.** Read `MAX_PERSISTENT_ENTRIES` from `process.env.NEXT_PUBLIC_SWR_CACHE_MAX_ENTRIES ?? 200`.

**Step 2.** Update `.env.example`:

```
# Max entries persisted in IndexedDB-backed SWR cache.
NEXT_PUBLIC_SWR_CACHE_MAX_ENTRIES=200
```

**Step 3.** Test that env-driven max takes effect.

**Step 4.** Commit.

```bash
git add SDRUtils/dashboard/src/lib/swr/IndexedDBCacheProvider.ts \
        SDRUtils/dashboard/src/app/SwrProvider.tsx \
        SDRUtils/dashboard/.env.example
git commit -m "feat(swr): IndexedDB cache size tuneable via NEXT_PUBLIC_SWR_CACHE_MAX_ENTRIES"
```

---

### Task D2: Hydrate-on-mount regression test

**Files.**
- Create: `SDRUtils/dashboard/src/lib/swr/__tests__/IndexedDBCacheProvider.hydrate.test.ts`

**Step 1. Write a test that simulates close-then-reopen.**

```ts
it('hydrates persisted entries on re-create', async () => {
  const a = await createIndexedDBCacheProvider({ maxEntries: 10 })
  a.set('key', { data: 'value' })
  await new Promise((r) => setTimeout(r, 50))

  const b = await createIndexedDBCacheProvider({ maxEntries: 10 })
  expect(b.get('key')).toEqual({ data: 'value' })
})
```

**Step 2. Run, expect green** (B4 already covers this; ensure no regression).

**Step 3. Commit.**

```bash
git add SDRUtils/dashboard/src/lib/swr/__tests__/IndexedDBCacheProvider.hydrate.test.ts
git commit -m "test(swr): pin IndexedDB hydrate-on-remount behaviour"
```

---

### Task D3: Quota / fallback handling

**Files.**
- Modify: `SDRUtils/dashboard/src/lib/swr/IndexedDBCacheProvider.ts`

**Step 1. Test.** Pin that if `indexedDB` is unavailable (e.g. private browsing), `createIndexedDBCacheProvider` falls back to an in-memory-only `Map` and emits a console warning.

**Step 2. Implement.** Wrap `openDb` in try/catch; on failure, return a provider that uses only the in-memory `Map`.

**Step 3. Commit.**

```bash
git add SDRUtils/dashboard/src/lib/swr/IndexedDBCacheProvider.ts \
        SDRUtils/dashboard/src/lib/swr/__tests__/IndexedDBCacheProvider.test.ts
git commit -m "feat(swr): graceful fallback when IndexedDB unavailable"
```

---

## Phase E — Prefetch on row hover

### Task E1: `useAnalyticsPrefetch` hook (TDD)

**Files.**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useAnalyticsPrefetch.ts`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useAnalyticsPrefetch.test.tsx`

**Step 1. Write the failing test.**

```ts
import 'fake-indexeddb/auto'
import { describe, expect, it, jest, beforeEach } from '@jest/globals'
import { renderHook, act } from '@testing-library/react'
import { useAnalyticsPrefetch } from '../useAnalyticsPrefetch'

describe('useAnalyticsPrefetch', () => {
  beforeEach(() => { (global as any).fetch = jest.fn(() => Promise.resolve(new Response('{}'))) })

  it('debounces 150ms before prefetching', async () => {
    const { result } = renderHook(() => useAnalyticsPrefetch())
    act(() => { result.current.onHover(rowFixture) })
    expect(global.fetch).not.toHaveBeenCalled()
    await new Promise((r) => setTimeout(r, 200))
    expect(global.fetch).toHaveBeenCalledTimes(3) // timeseries + rarity + extremes
  })

  it('cancels prefetch when hover changes within debounce', async () => {
    const { result } = renderHook(() => useAnalyticsPrefetch())
    act(() => { result.current.onHover(rowA) })
    act(() => { result.current.onHover(rowB) })
    await new Promise((r) => setTimeout(r, 200))
    // Only rowB prefetches fire (3), not rowA's
    expect(global.fetch).toHaveBeenCalledTimes(3)
  })

  it('respects ENABLE_HOVER_PREFETCH feature flag', async () => {
    process.env.NEXT_PUBLIC_ENABLE_HOVER_PREFETCH = 'false'
    const { result } = renderHook(() => useAnalyticsPrefetch())
    act(() => { result.current.onHover(rowFixture) })
    await new Promise((r) => setTimeout(r, 200))
    expect(global.fetch).not.toHaveBeenCalled()
    process.env.NEXT_PUBLIC_ENABLE_HOVER_PREFETCH = 'true'
  })
})
```

**Step 2. Run, expect failures.**

**Step 3. Implement.**

```ts
// ABOUTME: Debounced prefetch hook for the analytics dock. On row
// hover (with 150ms debounce), prefetches timeseries / rarity /
// extremes via SWR's mutate so a subsequent click renders instantly.
// Behind feature flag NEXT_PUBLIC_ENABLE_HOVER_PREFETCH (default on).

import { useCallback, useRef } from 'react'
import { useSWRConfig } from 'swr'
import { timeseriesKey, rarityKey, extremesKey } from '@/lib/usd-swaps-tape-v2/analyticsCacheKeys'
import type { UsdSwapTapeRow } from '../types/trade.types'
import { normalizeFocusedTrade } from './useFocusedTrade'

const DEBOUNCE_MS = 150

export function useAnalyticsPrefetch() {
  const { mutate, cache } = useSWRConfig()
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const enabled = process.env.NEXT_PUBLIC_ENABLE_HOVER_PREFETCH !== 'false'

  const onHover = useCallback((row: UsdSwapTapeRow | null) => {
    if (!enabled || !row) return
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      const focused = normalizeFocusedTrade(row)
      if (!focused) return
      const keys = [
        timeseriesKey(/* derive from focused + dock state */),
        rarityKey(/* ... */),
        extremesKey(/* ... */),
      ]
      for (const k of keys) {
        if (!cache.get(k as any)) mutate(k as any)
      }
    }, DEBOUNCE_MS)
  }, [enabled, mutate, cache])

  const onLeave = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  return { onHover, onLeave }
}
```

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useAnalyticsPrefetch.ts \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useAnalyticsPrefetch.test.tsx
git commit -m "feat(usd-swaps-tape): debounced row-hover prefetch hook"
```

---

### Task E2: Wire `useAnalyticsPrefetch` into `TradeTapeTable` row hover

**Files.**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TradeTapeTable.tsx`

**Step 1.** Test that `onMouseEnter` / `onMouseLeave` on a row fire `onHover` / `onLeave`.

**Step 2.** Implement: add the hook call inside `TradeTapeTable`; attach `onMouseEnter={() => onHover(row)}` and `onMouseLeave={onLeave}` to the PrimeReact `<DataTable>` `rowProps` callback (or equivalent).

**Step 3.** Commit.

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TradeTapeTable.tsx
git commit -m "feat(usd-swaps-tape): wire row-hover prefetch into TradeTapeTable"
```

---

### Task E3: Document `NEXT_PUBLIC_ENABLE_HOVER_PREFETCH`

**Files.**
- Modify: `SDRUtils/dashboard/.env.example`

```
# Enable analytics prefetch on row hover (150ms debounce).
NEXT_PUBLIC_ENABLE_HOVER_PREFETCH=true
```

**Commit.** `docs(usd-swaps-tape): document NEXT_PUBLIC_ENABLE_HOVER_PREFETCH flag`

---

## Verification

### Task V: Comprehensive E2E walk-through

**Step 1.** Run the full feature suite + lint:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2 2>&1 | tail -30
cd SDRUtils/dashboard && npm run lint 2>&1 | tail -10
```

Expected: all green.

**Step 2.** Start dev server:

```bash
cd SDRUtils/dashboard && PORT=3001 npx next dev
```

**Step 3.** Walk the §4.2 checklist from the design doc:

1. Open `/usd-swaps`. Wait for tape to populate.
2. Click row → dock opens. Network tab: 3 requests (analytics-timeseries, rarity, extremes), each with `ETag` + `Cache-Control: private, max-age=60`.
3. Click same row again → no network requests.
4. Click second row → 3 fresh requests.
5. Click first row again → 3 requests with `If-None-Match`, all 304.
6. Toggle "Use gross DV01" → no network request.
7. Toggle "Exclude large CUSTY" → no network request.
8. Hover third row (no click) → after 150ms, 3 prefetch requests fire silently.
9. Click third row → instant render.
10. Hard reload → rows render instantly from IDB hydrate.
11. Switch range from 1M to 1Y → fresh requests fire (range in key).
12. Switch groupBy to canonical → fresh requests fire.

**Step 4.** Walk regression check:

- Canonical-underlier flow (groupBy=canonical) — column tooltip + bucket selector unchanged.
- Package-confidence detail panel.
- Pagination + column filters + polling.
- Manual-link create / inspect.
- Multi-trade dock (post-WS2) single-mode behavior.

**Step 5.** Append a verification log to this plan (mirroring PR #285 + canonical-underlier-analytics):

```bash
git commit -am "docs(usd-swaps-tape): analytics-fetching verification log"
```

**Step 6.** Open PR.

```bash
git push -u origin <branch>
gh pr create --title "feat(usd-swaps-tape): analytics-dock fetching optimisation" --body "..."
```

PR body summarises:
- LRU + ETag on three routes (Phase A).
- SWR + IndexedDB-backed cache provider (Phase B).
- Orthogonal-option payload split (Phase C).
- Persistent cache hydrate (Phase D).
- Hover prefetch (Phase E).
- E2E verification evidence (network-tab before/after, cache-hit ratios sampled).

---

## Out of scope

- **Mutations / server-sent invalidation.**
- **Rarity sample-cap streaming.**
- **Server-side warehouse query optimisation.** SQL untouched (other than orthogonal-option fan-out in C1).
- **Cross-user shared cache.**
- **TanStack Query / Apollo / etc.**

## Risk + caveats

1. **Mount-time hydration race.** SWR `fallbackData` mitigates if needed.
2. **ETag staleness up to 60s on warehouse edits.** Acceptable for analytics dock.
3. **IDB browser quirks.** Fallback to in-memory provider (Task D3).
4. **Prefetch storm on rapid scroll.** Debounce + per-bucket dedup.
5. **WS2 cross-dependency.** WS2 lands first; this plan assumes the AnalyticsPanel surface is stable.

## Recommended order

- Day 1: Phase A (~6 tasks, ~4 hours).
- Day 2-3: Phase B (~8 tasks, ~2 days).
- Day 4: Phase C + D (~6 tasks, 1 day).
- Day 5: Phase E + Verification (~4 tasks, ~half day).
- PR cadence: single PR per the user's brief; long-running task; phases sequence within for review-ability.
