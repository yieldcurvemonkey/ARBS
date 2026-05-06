// ABOUTME: Debounced prefetch hook for the analytics dock. On row
// hover (with 150ms debounce), prefetches timeseries / rarity /
// extremes via SWR's mutate so a subsequent click renders instantly.
// Behind feature flag NEXT_PUBLIC_ENABLE_HOVER_PREFETCH (default on).
//
// Consumed by TradeTapeTable's onMouseEnter/onMouseLeave per row;
// the dock click handler still calls the SWR-backed hooks directly,
// so a prefetch is purely a cache warmer — never sets state.
import { useCallback, useEffect, useRef } from 'react'
import { unstable_serialize, useSWRConfig, type Key } from 'swr'
import {
  timeseriesKey,
  rarityKey,
  extremesKey,
} from '@/lib/usd-swaps-tape-v2/analyticsCacheKeys'
import { TAPE_V2_API_BASE } from '../constants'
import {
  RARITY_DEFAULT_STATE,
  RARITY_PREFS_STORAGE_KEY,
} from '../components/AnalyticsPanel/constants'
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

// Read the same localStorage key AnalyticsPanel uses so the prefetch's
// rarity URL matches the dock-hook's rarity URL byte-for-byte. Without
// this the prefetch would use one binMetric default while the dock
// uses another → two cache entries for the same row → 2x rarity
// requests on first row click.
function readPersistedRarityDefaults(): {
  binMetric: 'fixed_rate' | 'dv01' | 'notional'
  primaryTol: number
  sizeTol: number
} {
  const fallback = {
    binMetric:
      RARITY_DEFAULT_STATE.histogramMetric === 'dv01'
        ? ('dv01' as const)
        : RARITY_DEFAULT_STATE.histogramMetric === 'notional'
          ? ('notional' as const)
          : ('fixed_rate' as const),
    primaryTol: RARITY_DEFAULT_STATE.primaryTol,
    sizeTol: RARITY_DEFAULT_STATE.sizeTol,
  }
  if (typeof window === 'undefined') return fallback
  try {
    const raw = window.localStorage.getItem(RARITY_PREFS_STORAGE_KEY)
    if (!raw) return fallback
    const parsed = JSON.parse(raw) as {
      histogramMetric?: 'fixed_rate' | 'dv01' | 'notional'
      primaryTol?: number
      sizeTol?: number
    }
    return {
      binMetric:
        parsed.histogramMetric === 'dv01'
          ? 'dv01'
          : parsed.histogramMetric === 'notional'
            ? 'notional'
            : parsed.histogramMetric === 'fixed_rate'
              ? 'fixed_rate'
              : fallback.binMetric,
      primaryTol:
        typeof parsed.primaryTol === 'number' ? parsed.primaryTol : fallback.primaryTol,
      sizeTol: typeof parsed.sizeTol === 'number' ? parsed.sizeTol : fallback.sizeTol,
    }
  } catch {
    return fallback
  }
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

  const persisted = readPersistedRarityDefaults()
  const range = options.range ?? '1Y'
  const view = options.view ?? 'DAILY_CLOSE'
  const groupBy = options.groupBy ?? 'tape_label'
  const rarityLookback = options.rarity?.lookback ?? 90
  const rarityPrimaryTol = options.rarity?.primaryTol ?? persisted.primaryTol
  const raritySizeTol = options.rarity?.sizeTol ?? persisted.sizeTol
  const rarityBinMetric: 'fixed_rate' | 'dv01' | 'notional' =
    options.rarity?.binMetric ?? persisted.binMetric
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
          // Mirror the dock-hook default so prefetch and the first
          // dock fetch hash to the same cache slot. Without this,
          // the dock fires a fresh request on row click even though
          // hover prefetched the right URL.
          options: { removeZeroRates: true },
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

        const fireIfMissing = (key: Key, url: string) => {
          // SWR stores cache entries under a stable-hash of the tuple
          // key, NOT the tuple itself. Serialise here so cache.get
          // looks up under the same string SWR uses internally; without
          // this the prefetch always misses, fires its own fetch, and
          // races the dock-hook's fetch on first row click.
          const stringKey = unstable_serialize(key)
          const cacheGet = (cache as { get: (k: string) => unknown }).get
          const existing = cacheGet ? cacheGet.call(cache, stringKey) : undefined
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
