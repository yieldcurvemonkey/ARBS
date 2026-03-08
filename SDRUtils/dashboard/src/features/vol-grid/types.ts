export type VolSource =
  | 'direct_observation'
  | 'interpolated'
  | 'propagated'
  | 'mdp_close'
  | 'prior'
  | 'no_data'

export type StalenessCategory =
  | 'live'
  | 'recent'
  | 'stale'
  | 'very_stale'
  | 'no_data'

export type CalibrationObservation = {
  packageId: string
  executionTimestamp: number
  platform: string | null
  packageType: string | null
  bpvolYr: number
  premium: number | null
  notional: number | null
  tradeLabel: string
  isCalibrationTrade: boolean
  gridNodeKey?: string | null
  displayNodeKey?: string | null
  expiry?: string | null
  tenor?: string | null
  mappingDistance?: number | null
  stalenessWeight?: number | null
  deltaBpvol?: number | null
}

export type VolGridTimeseriesPoint = {
  date: string
  timestamp: number
  nvol: number
  dailyChange: number | null
}

export type VolGridHistorySource = 'mdp' | 'pca'

export type VolGridTechnicalSignals = {
  autocorrelation1d: number | null
  maShortVsLong: string | null
  regimeLabel: string | null
}

export type VolGridCell = {
  nodeKey: string
  expiry: string
  tenor: string
  expiryYears: number
  tenorYears: number
  atmfVol: number | null
  eodVol: number | null
  atmfVolSource: VolSource
  atmfVolConfidence: number
  atmfVolChange: number | null
  atmfVolChangeTime: number | null
  atmfPremium: number | null
  atmfPremiumBps: number | null
  atmfPremiumBpsChange: number | null
  lastObservation: CalibrationObservation | null
  observationCount: number
  staleness: number | null
  stalenessCategory: StalenessCategory
  lastPropagatedFrom: string | null
  propagationFactor: number
  quadrant: 'ULC' | 'URC' | 'LLC' | 'LRC' | 'BOUNDARY'
  regimeLabel: string | null
  comparisonVol: number | null
  comparisonDiff: number | null
}

export type CalibrationFilterConfig = {
  platforms: {
    idb: boolean
    custy: boolean
    specificPlatforms?: string[]
  }
  packageTypes: {
    straddle: boolean
    outright: boolean
    riskReversal: boolean
    verticalSpread: boolean
    other: boolean
  }
  minimumNotional: number | null
  maximumNotional: number | null
  requireATMF: boolean
  maxStrikeOffsetBps: number | null
  actions: {
    newTrade: boolean
    amendment: boolean
    termination: boolean
  }
  observationHalfLife: number
  maxStalenessMinutes: number
  propagationLengthScale: number
  expiryWeight: number
  tenorWeight: number
}

export type CalibrationPresetKey =
  | 'idb_straddles'
  | 'all_idb'
  | 'custy_only'
  | 'custy_and_idb'
  | 'straddles_only'

export type SnapshotKind = 'intraday' | 'close_pca' | 'close_mdp'

export type VolGridSessionMode =
  | 'live'
  | 'eod_close'
  | 'weekend_close'
  | 'preopen_close'
  | 'historical'
  | 'prior_close'

export type VolGridSessionMeta = {
  mode: VolGridSessionMode
  label: string
  requestedDate: string
  effectiveDate: string
  isClosingView: boolean
  defaultSnapshotKind: SnapshotKind
  fallbackSnapshotKinds: SnapshotKind[]
  comparisonSnapshotKind: SnapshotKind | null
}

export type VolGridComparisonMeta = {
  snapshotKind: SnapshotKind
  source: string
  asOfDate: string
  timestamp: string | null
}

export type VolGridSurfaceResponse = {
  asOfDate: string
  asOfTimestamp: number
  calibrationPreset: CalibrationPresetKey
  grid: {
    expiries: string[]
    tenors: string[]
    expiryYears: number[]
    tenorYears: number[]
  }
  cells: VolGridCell[]
  curve: {
    curveName: string
    source: string
    timestamp: string | null
    referenceDate: string | null
  } | null
  meta: {
    hasData: boolean
    emptyReason: string | null
    lastUpdate: number | null
    calibrationTradeCount: number
    filteredOutCount: number
    snapshotKind: SnapshotKind | null
    comparison: VolGridComparisonMeta | null
    session: VolGridSessionMeta
  }
}

export type CalibrationTradesResponse = {
  asOfDate: string
  calibrationPreset: CalibrationPresetKey
  trades: CalibrationObservation[]
  filteredOutCount: number
}

export type VolumeStats = {
  tradeCount1w: number
  avgNotional1w: number | null
  totalNotional1w: number | null
  lastTradeDate: string | null
  lastTradeTimestamp: number | null
  daysSinceLastTrade: number | null
  rarityPercentile: number | null
}

export type VolGridTradeHistoryStats = {
  tradeCount: number
  firstTradeTimestamp: number | null
  lastTradeTimestamp: number | null
  totalNotional: number | null
  avgNotional: number | null
  medianNotional: number | null
  totalPremium: number | null
  avgPremium: number | null
  medianPremium: number | null
  avgBpvol: number | null
  medianBpvol: number | null
  tradesPerDay: number | null
  avgGapMs: number | null
  activeDays: number | null
  platformBreakdown: Array<{
    platform: string
    count: number
  }>
}

export type CellDetailResponse = {
  expiry: string
  tenor: string
  timeseries: VolGridTimeseriesPoint[]
  timeseriesBySource: Record<VolGridHistorySource, VolGridTimeseriesPoint[]>
  defaultHistorySource: VolGridHistorySource
  availableHistorySources: VolGridHistorySource[]
  tradeHistory: CalibrationObservation[]
  volumeStats: VolumeStats
  technicalSignals: VolGridTechnicalSignals
  tradeHistoryStats: VolGridTradeHistoryStats
}

export type VolGridViewMode =
  | 'vol'
  | 'premium'
  | 'change'
  | 'staleness'
  | 'confidence'
  | 'vs_mdp'

export type VolGridHistoryRange = '1M' | '3M' | '6M' | '1Y' | 'ALL'

export type VolGridHistoryMetric = 'nvol' | 'dailyChange'

export type VolGridTradeTimelineMetric = 'bpvol' | 'notional' | 'premium'

export type CellDisplayField =
  | 'vol'
  | 'premium'
  | 'change'
  | 'lastTradedTime'
  | 'lastTradedLevel'

export type VolGridChangeMetric = 'vol' | 'premium'

export type LastTradedLevelField = 'bpvol' | 'premiumBps'

export type CellDisplayConfig = {
  visibleFields: CellDisplayField[]
  changeMetric: VolGridChangeMetric
  lastTradedLevelFields: LastTradedLevelField[]
}

export const DEFAULT_CELL_DISPLAY_CONFIG: CellDisplayConfig = {
  visibleFields: ['vol', 'premium', 'change', 'lastTradedTime', 'lastTradedLevel'],
  changeMetric: 'vol',
  lastTradedLevelFields: ['bpvol', 'premiumBps']
}
