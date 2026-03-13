export type ListedOptionProductFamily = 'UST' | 'STIR'
export type ListedOptionMetricField =
  | 'open_interest'
  | 'volume'
  | 'open_interest_change'
  | 'volume_change'
export type ListedOptionLabelNamespace = 'BBG' | 'Globex' | 'Barchart'
export type ListedOptionContractReferenceMode = 'explicit' | 'constant_maturity'
export type ListedOptionRowAxis = 'strike' | 'delta' | 'bps_offset'
export type ListedOptionRange = '1M' | '3M' | '6M' | '1Y' | 'ALL'
export type ListedOptionSide = 'C' | 'P' | 'S'
export type ListedOptionSeriesSelectorType =
  | 'explicit_symbol'
  | 'strike'
  | 'delta'
  | 'bps_offset'

export type ListedOptionSeriesConfig = {
  metricField: ListedOptionMetricField
  productFamily?: ListedOptionProductFamily
  productRoot: string
  labelNamespace?: ListedOptionLabelNamespace
  contractReferenceMode: ListedOptionContractReferenceMode
  explicitContract?: string
  constantMaturityRank?: number
  selectorType: ListedOptionSeriesSelectorType
  side: ListedOptionSide
  selectorValue?: number | string | null
  rawSymbolFallback?: string | null
}

export type ListedOptionSeriesStats = {
  latest: number | null
  mean: number | null
  min: number | null
  max: number | null
  stdev: number | null
  zScore: number | null
  count: number
}

export type ListedOptionTimeseriesPoint = {
  asOf: string
  value: number | null
}

export type ListedOptionTimeseriesSeries = {
  id: string
  label: string
  config: ListedOptionSeriesConfig
  points: ListedOptionTimeseriesPoint[]
  stats: ListedOptionSeriesStats
}

export type ListedOptionTimeseriesMultiResponse = {
  startDate: string | null
  endDate: string | null
  asOfDate: string | null
  series: ListedOptionTimeseriesSeries[]
  warnings: string[]
}

export type ListedOptionSnapshotContractGroup = {
  id: string
  productFamily: ListedOptionProductFamily
  productRoot: string
  contractReferenceMode: ListedOptionContractReferenceMode
  explicitContract: string | null
  constantMaturityRank: number | null
  displayLabel: string
  underlyingLabel: string | null
  forwardPrice: number | null
  expiryDate: string | null
  dteDays: number | null
}

export type ListedOptionSnapshotCell = {
  contractGroupId: string
  side: Exclude<ListedOptionSide, 'S'>
  value: number | null
  strike: number | null
  deltaAbs: number | null
  atmOffsetBps: number | null
  explicitOptionSymbol: string | null
  chartSeries: ListedOptionSeriesConfig | null
}

export type ListedOptionSnapshotRow = {
  rowKey: string
  rowLabel: string
  axisValue: number | null
  strike: number | null
  deltaAbs: number | null
  bpsOffset: number | null
  cells: Record<
    string,
    {
      call: ListedOptionSnapshotCell | null
      put: ListedOptionSnapshotCell | null
    }
  >
}

export type ListedOptionSnapshotFilterOption = {
  productFamily: ListedOptionProductFamily
  productRoot: string
}

export type ListedOptionSnapshotResponse = {
  requestedDate: string | null
  asOfDate: string | null
  latestAvailableDate: string | null
  periodBusinessDays: number
  field: ListedOptionMetricField
  labelNamespace: ListedOptionLabelNamespace
  contractView: ListedOptionContractReferenceMode
  rowAxis: ListedOptionRowAxis
  availableRoots: ListedOptionSnapshotFilterOption[]
  contractGroups: ListedOptionSnapshotContractGroup[]
  rows: ListedOptionSnapshotRow[]
  warnings: string[]
}

export type ListedOptionTimeseriesFormulaLeg = {
  seriesId: string
  weight: number
}

export type ListedOptionTimeseriesFormulaConfig = {
  id: string
  name: string
  yaxis: 'y' | 'y2'
  scaleBy100: boolean
  legs: ListedOptionTimeseriesFormulaLeg[]
}

export type ListedOptionDerivedFormulaSeries = {
  id: string
  name: string
  yaxis: 'y' | 'y2'
  scaleBy100: boolean
  expression: string
  nonNullCount: number
  points: ListedOptionTimeseriesPoint[]
}

export type ListedOptionSearchOption = {
  id: string
  label: string
  subtitle: string
  bucket: 'explicit' | 'delta' | 'offset' | 'cm'
  config: ListedOptionSeriesConfig
  aliases: string[]
}
