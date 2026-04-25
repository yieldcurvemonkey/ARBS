// Fetches all-time / 52w / 30d extremes + recent-similar trades for the
// analytics dock's Traded Levels tab from /api/usd-swaps-tape-v2/extremes.
import { useCallback, useEffect, useState } from 'react'
import { TAPE_V2_API_BASE } from '../constants'
import type {
  ExtremeRow,
  FocusedTrade,
  RecentSimilarRow,
} from '../components/AnalyticsPanel/analytics-types'

export interface UseExtremesDataReturn {
  extremes: ExtremeRow[]
  recentSimilar: RecentSimilarRow[]
  loading: boolean
  error: string | null
  refetch: () => void
}

export function useExtremesData(
  focused: FocusedTrade | null,
  opts: { primaryTol?: number; sizeTol?: number } = {},
): UseExtremesDataReturn {
  const [extremes, setExtremes] = useState<ExtremeRow[]>([])
  const [recentSimilar, setRecentSimilar] = useState<RecentSimilarRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const bucket = focused?.tape_label ?? null
  const rate = focused?.fixed_rate_bps ?? null
  const notional = focused?.notional_usd ?? null
  const primaryTol = opts.primaryTol ?? 2.0
  const sizeTol = opts.sizeTol ?? 0.25

  const fetchData = useCallback(async () => {
    if (!bucket) {
      setExtremes([]); setRecentSimilar([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const q = new URLSearchParams({
        value: bucket,
        groupBy: 'tape_label',
        primaryTol: String(primaryTol),
        sizeTol: String(sizeTol),
      })
      if (rate != null) q.set('focusedRate', String(rate))
      if (notional != null) q.set('focusedNotional', String(notional))
      const res = await fetch(`${TAPE_V2_API_BASE}/extremes?${q}`)
      if (!res.ok) throw new Error(`extremes ${res.status}`)
      const data = await res.json()
      setExtremes(data.extremes ?? [])
      setRecentSimilar(data.recentSimilar ?? [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'extremes failed')
    } finally {
      setLoading(false)
    }
  }, [bucket, rate, notional, primaryTol, sizeTol])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  return { extremes, recentSimilar, loading, error, refetch: fetchData }
}
