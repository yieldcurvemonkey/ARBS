import { fmtDv01Compact } from './analytics-format'
import type {
  DistributionStats,
  FocusedTrade,
  HistogramBin,
} from './analytics-types'

export type RarityBinMetric = 'fixed_rate' | 'dv01' | 'notional'

export function focusedHistogramValue(
  focused: FocusedTrade,
  metric: RarityBinMetric,
): number {
  if (metric === 'dv01') return focused.dv01_usd_per_bp
  if (metric === 'notional') return focused.notional_usd / 1e6
  return focused.fixed_rate_bps
}

export function formatHistogramValue(
  value: number | null | undefined,
  metric: RarityBinMetric,
): string {
  if (value == null || Number.isNaN(value)) return '-'
  if (metric === 'dv01') return fmtDv01Compact(value)
  if (metric === 'notional') return value >= 100 ? value.toFixed(0) : value.toFixed(1)
  return value.toFixed(1)
}

export function findFocusedHistogramBin(
  bins: HistogramBin[],
  focusedValue: number,
): HistogramBin | undefined {
  return bins.find((b, i) => {
    const isLast = i === bins.length - 1
    return (
      focusedValue >= b.binStart &&
      (isLast ? focusedValue <= b.binEnd : focusedValue < b.binEnd)
    )
  })
}

export function statsForHistogram(
  stats: DistributionStats,
  fallback: DistributionStats,
): DistributionStats {
  return stats.count > 0 ? stats : fallback
}
