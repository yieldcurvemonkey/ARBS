// Fetches all-time / 52w / 30d extremes + recent-similar trades for the
// analytics dock's Traded Levels tab from /api/usd-swaps-tape-v2/extremes.
//
// Phase 5 (analytics-fetching): SWR-backed internals; bespoke
// AbortController + setState loop replaced. Public return shape
// unchanged so TradedLevelsTab sees no API change.
import { useMemo } from 'react'
import useSWR from 'swr'
import { TAPE_V2_API_BASE } from '../constants'
import type {
  ExtremeRow,
  FocusedTrade,
  RecentSimilarRow,
} from '../components/AnalyticsPanel/analytics-types'
import { extremesKey } from '@/lib/usd-swaps-tape-v2/analyticsCacheKeys'

export interface UseExtremesDataReturn {
  extremes: ExtremeRow[]
  recentSimilar: RecentSimilarRow[]
  loading: boolean
  error: string | null
  refetch: () => void
}

interface ExtremesResponse {
  extremes?: ExtremeRow[]
  recentSimilar?: RecentSimilarRow[]
}

export function buildExtremesUrl(
  focused: FocusedTrade,
  opts: { primaryTol: number; sizeTol: number },
): string {
  const q = new URLSearchParams({
    value: focused.tape_label ?? '',
    groupBy: 'tape_label',
    primaryTol: String(opts.primaryTol),
    sizeTol: String(opts.sizeTol),
  })
  const rate = focused.fixed_rate_bps
  const notional = focused.notional_usd
  if (rate != null) q.set('focusedRate', String(rate))
  // Skip focusedNotional when the focused trade has no leg
  // notional (orphan packages aggregate to 0). Sending 0 would
  // narrow the size band to ±0% and silently filter out every
  // similar print.
  if (notional != null && notional > 0) q.set('focusedNotional', String(notional))
  return `${TAPE_V2_API_BASE}/extremes?${q.toString()}`
}

export function useExtremesData(
  focused: FocusedTrade | null,
  opts: { primaryTol?: number; sizeTol?: number } = {},
): UseExtremesDataReturn {
  const primaryTol = opts.primaryTol ?? 2.0
  const sizeTol = opts.sizeTol ?? 0.25

  const enabled = focused != null && focused.tape_label != null

  const swrKey = useMemo(() => {
    if (!enabled) return null
    return extremesKey({
      bucket: `tape_label:${focused.tape_label}`,
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: {
        primaryTol,
        sizeTol,
        focusedRate: focused.fixed_rate_bps ?? null,
        focusedNotional: focused.notional_usd ?? null,
      },
    })
  }, [enabled, focused, primaryTol, sizeTol])

  const url = useMemo(() => {
    if (!enabled) return null
    return buildExtremesUrl(focused, { primaryTol, sizeTol })
  }, [enabled, focused, primaryTol, sizeTol])

  const { data, error, isLoading, mutate } = useSWR<ExtremesResponse>(
    swrKey,
    url ? () => fetch(url).then((r) => r.json()) : null,
  )

  return {
    extremes: data?.extremes ?? [],
    recentSimilar: data?.recentSimilar ?? [],
    loading: isLoading,
    error: error ? (error instanceof Error ? error.message : String(error)) : null,
    refetch: () => {
      mutate()
    },
  }
}
