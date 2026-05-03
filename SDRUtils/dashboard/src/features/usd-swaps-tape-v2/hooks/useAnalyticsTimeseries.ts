// Fetches pre-aggregated daily / intraday series for the analytics dock
// from /api/usd-swaps-tape-v2/analytics-timeseries. Lazy-loaded per
// view: intraday payload only fires when the user actually switches to
// the intraday tab, and daily loads don't re-run on view-only changes.
//
// Phase 2 perf hardening:
//   * AbortController per fetch — when the bucket / range / view swaps
//     mid-flight, the prior request is cancelled instead of racing to
//     update state with stale data.
//   * In-memory result cache keyed by (bucket, view, range) so flipping
//     between tabs doesn't re-issue the same SQL.
//   * Cache TTL bound (60s) so traders see fresh prints when polling
//     bumps an active bucket.
import { useCallback, useEffect, useRef, useState } from 'react'
import { TAPE_V2_API_BASE } from '../constants'
import type {
  AnalyticsRangeKey,
  AnalyticsViewKey,
  FocusedTrade,
  TimeseriesPointAug,
} from '../components/AnalyticsPanel/analytics-types'

export interface UseAnalyticsTimeseriesReturn {
  dailyClose: TimeseriesPointAug[]
  intraday: TimeseriesPointAug[]
  loading: boolean
  error: string | null
  pickForView: (view: AnalyticsViewKey) => TimeseriesPointAug[]
  refetch: () => void
}

type CacheEntry = {
  points: TimeseriesPointAug[]
  fetchedAt: number
}

export type AnalyticsTimeseriesOptions = {
  useGrossDv01?: boolean
  excludeLargeCusty?: boolean
}

const RESULT_CACHE_TTL_MS = 60_000
const resultCache = new Map<string, CacheEntry>()

function cacheKey(
  bucket: string,
  view: 'INTRADAY' | 'DAILY_CLOSE',
  range: AnalyticsRangeKey,
  opts: AnalyticsTimeseriesOptions = {},
): string {
  return [
    bucket,
    view,
    range,
    opts.useGrossDv01 ? 'gross' : 'net',
    opts.excludeLargeCusty === false ? 'raw-custy' : 'clean-custy',
  ].join('::')
}

function buildAnalyticsTimeseriesQuery(
  bucket: string,
  view: 'INTRADAY' | 'DAILY_CLOSE',
  range: AnalyticsRangeKey,
  opts: AnalyticsTimeseriesOptions = {},
): URLSearchParams {
  return new URLSearchParams({
    value: bucket,
    view,
    range,
    groupBy: 'tape_label',
    useGrossDv01: opts.useGrossDv01 ? 'true' : 'false',
    excludeLargeCusty: opts.excludeLargeCusty === false ? 'false' : 'true',
  })
}

async function fetchSeries(
  bucket: string,
  view: 'INTRADAY' | 'DAILY_CLOSE',
  range: AnalyticsRangeKey,
  opts: AnalyticsTimeseriesOptions,
  signal: AbortSignal,
): Promise<TimeseriesPointAug[]> {
  const key = cacheKey(bucket, view, range, opts)
  const cached = resultCache.get(key)
  if (cached && Date.now() - cached.fetchedAt < RESULT_CACHE_TTL_MS) {
    return cached.points
  }
  const q = buildAnalyticsTimeseriesQuery(bucket, view, range, opts)
  const res = await fetch(`${TAPE_V2_API_BASE}/analytics-timeseries?${q}`, { signal })
  if (!res.ok) {
    throw new Error(`analytics-timeseries ${view} ${res.status}`)
  }
  const data = await res.json()
  const points = (data.points ?? []) as TimeseriesPointAug[]
  resultCache.set(key, { points, fetchedAt: Date.now() })
  return points
}

export function useAnalyticsTimeseries(
  focused: FocusedTrade | null,
  range: AnalyticsRangeKey = '1Y',
  view: AnalyticsViewKey = 'DAILY_CLOSE',
  opts: AnalyticsTimeseriesOptions = {},
): UseAnalyticsTimeseriesReturn {
  const [dailyClose, setDailyClose] = useState<TimeseriesPointAug[]>([])
  const [intraday, setIntraday] = useState<TimeseriesPointAug[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const dailyAbortRef = useRef<AbortController | null>(null)
  const intradayAbortRef = useRef<AbortController | null>(null)

  const bucket = focused?.tape_label ?? null
  const needsIntraday = view === 'INTRADAY'
  const useGrossDv01 = Boolean(opts.useGrossDv01)
  const excludeLargeCusty = opts.excludeLargeCusty !== false

  const fetchDaily = useCallback(async () => {
    if (!bucket || needsIntraday) return
    dailyAbortRef.current?.abort()
    const controller = new AbortController()
    dailyAbortRef.current = controller
    setLoading(true)
    setError(null)
    try {
      const daily = await fetchSeries(
        bucket,
        'DAILY_CLOSE',
        range,
        { useGrossDv01, excludeLargeCusty },
        controller.signal,
      )
      if (controller.signal.aborted) return
      setDailyClose(daily)
    } catch (e) {
      if ((e as { name?: string })?.name === 'AbortError') return
      setError(e instanceof Error ? e.message : 'analytics-timeseries failed')
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }, [bucket, range, needsIntraday, useGrossDv01, excludeLargeCusty])

  const fetchIntraday = useCallback(async () => {
    if (!bucket || !needsIntraday) return
    intradayAbortRef.current?.abort()
    const controller = new AbortController()
    intradayAbortRef.current = controller
    setLoading(true)
    setError(null)
    try {
      const intra = await fetchSeries(
        bucket,
        'INTRADAY',
        '1D',
        { useGrossDv01, excludeLargeCusty },
        controller.signal,
      )
      if (controller.signal.aborted) return
      setIntraday(intra)
    } catch (e) {
      if ((e as { name?: string })?.name === 'AbortError') return
      setError(e instanceof Error ? e.message : 'analytics-timeseries failed')
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }, [bucket, needsIntraday, useGrossDv01, excludeLargeCusty])

  useEffect(() => { fetchDaily() }, [fetchDaily])
  useEffect(() => { fetchIntraday() }, [fetchIntraday])

  // Reset caches when bucket changes so a stale series from a different
  // focused trade doesn't briefly flash while the new fetch is in flight.
  useEffect(() => {
    setDailyClose([])
    setIntraday([])
  }, [bucket])

  // Abort any in-flight fetch on unmount so navigating away from the
  // dock doesn't leak fetches that update state on a torn-down hook.
  useEffect(() => {
    return () => {
      dailyAbortRef.current?.abort()
      intradayAbortRef.current?.abort()
    }
  }, [])

  const pickForView = useCallback(
    (v: AnalyticsViewKey) => (v === 'INTRADAY' ? intraday : dailyClose),
    [intraday, dailyClose],
  )

  const refetch = useCallback(async () => {
    if (bucket) {
      const cacheOpts = { useGrossDv01, excludeLargeCusty }
      resultCache.delete(cacheKey(bucket, 'DAILY_CLOSE', range, cacheOpts))
      resultCache.delete(cacheKey(bucket, 'INTRADAY', '1D', cacheOpts))
    }
    await (needsIntraday ? fetchIntraday() : fetchDaily())
  }, [bucket, range, fetchDaily, fetchIntraday, needsIntraday, useGrossDv01, excludeLargeCusty])

  return { dailyClose, intraday, loading, error, pickForView, refetch }
}

export const __internal = { resultCache, cacheKey, buildAnalyticsTimeseriesQuery }
