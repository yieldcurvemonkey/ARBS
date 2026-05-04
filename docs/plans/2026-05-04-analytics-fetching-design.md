# USD Swaps Tape v2 — Analytics Dock Fetching Optimisation — Design

**Date.** 2026-05-04
**Companion plan.** [docs/plans/2026-05-04-analytics-fetching-implementation.md](2026-05-04-analytics-fetching-implementation.md) (forthcoming)
**Routes affected.** `/usd-swaps` (v2 redirect target).
**Feature module.** `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/`
**API routes.** `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/{analytics-timeseries,rarity,extremes}/route.ts`
**Stack.** TypeScript, React 19, Next.js 15, Jest 30, Tailwind, PrimeReact 10. New runtime dependency: `swr`.

---

## 0. Why this plan

The analytics dock fetches per-focused-trade data through three independent hooks
(`useAnalyticsTimeseries`, `useRarityData`, `useExtremesData`) that fan out three parallel
HTTP requests on every row-focus change. Only `useAnalyticsTimeseries` has any client-side
cache (a bespoke 60-second in-memory `Map` at [useAnalyticsTimeseries.ts:49](../../SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useAnalyticsTimeseries.ts:49));
the other two refetch from scratch on every interaction. There is no server-side
memoisation, no `ETag` support, no cross-tab persistence, and no request coalescing —
so a trader who flips between five recent rows triggers fifteen warehouse round-trips
even though the underlying data was identical.

Per-route payload sizes (sampled by the exploration agent):

| Route | Typical payload | Cap |
|---|---|---|
| `analytics-timeseries` (DAILY_CLOSE) | ~5 KB | 2000 rows |
| `analytics-timeseries` (INTRADAY) | ~20 KB | 5000 rows |
| `rarity` | 80–150 KB | 50000 sample cap |
| `extremes` | ~10–15 KB | 8 extremes + 8 similar |

Rarity dominates. With three hooks firing in parallel and rarity at ~120 KB, every
focus change costs the user ~140 KB of network and the warehouse three fresh
aggregation queries.

Three orthogonal weaknesses make this worse:

1. **Tab-option toggles bust the cache.** `useAnalyticsTimeseries` keys its cache on
   `(bucket, view, range, useGrossDv01, excludeLargeCusty, groupBy, groupValueOverride)` —
   flipping `useGrossDv01` or `excludeLargeCusty` re-fetches the full payload even
   though both options are display transforms over the same source aggregation.
2. **No persistence across navigation.** Closing and re-opening the dock, or
   navigating back to a previously-viewed bucket, fires fresh requests. There is no
   IndexedDB- or localStorage-backed cache.
3. **No prefetch on hover.** A trader hovering rows pays full latency on click.

---

## 1. Approach

Replace the bespoke caching with **SWR**, add **IndexedDB persistence** via a custom
cache provider, add **`ETag` support** and an **in-memory LRU** on the server,
**decouple orthogonal display options** from cache keys, and **prefetch on row
hover**. Hook contracts (signatures consumed by `TimeseriesTab.tsx`,
`TradeRarityTab.tsx`, `TradedLevelsTab.tsx`) are preserved so tabs remain unchanged.

### 1.1 SWR + persistent cache provider

SWR over TanStack Query: the dock is read-only, no mutations needed, smaller surface,
simpler persistence story. SWR's [provider pattern](https://swr.vercel.app/docs/advanced/cache)
accepts a `Map`-shaped backing store; we provide an IndexedDB-backed wrapper.

Cache key shape (deeper composite for forward-compat):

```ts
type AnalyticsCacheKey = readonly [
  'usd-swaps-tape-v2',          // namespace
  'analytics-timeseries' | 'rarity' | 'extremes',
  bucket: string,                // groupBy + value
  view: 'INTRADAY' | 'DAILY_CLOSE' | null,  // timeseries-only
  range: '1D' | '1W' | '1M' | '1Y' | 'CUSTOM',
  groupBy: 'tape_label' | 'trade_type' | 'tenor' | 'canonical' | 'package',
  groupValueOverride: string | null,
  optionsHash: string,           // sha-1 of stable options minus orthogonal display toggles
]
```

