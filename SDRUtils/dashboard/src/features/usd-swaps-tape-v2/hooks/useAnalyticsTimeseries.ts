// Fetches pre-aggregated daily / intraday series for the analytics dock
// from /api/usd-swaps-tape-v2/analytics-timeseries. Lazy-loaded per
// view: intraday payload only fires when the user actually switches to
// the intraday tab, and daily loads don't re-run on view-only changes.
import { useCallback, useEffect, useState } from 'react'
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

async function fetchSeries(
  bucket: string,
  view: 'INTRADAY' | 'DAILY_CLOSE',
  range: AnalyticsRangeKey,
): Promise<TimeseriesPointAug[]> {
  const q = new URLSearchParams({
    value: bucket,
    view,
    range,
    groupBy: 'tape_label',
  })
  const res = await fetch(`${TAPE_V2_API_BASE}/analytics-timeseries?${q}`)
  if (!res.ok) {
    throw new Error(`analytics-timeseries ${view} ${res.status}`)
  }
  const data = await res.json()
  return (data.points ?? []) as TimeseriesPointAug[]
}

export function useAnalyticsTimeseries(
  focused: FocusedTrade | null,
  range: AnalyticsRangeKey = '1Y',
  view: AnalyticsViewKey = 'DAILY_CLOSE',
): UseAnalyticsTimeseriesReturn {
  const [dailyClose, setDailyClose] = useState<TimeseriesPointAug[]>([])
  const [intraday, setIntraday] = useState<TimeseriesPointAug[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const bucket = focused?.tape_label ?? null
  const needsIntraday = view === 'INTRADAY'

  // Daily fetch — fires whenever the bucket or range changes. Covers
  // DAILY_CLOSE / DAILY_OHLC / VOLUME. INTRADAY doesn't need this.
  const fetchDaily = useCallback(async () => {
    if (!bucket || needsIntraday) return
    setLoading(true)
    setError(null)
    try {
      const daily = await fetchSeries(bucket, 'DAILY_CLOSE', range)
      setDailyClose(daily)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'analytics-timeseries failed')
    } finally {
      setLoading(false)
    }
  }, [bucket, range, needsIntraday])

  // Intraday fetch — fires only when the user picks the INTRADAY view.
  // Server pins the window to last 72h regardless of range selector;
  // intraday is intrinsically short-term and pulling a month of ticks
  // is the primary cause of the earlier slowness.
  const fetchIntraday = useCallback(async () => {
    if (!bucket || !needsIntraday) return
    setLoading(true)
    setError(null)
    try {
      const intra = await fetchSeries(bucket, 'INTRADAY', '1D')
      setIntraday(intra)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'analytics-timeseries failed')
    } finally {
      setLoading(false)
    }
  }, [bucket, needsIntraday])

  useEffect(() => { fetchDaily() }, [fetchDaily])
  useEffect(() => { fetchIntraday() }, [fetchIntraday])

  // Reset caches when bucket changes so a stale series from a different
  // focused trade doesn't briefly flash while the new fetch is in flight.
  useEffect(() => {
    setDailyClose([])
    setIntraday([])
  }, [bucket])

  const pickForView = useCallback(
    (v: AnalyticsViewKey) => (v === 'INTRADAY' ? intraday : dailyClose),
    [intraday, dailyClose],
  )

  const refetch = useCallback(async () => {
    await (needsIntraday ? fetchIntraday() : fetchDaily())
  }, [fetchDaily, fetchIntraday, needsIntraday])

  return { dailyClose, intraday, loading, error, pickForView, refetch }
}
