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
  // Drops reported-0 fixed_rate prints from the bucket aggregation
  // (compression / off-market markers). Server defaults to true when
  // the param is absent so the in-flight rollout doesn't break
  // existing clients.
  removeZeroRates?: boolean
}

interface TimeseriesResponse {
  points?: TimeseriesPointAug[]
  count?: number
  view?: string
  range?: string
}

// Phase 5 (orthogonal-payload split): the server returns extra fields
// alongside TimeseriesPointAug so the client can re-derive the legacy
// idbDv01 / custyDv01 etc. without re-fetching.
interface PointVariants {
  idbDv01_gross?: number
  idbDv01_net?: number
  custyDv01_gross?: number
  custyDv01_net?: number
  custyDv01_gross_excl_large?: number
  custyDv01_net_excl_large?: number
  custyNotional_raw?: number
  custyNotional_excl_large?: number
  custyPrints_raw?: number
  custyPrints_excl_large?: number
}

function safeNumLocal(
  primary: number | null | undefined,
  fallback: number | null | undefined = 0,
): number {
  if (typeof primary === 'number' && Number.isFinite(primary)) return primary
  if (typeof fallback === 'number' && Number.isFinite(fallback)) return fallback
  return 0
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
  // Phase 5 (orthogonal-payload split): useGrossDv01 +
  // excludeLargeCusty are display-only toggles; the server returns the
  // full (gross|net) × (raw|excl-large) variant grid in a single
  // payload regardless. Drop them from the URL so the dock-hook +
  // hover-prefetch hooks build identical URLs and one in-flight fetch
  // can satisfy both code paths.
  //
  // removeZeroRates DOES change which rows the warehouse aggregation
  // sees, so it stays in the URL and in the SWR cache key.
  const params = new URLSearchParams({
    value,
    view,
    range,
    groupBy,
  })
  if (opts.removeZeroRates === false) {
    params.set('removeZeroRates', 'false')
  }
  return params
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
  const removeZeroRates = opts.removeZeroRates !== false

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
      // survives orthogonal-toggle changes. removeZeroRates DOES
      // change the warehouse result, so it MUST stay in the key.
      options: { useGrossDv01, excludeLargeCusty, removeZeroRates },
    })
  }, [dailyEnabled, bucket, groupValueOverride, range, groupBy, useGrossDv01, excludeLargeCusty, removeZeroRates])

  const dailyUrl = useMemo(() => {
    if (!dailyEnabled) return null
    return buildTimeseriesUrl(bucket!, 'DAILY_CLOSE', range, {
      useGrossDv01,
      excludeLargeCusty,
      groupBy,
      groupValueOverride,
      removeZeroRates,
    })
  }, [dailyEnabled, bucket, range, useGrossDv01, excludeLargeCusty, groupBy, groupValueOverride, removeZeroRates])

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
      options: { useGrossDv01, excludeLargeCusty, removeZeroRates },
    })
  }, [intradayEnabled, bucket, groupValueOverride, groupBy, useGrossDv01, excludeLargeCusty, removeZeroRates])

  const intradayUrl = useMemo(() => {
    if (!intradayEnabled) return null
    return buildTimeseriesUrl(bucket!, 'INTRADAY', '1D', {
      useGrossDv01,
      excludeLargeCusty,
      groupBy,
      groupValueOverride,
      removeZeroRates,
    })
  }, [intradayEnabled, bucket, useGrossDv01, excludeLargeCusty, groupBy, groupValueOverride, removeZeroRates])

  const intradaySwr = useSWR<TimeseriesResponse>(
    intradayKey,
    intradayUrl ? () => fetch(intradayUrl).then((r) => r.json()) : null,
  )

  // Phase 5 (orthogonal-payload split): the server returns the full
  // variant grid; we re-project idbDv01 / custyDv01 / custyNotional /
  // custyPrints from the variant fields based on the *current* toggle
  // state. This means flipping useGrossDv01 / excludeLargeCusty
  // produces a re-render but no network request — the SWR cache key
  // stays stable.
  function projectPoint(
    p: TimeseriesPointAug & PointVariants,
  ): TimeseriesPointAug {
    const idbDv01 = useGrossDv01
      ? safeNumLocal(p.idbDv01_gross, p.idbDv01)
      : safeNumLocal(p.idbDv01_net, p.idbDv01)
    const custyDv01 = excludeLargeCusty
      ? useGrossDv01
        ? safeNumLocal(p.custyDv01_gross_excl_large, p.custyDv01)
        : safeNumLocal(p.custyDv01_net_excl_large, p.custyDv01)
      : useGrossDv01
        ? safeNumLocal(p.custyDv01_gross, p.custyDv01)
        : safeNumLocal(p.custyDv01_net, p.custyDv01)
    const custyNotional = excludeLargeCusty
      ? safeNumLocal(p.custyNotional_excl_large, p.custyNotional)
      : safeNumLocal(p.custyNotional_raw, p.custyNotional)
    const custyPrints = excludeLargeCusty
      ? safeNumLocal(p.custyPrints_excl_large, p.custyPrints)
      : safeNumLocal(p.custyPrints_raw, p.custyPrints)
    return {
      ...p,
      idbDv01,
      custyDv01,
      custyNotional,
      custyPrints,
    }
  }

  const dailyClose: TimeseriesPointAug[] = (dailySwr.data?.points ?? []).map(
    (p) => projectPoint(p as TimeseriesPointAug & PointVariants),
  )
  const intraday: TimeseriesPointAug[] = (intradaySwr.data?.points ?? []).map(
    (p) => projectPoint(p as TimeseriesPointAug & PointVariants),
  )

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
