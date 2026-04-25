export type TimeseriesMetricKey = 'notional' | 'risk' | 'trade_count' | 'fixed_rate'

export type TimeseriesViewKey = 'INTRADAY' | 'DAILY_CLOSE' | 'DAILY_OHLC' | 'VOLUME'

export type TimeseriesRangeKey = '1D' | '1W' | '1M' | '3M' | '6M' | '1Y' | 'CUSTOM'

export type TimeseriesGroupByKey = 'package' | 'tape_label' | 'trade_type' | 'tenor'

export type TimeseriesPoint = {
  ts: string
  value: number | null
  notional?: number | null
  risk?: number | null
  fixed_rate?: number | null
}

export type OhlcPoint = {
  date: string
  open: number | null
  high: number | null
  low: number | null
  close: number | null
}
