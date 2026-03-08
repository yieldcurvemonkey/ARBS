import type {
  CalibrationObservation,
  VolGridCell,
  VolGridHistoryRange,
  VolGridHistoryMetric,
  VolGridTradeTimelineMetric,
  VolGridTimeseriesPoint
} from './types'
import { buildNodeKey } from './utils'

const RANGE_TO_DAYS: Record<Exclude<VolGridHistoryRange, 'ALL'>, number> = {
  '1M': 31,
  '3M': 92,
  '6M': 183,
  '1Y': 366
}

export const VOL_GRID_HISTORY_RANGE_OPTIONS: VolGridHistoryRange[] = [
  '1M',
  '3M',
  '6M',
  '1Y',
  'ALL'
]

export const VOL_GRID_HISTORY_METRIC_OPTIONS: VolGridHistoryMetric[] = [
  'nvol',
  'dailyChange'
]

export const VOL_GRID_TRADE_TIMELINE_METRIC_OPTIONS: VolGridTradeTimelineMetric[] = [
  'bpvol',
  'notional',
  'premium'
]

export function filterTimeseriesByRange(
  points: VolGridTimeseriesPoint[],
  range: VolGridHistoryRange
) {
  if (range === 'ALL' || points.length === 0) return points
  const latestTimestamp = points[points.length - 1]?.timestamp ?? null
  if (!latestTimestamp) return points
  const cutoff = latestTimestamp - RANGE_TO_DAYS[range] * 24 * 60 * 60 * 1000
  return points.filter((point) => point.timestamp >= cutoff)
}

export function getHistoryMetricValue(
  point: VolGridTimeseriesPoint,
  metric: VolGridHistoryMetric
) {
  if (metric === 'dailyChange') return point.dailyChange
  return point.nvol
}

export function filterTradeHistoryByRange(
  trades: CalibrationObservation[],
  range: VolGridHistoryRange
) {
  if (range === 'ALL' || trades.length === 0) return trades
  const latestTimestamp = trades[0]?.executionTimestamp ?? null
  if (!latestTimestamp) return trades
  const cutoff = latestTimestamp - RANGE_TO_DAYS[range] * 24 * 60 * 60 * 1000
  return trades.filter((trade) => trade.executionTimestamp >= cutoff)
}

export function getTradeTimelineMetricValue(
  trade: CalibrationObservation,
  metric: VolGridTradeTimelineMetric
) {
  if (metric === 'premium') return trade.premium
  if (metric === 'notional') return trade.notional
  return trade.bpvolYr
}

export function formatTradeTimelineMetricLabel(metric: VolGridTradeTimelineMetric) {
  if (metric === 'premium') return 'Premium'
  if (metric === 'notional') return 'Notional'
  return 'BPVol'
}

export function buildSurfaceMatrix(
  cells: VolGridCell[],
  expiries: string[],
  tenors: string[]
) {
  const cellMap = new Map(cells.map((cell) => [cell.nodeKey, cell]))
  const z = expiries.map((expiry) =>
    tenors.map((tenor) => cellMap.get(buildNodeKey(expiry, tenor))?.atmfVol ?? null)
  )
  const hoverText = expiries.map((expiry) =>
    tenors.map((tenor) => `${expiry}x${tenor}`)
  )
  return { z, hoverText }
}
