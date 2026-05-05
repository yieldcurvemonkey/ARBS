// ABOUTME: Debounced prefetch hook for the analytics dock. On row
// hover (with 150ms debounce), prefetches timeseries / rarity /
// extremes via SWR's mutate so a subsequent click renders instantly.
// Behind feature flag NEXT_PUBLIC_ENABLE_HOVER_PREFETCH (default on).
//
// Consumed by TradeTapeTable's onMouseEnter/onMouseLeave per row;
// the dock click handler still calls the SWR-backed hooks directly,
// so a prefetch is purely a cache warmer — never sets state.
import { useCallback, useEffect, useRef } from 'react'
import { useSWRConfig } from 'swr'
import {
  timeseriesKey,
  rarityKey,
  extremesKey,
} from '@/lib/usd-swaps-tape-v2/analyticsCacheKeys'
import { TAPE_V2_API_BASE } from '../constants'
import type { UsdSwapTapeRow } from '../types/trade.types'
import { normalizeFocusedTrade } from './useFocusedTrade'

const DEBOUNCE_MS = 150

interface PrefetchOptions {
  range?: '1D' | '1W' | '1M' | '1Y' | 'CUSTOM'
  view?: 'INTRADAY' | 'DAILY_CLOSE' | 'DAILY_OHLC' | 'VOLUME'
  groupBy?: string
  rarity?: { lookback?: number; primaryTol?: number; sizeTol?: number; binMetric?: 'fixed_rate' | 'dv01' | 'notional' }
  extremes?: { primaryTol?: number; sizeTol?: number }
}

function isPrefetchEnabled(): boolean {
  return process.env.NEXT_PUBLIC_ENABLE_HOVER_PREFETCH !== 'false'
}

/**
 * Returns onHover / onLeave callbacks for row prefetch. Hover starts
 * a 150 ms debounce; if the hover stays on the same row past the
 * deadline, three prefetch fetches fire silently (timeseries +
 * rarity + extremes). Hover-out before the deadline cancels.
 *
 * The hook does not subscribe to the analytics state; it computes
 * cache keys + URLs from the row alone using sensible defaults so a
 * row hovered before any other interaction warms the dock's "open
 * to default range / view / groupBy" path. Subsequent toggles in
 * the dock are served by the same cache entry (orthogonal options
 * are stripped).
 */
export function useAnalyticsPrefetch(options: PrefetchOptions = {}) {
  const { mutate, cache } = useSWRConfig()
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const enabled = isPrefetchEnabled()

  const range = options.range ?? '1Y'
  const view = options.view ?? 'DAILY_CLOSE'
  const groupBy = options.groupBy ?? 'tape_label'
  const rarityLookback = options.rarity?.lookback ?? 90
  const rarityPrimaryTol = options.rarity?.primaryTol ?? 2
  const raritySizeTol = options.rarity?.sizeTol ?? 0.25
  const rarityBinMetric: 'fixed_rate' | 'dv01' | 'notional' =
    options.rarity?.binMetric ?? 'fixed_rate'
  const extremesPrimaryTol = options.extremes?.primaryTol ?? 2
  const extremesSizeTol = options.extremes?.sizeTol ?? 0.25

  const onHover = useCallback(
    (row: UsdSwapTapeRow | null) => {
      if (!enabled || !row) return
      if (timer.current) clearTimeout(timer.current)

      timer.current = setTimeout(() => {
        const focused = normalizeFocusedTrade(row)
        if (!focused) return
        const bucket = focused.tape_label
        if (!bucket) return

        const tsKey = timeseriesKey({
          bucket,
          view,
          range,
          groupBy,
          groupValueOverride: null,
          options: {},
        })
        const rKey = rarityKey({
          bucket: `tape_label:${bucket}`,
          groupBy,
          groupValueOverride: null,
          options: {
            lookback: rarityLookback,
            primaryTol: rarityPrimaryTol,
            sizeTol: raritySizeTol,
            binMetric: rarityBinMetric,
            focusedRate: focused.fixed_rate_bps ?? null,
            focusedDv01: focused.dv01_usd_per_bp ?? null,
            focusedNotional: focused.notional_usd ?? null,
          },
        })
        const eKey = extremesKey({
          bucket: `tape_label:${bucket}`,
          groupBy,
          groupValueOverride: null,
          options: {
            primaryTol: extremesPrimaryTol,
            sizeTol: extremesSizeTol,
            focusedRate: focused.fixed_rate_bps ?? null,
            focusedNotional: focused.notional_usd ?? null,
          },
        })

        // Fire prefetch only when entry is missing — SWR's dedup +
        // the route LRU keep this cheap.
        const tsParams = new URLSearchParams({
          value: bucket,
          view,
          range,
          groupBy,
        })
        const tsUrl = `${TAPE_V2_API_BASE}/analytics-timeseries?${tsParams.toString()}`

        const rParams = new URLSearchParams({
          value: bucket,
          groupBy,
          lookback: String(rarityLookback),
          primaryTol: String(rarityPrimaryTol),
          sizeTol: String(raritySizeTol),
          binMetric: rarityBinMetric,
        })
        if (focused.fixed_rate_bps != null)
          rParams.set('focusedRate', String(focused.fixed_rate_bps))
        if (focused.dv01_usd_per_bp != null && focused.dv01_usd_per_bp > 0)
          rParams.set('focusedDv01', String(focused.dv01_usd_per_bp))
        if (focused.notional_usd != null && focused.notional_usd > 0)
          rParams.set('focusedNotional', String(focused.notional_usd))
        const rUrl = `${TAPE_V2_API_BASE}/rarity?${rParams.toString()}`

        const eParams = new URLSearchParams({
          value: bucket,
          groupBy,
          primaryTol: String(extremesPrimaryTol),
          sizeTol: String(extremesSizeTol),
        })
        if (focused.fixed_rate_bps != null)
          eParams.set('focusedRate', String(focused.fixed_rate_bps))
        if (focused.notional_usd != null && focused.notional_usd > 0)
          eParams.set('focusedNotional', String(focused.notional_usd))
        const eUrl = `${TAPE_V2_API_BASE}/extremes?${eParams.toString()}`

        const fireIfMissing = (key: unknown, url: string) => {
          // SWRConfig.cache typed as Map-like; use a permissive cast.
          const cacheGet = (cache as { get: (k: unknown) => unknown }).get
          const existing = cacheGet ? cacheGet.call(cache, key) : undefined
          if (existing) return
          mutate(
            key,
            async () => {
              const res = await fetch(url)
              if (!res.ok) throw new Error(`prefetch ${res.status}`)
              return res.json()
            },
            { revalidate: false },
          ).catch(() => {
            // silent — prefetch is best-effort.
          })
        }

        fireIfMissing(tsKey, tsUrl)
        fireIfMissing(rKey, rUrl)
        fireIfMissing(eKey, eUrl)
      }, DEBOUNCE_MS)
    },
    [
      enabled,
      mutate,
      cache,
      view,
      range,
      groupBy,
      rarityLookback,
      rarityPrimaryTol,
      raritySizeTol,
      rarityBinMetric,
      extremesPrimaryTol,
      extremesSizeTol,
    ],
  )

  const onLeave = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
  }, [])

  // Cleanup timer on unmount.
  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current)
    }
  }, [])

  return { onHover, onLeave }
}

export const __testing = { DEBOUNCE_MS, isPrefetchEnabled }
