import { LISTED_VOL_LOOKBACK_SESSIONS } from './constants'
import type {
  ListedVolGridCell,
  ListedVolRange,
  ListedVolSeriesPoint,
  ListedVolSeriesStats
} from './types'

const RANGE_TO_DAYS: Record<Exclude<ListedVolRange, 'ALL'>, number> = {
  '1M': 31,
  '3M': 92,
  '6M': 183,
  '1Y': 366
}

function percentileRank(values: number[], latest: number) {
  if (!values.length) return null
  const lessOrEqual = values.filter((value) => value <= latest).length
  return (lessOrEqual / values.length) * 100
}

export function filterByRange(points: ListedVolSeriesPoint[], range: ListedVolRange) {
  if (range === 'ALL' || points.length === 0) return points
  const latestTimestamp = points[points.length - 1]?.timestamp ?? null
  if (!latestTimestamp) return points
  const cutoff = latestTimestamp - RANGE_TO_DAYS[range] * 24 * 60 * 60 * 1000
  return points.filter((point) => point.timestamp >= cutoff)
}

export function computeStats(values: Array<number | null>): ListedVolSeriesStats {
  const numeric = values.filter((value): value is number => value !== null && Number.isFinite(value))
  if (!numeric.length) {
    return {
      latest: null,
      mean: null,
      std: null,
      zScore: null,
      percentile: null,
      dailyChange: null
    }
  }
  const latest = numeric[numeric.length - 1] ?? null
  const mean = numeric.reduce((sum, value) => sum + value, 0) / numeric.length
  const variance =
    numeric.length > 1
      ? numeric.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (numeric.length - 1)
      : 0
  const std = variance > 0 ? Math.sqrt(variance) : 0
  const zScore =
    latest !== null && std > 0 && Number.isFinite(std)
      ? (latest - mean) / std
      : null
  const dailyChange =
    numeric.length > 1
      ? numeric[numeric.length - 1] - numeric[numeric.length - 2]
      : null
  return {
    latest,
    mean,
    std: std || null,
    zScore,
    percentile: latest === null ? null : percentileRank(numeric, latest),
    dailyChange
  }
}

export function buildGridMatrix(
  cells: ListedVolGridCell[],
  products: string[],
  expiries: string[]
) {
  const cellMap = new Map(cells.map((cell) => [`${cell.product}_${cell.expiryLabel}`, cell]))
  return products.map((product) =>
    expiries.map((expiry) => cellMap.get(`${product}_${expiry}`) ?? null)
  )
}

export function computeCellHistoryStats(values: Array<number | null>) {
  const trimmed = values.slice(-LISTED_VOL_LOOKBACK_SESSIONS)
  return computeStats(trimmed)
}
