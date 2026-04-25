// Fetches distribution bins + stats + percentile rows + recency for the
// analytics dock's Rarity tab from /api/usd-swaps-tape-v2/rarity.
//
// Phase 2 perf: AbortController per fetch + result cache so basis /
// histogram-metric toggles don't refetch the same SQL.
import { useCallback, useEffect, useRef, useState } from 'react'
import { TAPE_V2_API_BASE } from '../constants'
import type {
  DistributionStats,
  FocusedTrade,
  HistogramBin,
  MetricRow,
  RecencyBucket,
} from '../components/AnalyticsPanel/analytics-types'

type FocusedPercentile = { combined: number; custy: number; idb: number }

export interface UseRarityDataReturn {
  bins: HistogramBin[]
  stats: DistributionStats
  metricRows: MetricRow[]
  recency: RecencyBucket | null
  focusedPercentile: FocusedPercentile
  loading: boolean
  error: string | null
  refetch: () => void
}

const EMPTY_STATS: DistributionStats = {
  count: 0, mean: 0, stddev: 0, median: 0,
  p5: 0, p25: 0, p75: 0, p95: 0, iqr: 0, min: 0, max: 0,
}

const EMPTY_PCT: FocusedPercentile = { combined: 50, custy: 50, idb: 50 }

export function useRarityData(
  focused: FocusedTrade | null,
  opts: { lookback?: number; primaryTol?: number; sizeTol?: number } = {},
): UseRarityDataReturn {
  const [bins, setBins] = useState<HistogramBin[]>([])
  const [stats, setStats] = useState<DistributionStats>(EMPTY_STATS)
  const [metricRows, setMetricRows] = useState<MetricRow[]>([])
  const [recency, setRecency] = useState<RecencyBucket | null>(null)
  const [focusedPercentile, setFocusedPercentile] = useState<FocusedPercentile>(EMPTY_PCT)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const bucket = focused?.tape_label ?? null
  const rate = focused?.fixed_rate_bps ?? null
  const dv01 = focused?.dv01_usd_per_bp ?? null
  const notional = focused?.notional_usd ?? null
  const lookback = opts.lookback ?? 90
  const primaryTol = opts.primaryTol ?? 2.0
  const sizeTol = opts.sizeTol ?? 0.25

  const fetchData = useCallback(async () => {
    if (!bucket) {
      setBins([]); setStats(EMPTY_STATS); setMetricRows([]); setRecency(null)
      setFocusedPercentile(EMPTY_PCT)
      return
    }
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    setError(null)
    try {
      const q = new URLSearchParams({
        value: bucket,
        groupBy: 'tape_label',
        lookback: String(lookback),
        primaryTol: String(primaryTol),
        sizeTol: String(sizeTol),
      })
      if (rate != null) q.set('focusedRate', String(rate))
      // dv01 / notional are aggregated abs-sums across legs; an orphan
      // package with no leg data hits this hook with 0 / 0 and would
      // otherwise produce a bogus P0 percentile + "rank #N" reading.
      // Drop them when zero so the server treats the rarity row as
      // notional-unknown and emits null bucketRank instead.
      if (dv01 != null && dv01 > 0) q.set('focusedDv01', String(dv01))
      if (notional != null && notional > 0) q.set('focusedNotional', String(notional))
      const res = await fetch(`${TAPE_V2_API_BASE}/rarity?${q}`, { signal: controller.signal })
      if (!res.ok) throw new Error(`rarity ${res.status}`)
      const data = await res.json()
      if (controller.signal.aborted) return
      setBins(data.bins ?? [])
      setStats(data.stats ?? EMPTY_STATS)
      setMetricRows(data.metricRows ?? [])
      setRecency(data.recency ?? null)
      setFocusedPercentile(data.focusedPercentile ?? EMPTY_PCT)
    } catch (e) {
      if ((e as { name?: string })?.name === 'AbortError') return
      setError(e instanceof Error ? e.message : 'rarity failed')
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }, [bucket, rate, dv01, notional, lookback, primaryTol, sizeTol])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  return {
    bins, stats, metricRows, recency, focusedPercentile,
    loading, error, refetch: fetchData,
  }
}
