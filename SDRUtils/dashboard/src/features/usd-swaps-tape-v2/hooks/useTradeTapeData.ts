// Hook for managing USD swap tape v2 data fetching, polling, and cursor pagination.
import { useCallback, useEffect, useRef, useState } from 'react'
import { TAPE_V2_API_BASE, POLL_INTERVAL_MS } from '../constants'
import type { UsdSwapTapeResponse, UsdSwapTapeRow } from '../types'

export interface UseTradeTapeDataParams {
  pollingEnabled?: boolean
  /**
   * Page size for cursor pagination. Matches the swaption tape default of 50,
   * which keeps individual fetches snappy and lets the VirtualScroller lazy
   * load chain pages as the user scrolls.
   */
  limit?: number
  /**
   * Pre-serialised JSON for the URL-synced columnFilters payload. When
   * present, attached to every fetch (initial / cursor / since) so the
   * server applies the filter via WHERE clauses instead of returning
   * unfiltered rows. A change in this string resets the rows array and
   * triggers a fresh replace=true fetch.
   *
   * Pass null (or omit) when no per-column constraint is active so the
   * route's Cache-Control header stays in play for the unfiltered initial
   * fetch.
   */
  columnFilters?: string | null
}

export interface UseTradeTapeDataReturn {
  rows: UsdSwapTapeRow[]
  loading: boolean
  loadingMore: boolean
  error: string | null
  initialError: string | null
  pollError: string | null
  paginationError: string | null
  nextCursor: string | null
  hasMore: boolean
  latestExecutionStart: string | null
  fetchTape: (options?: {
    cursor?: string
    since?: string
    replace?: boolean
  }) => Promise<void>
  loadMore: () => Promise<void>
  refetch: () => Promise<void>
}

// Initial fetch loads a larger batch so traders see a deep tape on first paint,
// then VirtualScroller lazy-loads subsequent pages at the same size as the
// swaption tape.
const DEFAULT_PAGE_LIMIT = 200

function buildQuery(params: UseTradeTapeDataParams, options?: {
  cursor?: string
  since?: string
}): URLSearchParams {
  const q = new URLSearchParams()
  const limit = params.limit ?? DEFAULT_PAGE_LIMIT
  q.set('limit', String(limit))
  if (options?.cursor) q.set('cursor', options.cursor)
  if (options?.since) q.set('since', options.since)
  if (params.columnFilters) q.set('columnFilters', params.columnFilters)
  return q
}

/**
 * Collapse rows that point at the same logical trade pair and drop stale
 * orphan packages that have no legs attached.
 *
 * Pre-fix, the per-day detector used a local ``CURVE_N`` counter — so the
 * same 2-leg curve reported across multiple ingest runs landed in the
 * ``arbs_usd_swap_tape_packages_v1`` table multiple times under different
 * package_ids. Two side-effects in the dashboard:
 *
 *   1. Duplicate rows: both surviving package_ids render, differing only
 *      in aggregated fields like platform_identifier.
 *   2. Orphan rows with empty legs_json: when a later ingest re-classified
 *      a leg's ``trade_id`` under a fresh package_id, the leg's
 *      ``package_id`` FK flipped to the new package (legs upsert on
 *      ``trade_id``), leaving the OLD package row behind with nothing
 *      pointing at it. The LEFT JOIN LATERAL in the display view returns
 *      an empty ``legs_json`` for those packages, so the row shows up in
 *      the tape but has no chevron / no expansion content.
 *
 * The backend fix (globally-unique ``CURVE_N_<min_leg>`` etc.) stops new
 * duplicates from forming but can't retro-clean existing stale rows.
 *
 * Dedupe signature: execution_start + execution_end + package_type +
 * package_tenors + total_risk + weighted_fixed_rate + package_transaction_spread.
 * That tuple uniquely identifies a logical package trade — two entries
 * that agree on all seven fields are the same economic fill reported twice.
 *
 * Outrights (package_type=OUTRIGHT) have unique package_ids
 * (``OUTRIGHT-<trade_id>``) that get folded into the signature via
 * ``package_id`` so two genuinely different outrights with coincidentally-
 * matching fields never collide.
 *
 * When duplicates are found, prefer the variant with more legs (so the
 * healthy package beats an orphan with zero legs), then prefer the one
 * with the richest platform_identifier / venue, then first-seen.
 *
 * After dedup, any surviving row whose ``legs_json`` is still empty is
 * dropped — it can't be expanded and represents orphan state from the
 * legacy bug.
 */
