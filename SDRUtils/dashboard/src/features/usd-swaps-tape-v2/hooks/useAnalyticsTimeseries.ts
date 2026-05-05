// Fetches pre-aggregated daily / intraday series for the analytics dock
// from /api/usd-swaps-tape-v2/analytics-timeseries. Lazy-loaded per
// view: intraday payload only fires when the user actually switches to
// the intraday tab, and daily loads don't re-run on view-only changes.
//
// Phase 5 (analytics-fetching): SWR-backed internals; the bespoke
// in-memory Map cache + AbortController scaffolding is gone — caching
// flows through SwrFetcher (ETag, 304 reuse) and the route LRU.
import { useCallback, useMemo } from 'react'
import useSWR from 'swr'
import { TAPE_V2_API_BASE } from '../constants'
import type {
  AnalyticsGroupBy,
  AnalyticsRangeKey,
  AnalyticsViewKey,
  FocusedTrade,
  TimeseriesPointAug,
} from '../components/AnalyticsPanel/analytics-types'
import { timeseriesKey } from '@/lib/usd-swaps-tape-v2/analyticsCacheKeys'

export interface UseAnalyticsTimeseriesReturn {
  dailyClose: TimeseriesPointAug[]
  intraday: TimeseriesPointAug[]
  loading: boolean
  error: string | null
  pickForView: (view: AnalyticsViewKey) => TimeseriesPointAug[]
  refetch: () => void
}

export type AnalyticsTimeseriesOptions = {
  useGrossDv01?: boolean
  excludeLargeCusty?: boolean
  // Phase 4: optional groupBy override. Defaults to tape_label to keep
  // backwards-compatible behaviour for existing callers; pass
  // 'canonical' to bucket by canonical_underlier_key (paired with a
  // canonical bucket key as the value via groupValueOverride).
  groupBy?: AnalyticsGroupBy
  groupValueOverride?: string | null
}

interface TimeseriesResponse {
  points?: TimeseriesPointAug[]
  count?: number
  view?: string
  range?: string
}

function buildAnalyticsTimeseriesQuery(
  bucket: string,
  view: 'INTRADAY' | 'DAILY_CLOSE',
  range: AnalyticsRangeKey,
  opts: AnalyticsTimeseriesOptions = {},
): URLSearchParams {
  const groupBy: AnalyticsGroupBy = opts.groupBy ?? 'tape_label'
  // When the caller pivots to canonical bucketing, the meaningful
  // identifier is the canonical key (e.g. "USD/SOFR-OIS/COMPOUND"),
  // not the focused trade's tape_label. Allow an explicit override.
  const value = opts.groupValueOverride ?? bucket
  return new URLSearchParams({
    value,
    view,
    range,
    groupBy,
    useGrossDv01: opts.useGrossDv01 ? 'true' : 'false',
    excludeLargeCusty: opts.excludeLargeCusty === false ? 'false' : 'true',
  })
}

export function buildTimeseriesUrl(
  bucket: string,
  view: 'INTRADAY' | 'DAILY_CLOSE',
  range: AnalyticsRangeKey,
  opts: AnalyticsTimeseriesOptions = {},
): string {
  const q = buildAnalyticsTimeseriesQuery(bucket, view, range, opts)
  return `${TAPE_V2_API_BASE}/analytics-timeseries?${q.toString()}`
}

export function useAnalyticsTimeseries(
  focused: FocusedTrade | null,
  range: AnalyticsRangeKey = '1Y',
  view: AnalyticsViewKey = 'DAILY_CLOSE',
  opts: AnalyticsTimeseriesOptions = {},
): UseAnalyticsTimeseriesReturn {
  const bucket = focused?.tape_label ?? null
  const needsIntraday = view === 'INTRADAY'
  const useGrossDv01 = Boolean(opts.useGrossDv01)
  const excludeLargeCusty = opts.excludeLargeCusty !== false
  const groupBy: AnalyticsGroupBy = opts.groupBy ?? 'tape_label'
  const groupValueOverride = opts.groupValueOverride ?? null

  // Daily: always fetched when bucket is set + view !== INTRADAY.
  const dailyEnabled = bucket != null && !needsIntraday
  const dailyKey = useMemo(() => {
    if (!dailyEnabled) return null
    return timeseriesKey({
      bucket: groupValueOverride ?? bucket!,
      view: 'DAILY_CLOSE',
      range,
      groupBy,
      groupValueOverride,
      // useGrossDv01 + excludeLargeCusty are dropped from the key by
      // analyticsCacheKeys.ORTHOGONAL_DISPLAY_OPTIONS so the cache
      // survives orthogonal-toggle changes.
      options: { useGrossDv01, excludeLargeCusty },
    })
  }, [dailyEnabled, bucket, groupValueOverride, range, groupBy, useGrossDv01, excludeLargeCusty])

  const dailyUrl = useMemo(() => {
    if (!dailyEnabled) return null
    return buildTimeseriesUrl(bucket!, 'DAILY_CLOSE', range, {
      useGrossDv01,
      excludeLargeCusty,
      groupBy,
      groupValueOverride,
    })
  }, [dailyEnabled, bucket, range, useGrossDv01, excludeLargeCusty, groupBy, groupValueOverride])

  const dailySwr = useSWR<TimeseriesResponse>(
    dailyKey,
    dailyUrl ? () => fetch(dailyUrl).then((r) => r.json()) : null,
  )

  // Intraday: lazy — only fires when view === 'INTRADAY'.
  const intradayEnabled = bucket != null && needsIntraday
  const intradayKey = useMemo(() => {
    if (!intradayEnabled) return null
    return timeseriesKey({
      bucket: groupValueOverride ?? bucket!,
      view: 'INTRADAY',
      range: '1D',
      groupBy,
      groupValueOverride,
      options: { useGrossDv01, excludeLargeCusty },
    })
  }, [intradayEnabled, bucket, groupValueOverride, groupBy, useGrossDv01, excludeLargeCusty])

  const intradayUrl = useMemo(() => {
    if (!intradayEnabled) return null
    return buildTimeseriesUrl(bucket!, 'INTRADAY', '1D', {
      useGrossDv01,
      excludeLargeCusty,
      groupBy,
      groupValueOverride,
    })
  }, [intradayEnabled, bucket, useGrossDv01, excludeLargeCusty, groupBy, groupValueOverride])

  const intradaySwr = useSWR<TimeseriesResponse>(
    intradayKey,
    intradayUrl ? () => fetch(intradayUrl).then((r) => r.json()) : null,
  )

  const dailyClose: TimeseriesPointAug[] = dailySwr.data?.points ?? []
  const intraday: TimeseriesPointAug[] = intradaySwr.data?.points ?? []

  const loading =
    (dailyEnabled && dailySwr.isLoading) ||
    (intradayEnabled && intradaySwr.isLoading)
  const error = (() => {
    const e = dailySwr.error ?? intradaySwr.error
    if (!e) return null
    return e instanceof Error ? e.message : String(e)
  })()

  const pickForView = useCallback(
    (v: AnalyticsViewKey) => (v === 'INTRADAY' ? intraday : dailyClose),
    [intraday, dailyClose],
  )

  const refetch = useCallback(() => {
    if (dailyEnabled) dailySwr.mutate()
    if (intradayEnabled) intradaySwr.mutate()
  }, [dailyEnabled, intradayEnabled, dailySwr, intradaySwr])

  return { dailyClose, intraday, loading, error, pickForView, refetch }
}

export const __internal = { buildAnalyticsTimeseriesQuery, buildTimeseriesUrl }
