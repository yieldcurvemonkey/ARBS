export type ListedVolProduct = 'TU' | 'FV' | 'TY' | 'US' | 'WN' | 'UXY' | 'SFR'

export type ListedVolProductClass = 'UST' | 'STIR' | 'ALL'

export type ListedVolExpiry = '1W' | '2W' | '1M' | '2M' | '3M' | '6M'

export type ListedVolDisplayMode = 'vol' | 'dchg' | 'zscore'

export type ListedVolRange = '1M' | '3M' | '6M' | '1Y' | 'ALL'

export type ListedVolGridHistoryPoint = {
  date: string
  value: number | null
}

export type ListedVolGridCell = {
  asOfDate: string
  product: ListedVolProduct
  productClass: Exclude<ListedVolProductClass, 'ALL'>
  expiryLabel: ListedVolExpiry
  atmNvolBps: number | null
  atmNvolPrice: number | null
  dailyChange: number | null
  zScore: number | null
  percentile: number | null
  historyMean: number | null
  historyStd: number | null
  forwardPrice: number | null
  forwardYield: number | null
  fv01: number | null
  underlyingContract: string | null
  source: string | null
  history?: ListedVolGridHistoryPoint[]
}

export type ListedVolComparisonRow = {
  asOfDate: string
  product: ListedVolProduct
  expiryLabel: ListedVolExpiry
  listedAtmNvolBps: number | null
  swaptionAtmfNvolBps: number | null
  volRatio: number | null
  volDiffBps: number | null
  swaptionExpiryLabel: string | null
  swaptionTenorLabel: string | null
}

export type ListedVolRealizedRow = {
  asOfDate: string
  product: ListedVolProduct
  windowLabel: ListedVolExpiry
  realizedNvolBps: number | null
  impliedRealizedRatio: number | null
}

export type ListedVolSeriesPoint = {
  date: string
  timestamp: number
  listedNvolBps: number | null
  swaptionNvolBps: number | null
  volRatio: number | null
  volDiffBps: number | null
  realizedNvolBps: number | null
  impliedRealizedRatio: number | null
}

export type ListedVolSeriesStats = {
  latest: number | null
  mean: number | null
  std: number | null
  zScore: number | null
  percentile: number | null
  dailyChange: number | null
}

export type ListedVolGridResponse = {
  requestedDate: string | null
  asOfDate: string
  productClass: ListedVolProductClass
  products: ListedVolProduct[]
  expiries: ListedVolExpiry[]
  cells: ListedVolGridCell[]
  realizedRows: ListedVolRealizedRow[]
}

export type ListedVolHistoryGridResponse = ListedVolGridResponse & {
  lookback: number
}

export type ListedVolComparisonResponse = {
  requestedDate: string | null
  asOfDate: string
  product: ListedVolProduct
  rows: ListedVolComparisonRow[]
}

export type ListedVolTimeseriesResponse = {
  requestedDate: string | null
  asOfDate: string
  product: ListedVolProduct
  expiryLabel: ListedVolExpiry
  range: ListedVolRange
  points: ListedVolSeriesPoint[]
  stats: {
    listed: ListedVolSeriesStats
    swaption: ListedVolSeriesStats | null
    ratio: ListedVolSeriesStats | null
    realized: ListedVolSeriesStats | null
  }
}