function dedupeDuplicatePackages(rows: UsdSwapTapeRow[]): UsdSwapTapeRow[] {
  const isPackage = (r: UsdSwapTapeRow) => {
    const t = String(r.package_type ?? '').toUpperCase()
    return t && t !== 'OUTRIGHT' && t !== 'NONE' && t !== ''
  }
  const signatureKey = (r: UsdSwapTapeRow) => {
    if (!isPackage(r)) {
      // Outrights are keyed by package_id (= "OUTRIGHT-<trade_id>") so
      // two genuinely different outrights that happen to tie on all
      // aggregate fields still render as two rows.
      return `OUT|${r.package_id}`
    }
    return [
      'PKG',
      r.execution_start ?? '',
      r.execution_end ?? '',
      String(r.package_type ?? ''),
      String(r.package_tenors ?? ''),
      r.total_risk ?? '',
      r.weighted_fixed_rate ?? '',
      r.package_transaction_spread ?? '',
    ].join('|')
  }
  const legCount = (r: UsdSwapTapeRow) =>
    Array.isArray(r.legs_json) ? r.legs_json.length : 0
  const richness = (r: UsdSwapTapeRow) => {
    // Weights picked so leg count dominates: an orphan with zero legs can
    // never beat a healthy variant that has at least one leg, even if the
    // orphan has a populated platform.
    let score = legCount(r) * 10
    const platform = (r as { platform_identifier?: string | null })
      .platform_identifier
    if (platform && String(platform).trim() !== '') score += 2
    if (r.venue && String(r.venue).trim() !== '') score += 1
    return score
  }

  const best = new Map<string, UsdSwapTapeRow>()
  const order: string[] = []
  for (const row of rows) {
    const key = signatureKey(row)
    const prior = best.get(key)
    if (!prior) {
      best.set(key, row)
      order.push(key)
      continue
    }
    if (richness(row) > richness(prior)) {
      best.set(key, row)
    }
  }
  // Final pass: drop rows that are still orphans (no legs to show / expand).
  return order
    .map((k) => best.get(k)!)
    .filter((r): r is UsdSwapTapeRow => Boolean(r) && legCount(r) > 0)
}