The `optionsHash` slot leaves room for future fields (tolerance bands, lookback
window, custom range bounds) without invalidating the schema.

### 1.2 Server-side LRU + ETag

Each route gets:

- **In-memory LRU** keyed by request signature, 60s TTL, per-route bound.
  Bound: `512` entries per route, configurable via env var `ANALYTICS_LRU_MAX`.
  Worst-case memory: ~150 KB × 512 ≈ 75 MB rarity / ~10 MB timeseries / ~10 MB
  extremes — fine for the operational footprint (~3 users).
- **`ETag`** computed from the response body (sha-1 of `JSON.stringify(payload)`),
  emitted as `ETag: "<hash>"` and `Cache-Control: private, max-age=60, must-revalidate`.
  SWR + browser handle `If-None-Match` automatically; route returns `304` on match.

The LRU sits in the route module; reset on server restart. No Redis dependency.

### 1.3 Orthogonal display-option payload split

`useGrossDv01` and `excludeLargeCusty` change which numbers the chart shows but not
which rows the warehouse aggregates. Update `analytics-timeseries` to compute both
gross + net DV01 and both with-large-custy + without in a single SQL pass, return
both in one payload, and let the client toggle display. Cache key drops these two
dimensions.

Payload growth: roughly +40% on the timeseries response (still ~7 KB DAILY / ~28 KB
INTRADAY). Worth it for the cache-hit ratio improvement.

### 1.4 IndexedDB persistence

SWR cache provider backed by IndexedDB (no library beyond the native `indexedDB`
API). Bucket eviction: oldest-first when over `MAX_PERSISTENT_ENTRIES = 200`. Total
budget: ~30 MB worst case.

Persisted entries hydrate SWR on dock mount so a returning user sees instant data
while a background revalidate confirms freshness.

### 1.5 Prefetch on row hover

On row `onMouseEnter`, dispatch `mutate(swrKey, fetcher, { revalidate: false })` for
the three analytics routes if the row's bucket is not already in cache. Debounce
150 ms to avoid prefetching on transit hovers. Behind a feature flag
`ENABLE_HOVER_PREFETCH` (default on; flagged for easy rollback).

### 1.6 Hook contracts preserved

```ts
useAnalyticsTimeseries(focused, range, view, options)  // unchanged signature
useRarityData(focused, options)                         // unchanged
useExtremesData(focused, options)                       // unchanged
```

Tabs see no interface change. Only the inside changes.

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  AnalyticsPanel tabs (TimeseriesTab, TradeRarityTab,         │
│  TradedLevelsTab) — UNCHANGED                                │
└──────────────┬───────────────────────────────────────────────┘
               │ same hook signatures
               ▼
┌──────────────────────────────────────────────────────────────┐
│  Hooks (refactored internals only)                           │
│  useAnalyticsTimeseries / useRarityData / useExtremesData    │
│    └── useSWR(key, fetcher, options)                         │
└──────────────┬───────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────┐
│  SWRConfig provider (mounts on dashboard root)               │
│    ├── cache provider: IndexedDBBackedMap                    │
│    ├── revalidateOnFocus: false                              │
│    ├── dedupingInterval: 5 s                                 │
│    └── fetcher: fetch + ETag handling + 304 reuse            │
└──────────────┬───────────────────────────────────────────────┘
               │ HTTP w/ If-None-Match
               ▼
┌──────────────────────────────────────────────────────────────┐
│  API routes (refactored)                                     │
│  /api/usd-swaps-tape-v2/{analytics-timeseries,rarity,        │
│     extremes}                                                │
│    ├── route-local LRU(512, ttl=60s) → SQL                   │
│    ├── ETag + Cache-Control: private, max-age=60             │
│    └── orthogonal options computed once, returned in full    │
└──────────────────────────────────────────────────────────────┘
```

### 2.1 New / modified files (preview)

**New.**
- `SDRUtils/dashboard/src/lib/swr/IndexedDBCacheProvider.ts`
- `SDRUtils/dashboard/src/lib/swr/SwrFetcher.ts` (ETag-aware fetch wrapper)
- `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/analyticsCacheKeys.ts`
- `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/etag.ts`
- `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/serverLru.ts`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useAnalyticsPrefetch.ts`

