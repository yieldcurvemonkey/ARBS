// Returns distribution bins, stats, percentile rows, and recency info for
// the analytics dock's Rarity tab. Currently derives everything off a
// deterministic client-side mock so the dock previews immediately; swap
// the internals for a /api/usd-swaps-tape-v2/rarity fetch once the route
// exists without touching the UI consumers.
import { useMemo } from 'react'
import type {
  DistributionStats,
  FocusedTrade,
  HistogramBin,
  MetricRow,
  RecencyBucket,
} from '../components/AnalyticsPanel/analytics-types'
import {
  generateDistribution,
  generateRecency,
} from '../components/AnalyticsPanel/mock-analytics'

export interface UseRarityDataReturn {
  bins: HistogramBin[]
  stats: DistributionStats
  metricRows: MetricRow[]
  recency: RecencyBucket
  loading: boolean
  error: string | null
}

export function useRarityData(focused: FocusedTrade | null): UseRarityDataReturn {
  const { bins, stats, metricRows } = useMemo(
    () => generateDistribution(focused),
    [focused],
  )
  const recency = useMemo(() => generateRecency(focused), [focused])
  return { bins, stats, metricRows, recency, loading: false, error: null }
}