export function useTradeTapeData(
  params: UseTradeTapeDataParams,
): UseTradeTapeDataReturn {
  const [rows, setRows] = useState<UsdSwapTapeRow[]>([])
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [latestExecutionStart, setLatestExecutionStart] = useState<string | null>(null)
  const [initialError, setInitialError] = useState<string | null>(null)
  const [pollError, setPollError] = useState<string | null>(null)
  const [paginationError, setPaginationError] = useState<string | null>(null)

  // P1-3 fix: Next.js useSearchParams may not change reference on
  // popstate, so the reset effect's dependency comparison sees no change
  // and forward navigation leaves the table empty. Increment a counter
  // on every popstate to force the reset effect to re-fire.
  const [navKey, setNavKey] = useState(0)
  useEffect(() => {
    const handler = () => setNavKey((k) => k + 1)
    window.addEventListener('popstate', handler)
    return () => window.removeEventListener('popstate', handler)
  }, [])

  const abortRef = useRef<AbortController | null>(null)
  const fetchInFlight = useRef(false)
  const recoveryAttemptRef = useRef(0)

  const upsertRows = useCallback(
    (incoming: UsdSwapTapeRow[], replace: boolean) => {
      if (replace) {
        setRows(dedupeDuplicatePackages(incoming))
      } else {
        setRows((prev) => {
          const map = new Map(prev.map((r) => [r.package_id, r]))
          incoming.forEach((r) => map.set(r.package_id, r))
          // The pg driver hands back `timestamp with time zone` as a JS
          // Date for fresh rows but as ISO strings for already-merged
          // rows that round-tripped through JSON. localeCompare on a
          // Date returns the toString form ("Thu Apr 09 2026 …") which
          // sorts unrelated to time. Coerce both sides to ISO strings
          // first so the merged set keeps a deterministic newest-first
          // order across polling and pagination upserts.
          const toKey = (v: unknown): string => {
            if (v instanceof Date) {
              return Number.isNaN(v.getTime()) ? '' : v.toISOString()
            }
            return v == null ? '' : String(v)
          }
          const combined = Array.from(map.values()).sort((a, b) =>
            toKey(b.execution_start).localeCompare(toKey(a.execution_start)),
          )
          return dedupeDuplicatePackages(combined)
        })
      }
    },
    [],
  )

  const fetchTape = useCallback(
    async (options?: {
      cursor?: string
      since?: string
      replace?: boolean
    }) => {
      if (fetchInFlight.current) return
      fetchInFlight.current = true
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      // 15s safety timeout — without this a hung network keeps
      // fetchInFlight stuck true and the 30s poll silently swallows
      // every subsequent tick. Once the timeout fires, the AbortError
      // is treated as a normal abort below and the in-flight latch
      // resets, so polling resumes on the next interval.
      const timeoutId = setTimeout(() => controller.abort(), 15_000)

      const isCursor = !!options?.cursor
      const isPoll = !!options?.since
      if (!isCursor && !isPoll) setLoading(true)
      if (isCursor) setLoadingMore(true)

      try {
        const q = buildQuery(params, options)
        const res = await fetch(`${TAPE_V2_API_BASE}?${q}`, {
          signal: controller.signal,
        })
        if (!res.ok) throw new Error(`Fetch failed: ${res.statusText}`)
        const data: UsdSwapTapeResponse = await res.json()
        upsertRows(data.rows, options?.replace ?? false)
        setNextCursor(data.nextCursor)
        setHasMore(data.hasMore)
        if (data.latestExecutionStart) {
          setLatestExecutionStart(data.latestExecutionStart)
        }
        // Clear the relevant error slot on success
        if (isCursor) setPaginationError(null)
        else if (isPoll) setPollError(null)
        else setInitialError(null)
      } catch (err) {
        if ((err as any)?.name === 'AbortError') return
        const msg = err instanceof Error ? err.message : 'Unknown error'
        if (isCursor) setPaginationError(msg)
        else if (isPoll) setPollError(msg)
        else setInitialError(msg)
      } finally {
        clearTimeout(timeoutId)
        setLoading(false)
        setLoadingMore(false)
        fetchInFlight.current = false
      }
    },
    [params, upsertRows],
  )

  const loadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return
    await fetchTape({ cursor: nextCursor })
  }, [fetchTape, nextCursor, loadingMore])

  const refetch = useCallback(async () => {
    await fetchTape({ replace: true })
  }, [fetchTape])

  // Reset on limit, columnFilters, or navigation (popstate) change. A
  // new filter payload means the server-side WHERE shape has changed;
  // existing rows + cursor are stale, so wipe them and fire a fresh
  // replace fetch. navKey catches forward/back navigation that doesn't
  // change the serialised filter string (P1-3 fix).
  useEffect(() => {
    setRows([])
    setNextCursor(null)
    setHasMore(false)
    setLatestExecutionStart(null)
    setInitialError(null)
    recoveryAttemptRef.current = 0
    fetchTape({ replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.limit, params.columnFilters, navKey])

  // P1-2 fix: when the initial fetch fails, latestExecutionStart stays
  // null and the polling guard blocks all subsequent ticks. Schedule
  // retries with exponential backoff (2s → 4s → 8s → … → 30s cap) so
  // the tape self-heals once the server recovers.
  useEffect(() => {
    if (!initialError || latestExecutionStart) return
    const attempt = recoveryAttemptRef.current
    const delay = Math.min(2000 * 2 ** attempt, 30_000)
    recoveryAttemptRef.current = attempt + 1
    const timeoutId = setTimeout(() => {
      fetchTape({ replace: true })
    }, delay)
    return () => clearTimeout(timeoutId)
  }, [initialError, latestExecutionStart, fetchTape])

  // Polling for new rows via ?since=latestExecutionStart
  useEffect(() => {
    if (params.pollingEnabled === false) return
    const id = setInterval(() => {
      if (latestExecutionStart) {
        fetchTape({ since: latestExecutionStart })
      }
    }, POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [fetchTape, latestExecutionStart, params.pollingEnabled])

  return {
    rows,
    loading,
    loadingMore,
    error: initialError ?? pollError ?? paginationError,
    initialError,
    pollError,
    paginationError,
    nextCursor,
    hasMore,
    latestExecutionStart,
    fetchTape,
    loadMore,
    refetch,
  }
}

export const __internal = { buildQuery, dedupeDuplicatePackages }
