// Hook for managing USD swap tape v2 data fetching, polling, and cursor pagination.
import { useCallback, useEffect, useRef, useState } from 'react'
import { TAPE_V2_API_BASE, POLL_INTERVAL_MS } from '../constants'
import type { UsdSwapTapeResponse, UsdSwapTapeRow, FlagFilterState } from '../types'

export interface UseTradeTapeDataParams {
  filter?: string
  columnFilterPayloadKey?: string
  columnFilterOperator?: 'and' | 'or'
  flagFilters?: FlagFilterState | null
  pollingEnabled?: boolean
  /**
   * Page size for cursor pagination. Matches the swaption tape default of 50,
   * which keeps individual fetches snappy and lets the VirtualScroller lazy
   * load chain pages as the user scrolls.
   */
  limit?: number
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

function serializeSet(s: Set<string> | undefined): string {
  if (!s || s.size === 0) return ''
  return Array.from(s).sort().join(',')
}

const DEFAULT_PAGE_LIMIT = 50

function buildQuery(params: UseTradeTapeDataParams, options?: {
  cursor?: string
  since?: string
}): URLSearchParams {
  const q = new URLSearchParams()
  const limit = params.limit ?? DEFAULT_PAGE_LIMIT
  q.set('limit', String(limit))
  if (options?.cursor) q.set('cursor', options.cursor)
  if (options?.since) q.set('since', options.since)
  if (params.filter) q.set('filter', params.filter)
  if (params.columnFilterPayloadKey) {
    q.set('columnFilters', params.columnFilterPayloadKey)
    q.set('columnFilterOp', params.columnFilterOperator ?? 'and')
  }
  const ff = params.flagFilters
  if (ff) {
    if (ff.clean) q.set('clean', 'true')
    const lc = serializeSet(
      new Set(Array.from(ff.lifecycle).map((l) => l.toLowerCase())),
    )
    if (lc) q.set('lifecycle', lc)
    const tt = serializeSet(ff.tradeTypes)
    if (tt) q.set('tradeTypes', tt)
    const v = serializeSet(ff.venues)
    if (v) q.set('venues', v)
    const c = serializeSet(ff.ccps)
    if (c) q.set('ccps', c)
    const s = serializeSet(ff.sessions)
    if (s) q.set('sessions', s)
    const r = serializeSet(ff.rateIndex)
    if (r) q.set('rateIndex', r)
    const tn = serializeSet(ff.tenors)
    if (tn) q.set('tenors', tn)
    if (ff.fomcMeeting) q.set('fomcMeeting', ff.fomcMeeting)
  }
  return q
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

  const abortRef = useRef<AbortController | null>(null)
  const fetchInFlight = useRef(false)

  const upsertRows = useCallback(
    (incoming: UsdSwapTapeRow[], replace: boolean) => {
      if (replace) {
        setRows(incoming)
      } else {
        setRows((prev) => {
          const map = new Map(prev.map((r) => [r.package_id, r]))
          incoming.forEach((r) => map.set(r.package_id, r))
          return Array.from(map.values()).sort((a, b) =>
            b.execution_start.localeCompare(a.execution_start),
          )
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

  // Reset on filter change
  useEffect(() => {
    setRows([])
    setNextCursor(null)
    setHasMore(false)
    setLatestExecutionStart(null)
    fetchTape({ replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    params.filter,
    params.columnFilterPayloadKey,
    params.columnFilterOperator,
    params.flagFilters,
    params.limit,
  ])

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

export const __internal = { buildQuery }
