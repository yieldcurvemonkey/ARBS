// Fetches distribution bins + stats + percentile rows + recency for the
// analytics dock's Rarity tab from /api/usd-swaps-tape-v2/rarity.
//
// Phase 5 (analytics-fetching): SWR-backed internals. The bespoke
// `Map`-cache + AbortController scaffolding has moved into SWR's
// dedup + stale-while-revalidate behaviour, plus a route-local LRU
// + ETag emission on the server. Public return shape is unchanged so
// the TradeRarityTab consumer doesn't see any API change.
import { useMemo } from 'react'
import useSWR from 'swr'
import { TAPE_V2_API_BASE } from '../constants'
import type {
  DistributionStats,
  FocusedTrade,
  HistogramBin,
  MetricRow,
  RecencyBucket,
} from '../components/AnalyticsPanel/analytics-types'
import { rarityKey } from '@/lib/usd-swaps-tape-v2/analyticsCacheKeys'

type FocusedPercentile = { combined: number; custy: number; idb: number }

export type RarityBinMetric = 'fixed_rate' | 'dv01' | 'notional'

export interface UseRarityDataReturn {
  bins: HistogramBin[]
  // UX-02: server echoes the metric + bin width it chose so the
  // client renders axis labels and tooltips with the right units.
  binMetric: RarityBinMetric
  binWidth: number
  stats: DistributionStats
  binStats: DistributionStats
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

interface RarityResponse {
  bins?: HistogramBin[]
  binMetric?: RarityBinMetric
  binWidth?: number
  stats?: DistributionStats
  binStats?: DistributionStats
  metricRows?: MetricRow[]
  recency?: RecencyBucket | null
  focusedPercentile?: FocusedPercentile
}

export function buildRarityUrl(
  focused: FocusedTrade,
  opts: {
    lookback: number
    primaryTol: number
    sizeTol: number
    binMetric: RarityBinMetric
  },
): string {
  const q = new URLSearchParams({
    value: focused.tape_label ?? '',
    groupBy: 'tape_label',
    lookback: String(opts.lookback),
    primaryTol: String(opts.primaryTol),
    sizeTol: String(opts.sizeTol),
    binMetric: opts.binMetric,
  })
  const rate = focused.fixed_rate_bps
  const dv01 = focused.dv01_usd_per_bp
  const notional = focused.notional_usd
  if (rate != null) q.set('focusedRate', String(rate))
  // dv01 / notional are aggregated abs-sums across legs; an orphan
  // package with no leg data hits this hook with 0 / 0 and would
  // otherwise produce a bogus P0 percentile + "rank #N" reading.
  // Drop them when zero so the server treats the rarity row as
  // notional-unknown and emits null bucketRank instead.
  if (dv01 != null && dv01 > 0) q.set('focusedDv01', String(dv01))
  if (notional != null && notional > 0) q.set('focusedNotional', String(notional))
  return `${TAPE_V2_API_BASE}/rarity?${q.toString()}`
}

export function useRarityData(
  focused: FocusedTrade | null,
  opts: {
    lookback?: number
    primaryTol?: number
    sizeTol?: number
    binMetric?: RarityBinMetric
  } = {},
): UseRarityDataReturn {
  const lookback = opts.lookback ?? 90
  const primaryTol = opts.primaryTol ?? 2.0
  const sizeTol = opts.sizeTol ?? 0.25
  const requestedBinMetric: RarityBinMetric = opts.binMetric ?? 'fixed_rate'

  const enabled = focused != null && focused.tape_label != null

  const swrKey = useMemo(() => {
    if (!enabled) return null
    return rarityKey({
      bucket: `tape_label:${focused.tape_label}`,
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: {
        lookback,
        primaryTol,
        sizeTol,
        binMetric: requestedBinMetric,
        // The focused row's own metrics shape the response (focusedRate,
        // focusedDv01, focusedNotional change which percentile rows /
        // similar prints are computed) — pin them to the cache key.
        focusedRate: focused.fixed_rate_bps ?? null,
        focusedDv01: focused.dv01_usd_per_bp ?? null,
        focusedNotional: focused.notional_usd ?? null,
      },
    })
  }, [enabled, focused, lookback, primaryTol, sizeTol, requestedBinMetric])

  const url = useMemo(() => {
    if (!enabled) return null
    return buildRarityUrl(focused, {
      lookback,
      primaryTol,
      sizeTol,
      binMetric: requestedBinMetric,
    })
  }, [enabled, focused, lookback, primaryTol, sizeTol, requestedBinMetric])

  const { data, error, isLoading, mutate } = useSWR<RarityResponse>(
    swrKey,
    url ? () => fetch(url).then((r) => r.json()) : null,
  )

  const bins = data?.bins ?? []
  const responseMetric: RarityBinMetric =
    data?.binMetric === 'dv01' || data?.binMetric === 'notional'
      ? data.binMetric
      : 'fixed_rate'

  return {
    bins,
    binMetric: responseMetric,
    binWidth:
      typeof data?.binWidth === 'number' && data.binWidth > 0
        ? data.binWidth
        : 1,
    stats: data?.stats ?? EMPTY_STATS,
    binStats: data?.binStats ?? data?.stats ?? EMPTY_STATS,
    metricRows: data?.metricRows ?? [],
    recency: data?.recency ?? null,
    focusedPercentile: data?.focusedPercentile ?? EMPTY_PCT,
    loading: isLoading,
    error: error ? (error instanceof Error ? error.message : String(error)) : null,
    refetch: () => {
      mutate()
    },
  }
}
