// ---------------------------------------------------------------------------
// USTF Vol Analytics – shared types
// ---------------------------------------------------------------------------

export type UstfProduct = 'TU' | 'FV' | 'TY' | 'TN' | 'US' | 'UL'
export type SwaptionTail = '2Y' | '5Y' | '7Y' | '10Y' | '20Y' | '30Y'
export type UstfExpiry = '1W' | '2W' | '1M' | '2M' | '3M' | '6M'
export type SwaptionExpiry = '1M' | '3M' | '6M' | '1Y'
export type TimeRange = '1M' | '3M' | '6M' | '1Y' | 'ALL'
export type AssetType = 'ustf' | 'swaption'
export type SmileXAxis = 'delta' | 'strike_offset_bps'
export type TimeseriesMode = 'overlay' | 'spread'
export type DashboardTab = 'timeseries' | 'term-structure' | 'smile'
export type ListedOtmSide = 'call' | 'put'
export type SwaptionOtmSide = 'payer' | 'receiver'
export type OtmSide = ListedOtmSide | SwaptionOtmSide

export type SeriesVolMetric =
  | { kind: 'atm' }
  | { kind: 'delta_otm'; side: OtmSide; delta: number }
  | { kind: 'strike_offset_otm'; side: OtmSide; offsetBps: number }

// ---------------------------------------------------------------------------
// Timeseries
// ---------------------------------------------------------------------------

export type SeriesConfig = {
  type: AssetType
  product?: UstfProduct
  expiry: string
  tail?: SwaptionTail
  volMetric?: SeriesVolMetric
}

export type TimeseriesAxis = 'y' | 'y2'

export type SeriesStats = {
  latest: number | null
  mean: number | null
  min: number | null
  max: number | null
  stdev: number | null
  zScore: number | null
  count: number
}

export type TimeseriesPoint = {
  date: string
  series1: number | null
  series2: number | null
  spread: number | null
}

export type TimeseriesResponse = {
  series1Label: string
  series2Label: string | null
  points: TimeseriesPoint[]
  stats: {
    series1: SeriesStats
    series2: SeriesStats | null
    spread: SeriesStats | null
  }
}

export type UstfTimeseriesSeriesPoint = {
  asOf: string
  value: number | null
}

export type UstfTimeseriesSeries = {
  id: string
  label: string
  config: SeriesConfig
  points: UstfTimeseriesSeriesPoint[]
  stats: SeriesStats
}

export type UstfTimeseriesMultiResponse = {
  startDate: string | null
  endDate: string | null
  asOfDate: string | null
  series: UstfTimeseriesSeries[]
  warnings: string[]
}

export type ComparisonSnapshotRow = {
  pairLabel: string
  asOfDate: string | null
  updatedAt: string | null
  listedLabel: string
  otcLabel: string
  listedVol: number | null
  otcVol: number | null
  spread: number | null
  spreadZScore: number | null
}

export type ComparisonSnapshotResponse = {
  latestDate: string | null
  latestUpdatedAt: string | null
  rows: ComparisonSnapshotRow[]
}

// ---------------------------------------------------------------------------
// Term Structure
// ---------------------------------------------------------------------------

export type TermStructureDateSlice = {
  date: string
  points: Array<{
    label: string
    vol: number | null
  }>
}

export type TermStructureResponse = {
  assetType: AssetType
  expiry: string
  strikeOffsetBps: number
  dates: TermStructureDateSlice[]
}

// ---------------------------------------------------------------------------
// Vol Smile
// ---------------------------------------------------------------------------

export type SmilePoint = {
  x: number
  vol: number
}

export type SabrParams = {
  alpha: number
  beta: number
  rho: number
  nu: number
}

export type SmileDateSlice = {
  date: string
  forward: number
  smilePoints: SmilePoint[]
  sabrParams: SabrParams
  marketPoints?: SmilePoint[]
}

export type SmileResponse = {
  assetType: AssetType
  label: string
  xAxis: SmileXAxis
  dates: SmileDateSlice[]
}