**Modified.**
- `analytics-timeseries/route.ts`, `rarity/route.ts`, `extremes/route.ts` (LRU + ETag wrapper)
- `useAnalyticsTimeseries.ts`, `useRarityData.ts`, `useExtremesData.ts` (SWR-based internals)
- Dashboard root layout (mount `SWRConfig` if not already higher up)
- `TradeTapeTable.tsx` and/or `useTradeTapeData.ts` (hover-prefetch wiring)

**Deleted.**
- The bespoke `Map`-cache scaffolding inside `useAnalyticsTimeseries.ts`.

---

## 3. Constraints satisfied

| Constraint | How |
|---|---|
| Tab UI unchanged | Hook signatures preserved. Tabs see SWR's loading/error states the same way they see today's `loading` + `error`. |
| Polling not broken | Polling cadence + `?since=` requests live in `useTradeTapeData`, untouched. |
| Existing tests stay green | The four canonical-underlier-key contract tests are SQL-shape tests — untouched. The `TimeseriesTab` / `TradeRarityTab` / `TradedLevelsTab` snapshot tests don't care about hook internals. |
| Cards from PR #286 | The four PR-#286 cards (`UnderlierMixCard`, `RfrAdoptionCard`, `SwapSpreadVwapCard`, `CcpSwitchCard`) don't go through these routes — they aggregate over loaded `rows[]`. Untouched. |
| Manual links / dialogue / package detail panel | Untouched. |

---

## 4. Test plan

### 4.1 Unit / integration

- `IndexedDBCacheProvider.test.ts` — set/get/delete round-trips through `fake-indexeddb`; eviction at `MAX_PERSISTENT_ENTRIES`; hydration on mount.
- `analyticsCacheKeys.test.ts` — pin key shape; pin that orthogonal display options (`useGrossDv01`, `excludeLargeCusty`) do NOT appear in the key; pin `optionsHash` stability.
- `serverLru.test.ts` — eviction order, TTL expiry, signature normalisation.
- `etag.test.ts` — ETag deterministic across runs for identical payload; `If-None-Match` returns 304 with empty body.
- Per-route `route.test.ts` extensions — LRU hit on second request; 304 on `If-None-Match`; orthogonal options returned in single payload.
- Per-hook `__tests__/useAnalyticsTimeseries.test.ts` (and equivalents) — SWR `fallbackData` honored; revalidate triggers on bucket change; orthogonal toggle does NOT trigger refetch.
- `useAnalyticsPrefetch.test.tsx` — debounced prefetch on hover; cancels on hover-out within debounce; respects feature flag.

### 4.2 Comprehensive E2E (dev server)

`PORT=3001 npx next dev`, then:

