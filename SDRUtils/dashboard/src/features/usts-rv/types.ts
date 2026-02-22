export type UstsRvValueColumn =
  | 'mmss'
  | 'ytm'
  | 'clean_price'
  | 'dirty_price'
  | 'mdur'
  | 'carry_bps'
  | 'roll_bps'
  | 'carry_and_roll_bps'
  | 'coupon'

export type UstsRvXColumn = 'ttm' | 'mdur'
export type UstsRvDataMode = 'eod_live' | 'intraday_live'

export type UstsRvSplineMethod = 'bspline' | 'loess'

export type UstsRvSplineConfigRequest = {
  id: string
  enabled?: boolean
  name?: string
  method: UstsRvSplineMethod
  valueColumn: UstsRvValueColumn
  xColumn?: UstsRvXColumn
  color?: string
  lineWidth?: number
  degree?: number
  knots?: number[]
  frac?: number
  it?: number
  delta?: number
  excludeRanks?: number[]
  pointCount?: number
  xMin?: number | null
  xMax?: number | null
}

export type UstsRvSnapshotRequest = {
  asOf?: string
  asOfTime?: string
  minTtm?: number
  xColumn?: UstsRvXColumn
  curveName?: string
  dataMode?: UstsRvDataMode
  includeValues?: UstsRvValueColumn[]
  splineConfigs?: UstsRvSplineConfigRequest[]
}

export type UstsRvPoint = {
  cusip: string
  ust_label: string | null
  oi: string | null
  rank: number | null
  ttm: number | null
  mdur: number | null
  ytm: number | null
  mmss: number | null
  clean_price: number | null
  dirty_price: number | null
  coupon: number | null
  carry_bps: number | null
  roll_bps: number | null
  carry_and_roll_bps: number | null
  carry_1m_bps: number | null
  roll_1m_bps: number | null
  carry_and_roll_1m_bps: number | null
  carry_2m_bps: number | null
  roll_2m_bps: number | null
  carry_and_roll_2m_bps: number | null
  carry_3m_bps: number | null
  roll_3m_bps: number | null
  carry_and_roll_3m_bps: number | null
  carry_6m_bps: number | null
  roll_6m_bps: number | null
  carry_and_roll_6m_bps: number | null
  swap_carry_bps: number | null
  swap_roll_bps: number | null
  swap_carry_and_roll_bps: number | null
  swap_carry_1m_bps: number | null
  swap_roll_1m_bps: number | null
  swap_carry_and_roll_1m_bps: number | null
  swap_carry_2m_bps: number | null
  swap_roll_2m_bps: number | null
  swap_carry_and_roll_2m_bps: number | null
  swap_carry_3m_bps: number | null
  swap_roll_3m_bps: number | null
  swap_carry_and_roll_3m_bps: number | null
  swap_carry_6m_bps: number | null
  swap_roll_6m_bps: number | null
  swap_carry_and_roll_6m_bps: number | null
  mmss_carry_bps: number | null
  mmss_roll_bps: number | null
  mmss_carry_and_roll_bps: number | null
  mmss_carry_1m_bps: number | null
  mmss_roll_1m_bps: number | null
  mmss_carry_and_roll_1m_bps: number | null
  mmss_carry_2m_bps: number | null
  mmss_roll_2m_bps: number | null
  mmss_carry_and_roll_2m_bps: number | null
  mmss_carry_3m_bps: number | null
  mmss_roll_3m_bps: number | null
  mmss_carry_and_roll_3m_bps: number | null
  mmss_carry_6m_bps: number | null
  mmss_roll_6m_bps: number | null
  mmss_carry_and_roll_6m_bps: number | null
  issue_date: string | null
  maturity_date: string | null
  market_timestamp: string | null
}

export type UstsRvSplineSeries = {
  id: string
  name: string
  method: UstsRvSplineMethod
  valueColumn: string
  xColumn: string
  color: string | null
  lineWidth: number
  fitCount: number
  x: number[]
  y: number[]
  error: string | null
}

export type UstsRvSnapshotResponse = {
  requestedAsOf: string
  asOf: string
  requestedLive: boolean
  dataMode: UstsRvDataMode
  curveName: string
  xColumn: UstsRvXColumn | string
  includeValues: string[]
  availableValueColumns: string[]
  points: UstsRvPoint[]
  splineSeries: UstsRvSplineSeries[]
  meta: {
    asOf: string
    pointCount: number
    curveName: string
    warnings?: string[]
  }
}

export type UstsRvTimeseriesRequest = {
  asOf?: string
  curveName?: string
  dataMode?: UstsRvDataMode
  valueColumn: UstsRvValueColumn
  cusips: string[]
  startDate?: string
  endDate?: string
  startTime?: string
  endTime?: string
  lookbackDays?: number
}

export type UstsRvTimeseriesPoint = {
  asOf: string
  value: number | null
  snapshotTs: string | null
}

export type UstsRvTimeseriesSeries = {
  cusip: string
  ust_label: string | null
  oi: string | null
  rank: number | null
  points: UstsRvTimeseriesPoint[]
}

export type UstsRvTimeseriesResponse = {
  requestedAsOf: string
  asOf: string
  requestedLive: boolean
  dataMode: UstsRvDataMode
  curveName: string
  valueColumn: UstsRvValueColumn
  startDate: string | null
  endDate: string | null
  series: UstsRvTimeseriesSeries[]
  meta: {
    seriesCount: number
    totalPoints: number
    warnings?: string[]
  }
}
