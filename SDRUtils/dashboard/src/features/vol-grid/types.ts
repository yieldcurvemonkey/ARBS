export type VolSource =
  | 'direct_observation'
  | 'interpolated'
  | 'propagated'
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
}

export type VolGridCell = {
  expiry: string
  tenor: string
  expiryYears: number
  tenorYears: number
  atmfVol: number | null
  atmfVolSource: VolSource
  atmfVolConfidence: number
  atmfVolChange: number | null
  atmfVolChangeTime: number | null
  atmfPremium: number | null
  atmfPremiumBps: number | null
  lastObservation: CalibrationObservation | null
  observationCount: number
  staleness: number | null
  stalenessCategory: StalenessCategory
  lastPropagatedFrom: string | null
  propagationFactor: number
  quadrant: 'ULC' | 'URC' | 'LLC' | 'LRC' | 'BOUNDARY'
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
  | 'custy_and_idb'
  | 'straddles_only'

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
    lastUpdate: number | null
    calibrationTradeCount: number
    filteredOutCount: number
  }
}

export type CalibrationTradesResponse = {
  asOfDate: string
  calibrationPreset: CalibrationPresetKey
  trades: CalibrationObservation[]
  filteredOutCount: number
}

export type VolGridViewMode = 'vol' | 'premium' | 'change' | 'staleness'