1. Open `/usd-swaps`. Wait for tape to populate.
2. Click row → dock opens, three tabs render.
3. Network tab: confirm 3 requests fire (analytics-timeseries, rarity, extremes), each with `Cache-Control: private, max-age=60` + `ETag`.
4. Click same row again within 60s → no network requests (SWR dedup + IndexedDB hit).
5. Click second row → 3 fresh requests.
6. Click first row again → 3 requests with `If-None-Match`, all return 304.
7. Toggle "Use gross DV01" in Timeseries tab → no network request (orthogonal option, served from existing payload).
8. Toggle "Exclude large CUSTY" → no network request.
9. Hover a third row (don't click) → after 150ms debounce, 3 prefetch requests fire silently.
10. Click that third row → instant render (cache hit from prefetch).
11. Hard reload page → rows still render instantly from IndexedDB hydrate; background revalidate confirms freshness.
12. Switch range from 1M to 1Y → fresh requests fire (range is in cache key).
13. Toggle to canonical groupBy → fresh requests fire (groupBy in cache key).

### 4.3 Regression

Walk every analytics surface that touches the three routes:

- Canonical-underlier flow (`groupBy=canonical`) — ensure tape-column tooltip + canonical bucket selector unchanged.
- Package-confidence detail panel.
- Pagination + column filters + polling.
- Manual-link create / inspect (post-WS3 if landed; pre-WS3 minimal flow).
- Multi-trade dock (post-WS2 if landed; pre-WS2 single-mode).

---

## 5. Build sequence

One PR; long-running task. Phases sequence within for review-ability.

- **Phase A — server scaffolding.** `serverLru` + `etag` helpers, route wrappers; tests. No client change. Each route 304s on `If-None-Match`.
- **Phase B — client library swap.** Install `swr`. Build `IndexedDBCacheProvider` + `SwrFetcher` + `analyticsCacheKeys`. Mount `SWRConfig` at dashboard root. Per-hook internals swapped one at a time (rarity → extremes → analytics-timeseries — heaviest payload first). Hook contracts unchanged.
- **Phase C — orthogonal-option payload split.** Route returns gross+net+filter combinations in single payload; client toggles display; cache key drops two dimensions.
- **Phase D — IndexedDB persistence.** Cache provider wired to IDB; eviction policy; hydrate-on-mount.
- **Phase E — prefetch on hover.** `useAnalyticsPrefetch` + row hover wiring + feature flag.
- **Verification — full E2E** via dev server (§4.2), manual + scripted; before/after network-tab evidence captured in PR description.
- **Open PR.**

---

## 6. Out of scope

- **Mutations / server-sent invalidation.** Read-only dock. If a trader edits a manual link or causes derived data to change, the SWR cache will refresh on next focus change or after the 60s TTL. We don't push invalidations from server to client.
- **Rarity sample-cap streaming.** The 50k sample cap on `/rarity` is preserved; streaming the response is its own follow-up.
- **Server-side warehouse query optimisation.** SQL changes (composite indexes, materialised views) are out of scope. The LRU is the sole server-side optimisation.
- **Cross-user cache.** Per-user / per-session only. Three-user workload doesn't justify shared cache.
- **TanStack Query / Apollo / etc.** SWR chosen.

---

## 7. Risks

1. **SWR mount-time hydration race.** If IndexedDB is slow on first paint, tabs may flash empty before cache hydrates. Mitigation: `fallbackData` from synchronous in-memory mirror of the persistent cache for the most-recent N entries.
2. **ETag staleness on warehouse edits.** If warehouse data changes mid-session, ETag will report unchanged for up to 60s (LRU TTL). Acceptable for analytics dock — not real-time price.
3. **IndexedDB browser quirks.** Quota errors on long sessions. Mitigation: aggressive eviction + try/catch around persistence ops; fallback to in-memory only if IndexedDB unavailable.
4. **Prefetch storm on rapid scroll.** Hover debounce + per-bucket dedup. Worst case at 60 rows/s scroll: ~7 prefetches/s. Budgeted.
5. **Orthogonal option payload growth.** ~40% on timeseries. Acceptable. Verified during Phase C.
6. **WS2 cross-dependency.** WS2's passthrough refactor lands first (per cross-workstream sequencing) so this PR doesn't have to absorb that work; WS2 leaves the hook surface intact.

---

## 8. Rollback

Each phase is a separate commit. Granular rollback options:

- **Drop hover-prefetch**: revert Phase E commit + flip feature flag.
- **Drop IndexedDB persistence**: revert Phase D, leaves in-memory SWR cache (still better than today).
- **Drop orthogonal option split**: revert Phase C, restore old cache key.
- **Drop client library swap**: revert Phase B, restore bespoke hooks. Server LRU + ETag stay (still better than today).
- **Full revert**: revert all six commits.

Server-side phases (A) are byte-for-byte identical to today when the LRU is empty
and ETag is missing — safe to leave deployed even if client phases are rolled back.
