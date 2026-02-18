import type { TimeseriesMetricKey, TimeseriesViewKey } from './types'

export const POLL_INTERVAL_MS = 30_000
export const ROW_ESTIMATE_PX = 44
export const EMPTY_VALUE = '--'

export const COLUMN_DEFS = [
  { key: 'event_action', label: 'Action', width: 120 },
  { key: 'package_type', label: 'Package Type', width: 150 },
  { key: 'time', label: 'Time', width: 180 },
  { key: 'platform', label: 'Platform', width: 140 },
  { key: 'metric', label: 'Metric', width: 130 },
  { key: 'label', label: 'Trade Label', width: 360 }
] as const

export const METRIC_OPTIONS: Array<{
  key: 'notional' | 'risk'
  label: string
}> = [
  { key: 'notional', label: 'Notional' },
  { key: 'risk', label: 'Risk' }
]

export const TIMESERIES_METRICS: Array<{
  key: TimeseriesMetricKey
  label: string
  color: string
  decimals: number
}> = [
  { key: 'notional', label: 'Notional', color: '#22c55e', decimals: 0 },
  { key: 'risk', label: 'Risk', color: '#38bdf8', decimals: 0 },
  { key: 'fixed_rate', label: 'Fixed Rate', color: '#f59e0b', decimals: 5 },
  { key: 'trade_count', label: 'Trade Count', color: '#f97316', decimals: 0 }
]

export const TIMESERIES_VIEWS: Array<{ key: TimeseriesViewKey; label: string }> = [
  { key: 'INTRADAY', label: 'Intraday' },
  { key: 'DAILY_CLOSE', label: 'Daily Close' },
  { key: 'DAILY_OHLC', label: 'Daily OHLC' }
]

export const DEFAULT_FORWARD_BOUNDARY = 1
export const DEFAULT_TENOR_BOUNDARY = 10
export const DEFAULT_FLOW_TOLERANCE = 0.25
