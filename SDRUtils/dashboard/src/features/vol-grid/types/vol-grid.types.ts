// ABOUTME: TypeScript types for the ATMF vol grid, calibration engine, and premium computation.

// ---------------------------------------------------------------------------
// Grid dimensions
// ---------------------------------------------------------------------------

export const EXPIRY_LABELS = ['1M', '3M', '6M', '1Y', '2Y', '3Y', '5Y', '7Y', '10Y', '15Y', '20Y', '30Y'] as const
export const TENOR_LABELS = ['1Y', '2Y', '3Y', '5Y', '7Y', '10Y', '15Y', '20Y', '25Y', '30Y'] as const

export type ExpiryLabel = (typeof EXPIRY_LABELS)[number]
export type TenorLabel = (typeof TENOR_LABELS)[number]

export const EXPIRY_YEARS: Record<ExpiryLabel, number> = {
  '1M': 1 / 12,
  '3M': 0.25,
  '6M': 0.5,
  '1Y': 1,
  '2Y': 2,
  '3Y': 3,
  '5Y': 5,
  '7Y': 7,
  '10Y': 10,
  '15Y': 15,
  '20Y': 20,
  '30Y': 30,
}

export const TENOR_YEARS: Record<TenorLabel, number> = {
  '1Y': 1,
  '2Y': 2,
  '3Y': 3,
  '5Y': 5,
  '7Y': 7,
  '10Y': 10,
  '15Y': 15,
  '20Y': 20,
  '25Y': 25,
  '30Y': 30,
}

// ---------------------------------------------------------------------------
// Vol source classification
// ---------------------------------------------------------------------------

export type VolSource =
  | 'direct_observation'
  | 'interpolated'
  | 'propagated'
  | 'prior'
  | 'no_data'

// ---------------------------------------------------------------------------
// Staleness
// ---------------------------------------------------------------------------

export type StalenessCategory = 'live' | 'recent' | 'stale' | 'very_stale' | 'no_data'

export type StalenessConfig = {
  liveThresholdMinutes: number
  recentThresholdMinutes: number
  staleThresholdMinutes: number
  veryStaleThresholdMinutes: number
}

export const DEFAULT_STALENESS_CONFIG: StalenessConfig = {
  liveThresholdMinutes: 15,
  recentThresholdMinutes: 60,
  staleThresholdMinutes: 240,
  veryStaleThresholdMinutes: 480,
}

// ---------------------------------------------------------------------------
// Quadrant classification
// ---------------------------------------------------------------------------

export type Quadrant = 'ULC' | 'URC' | 'LLC' | 'LRC' | 'BOUNDARY'

// ---------------------------------------------------------------------------
// Calibration observation (a qualifying trade that feeds the surface)
// ---------------------------------------------------------------------------

export type CalibrationObservation = {
  packageId: string
  executionTimestamp: number    // epoch ms
  platform: string
  packageType: string
  bpvolYr: number              // observed ATMF vol in bpvol/yr
  premium: number | null
  notional: number
  tradeLabel: string
  expiryLabel: string
  tenorLabel: string
  expiryYears: number
  tenorYears: number
  isCalibrationTrade: boolean
}

// ---------------------------------------------------------------------------
// Grid cell
// ---------------------------------------------------------------------------

export type VolGridCell = {
  // Grid coordinates
  expiry: ExpiryLabel
  tenor: TenorLabel
  expiryYears: number
  tenorYears: number

  // Vol surface
  atmfVol: number | null
  atmfVolSource: VolSource
  atmfVolConfidence: number
  atmfVolChange: number | null
  atmfVolChangeTime: number | null

  // Premium (derived from vol + yield curve)
  atmfPremium: number | null
  atmfPremiumBps: number | null

  // Observation metadata
  lastObservation: CalibrationObservation | null
  observationCount: number
  staleness: number              // minutes since last direct observation
  stalenessCategory: StalenessCategory

  // Propagation metadata
  lastPropagatedFrom: string | null
  propagationFactor: number

  // Quadrant
  quadrant: Quadrant
}

// ---------------------------------------------------------------------------
// Full grid state (returned by API)
// ---------------------------------------------------------------------------

export type VolGridState = {
  cells: VolGridCell[][]         // [expiryIndex][tenorIndex]
  lastUpdateTime: number         // epoch ms
  calibrationTradeCount: number
  filteredOutCount: number
  curveInfo: CurveInfo | null
  priorSource: 'previous_close' | 'historical_median' | 'none'
}

export type CurveInfo = {
  curveName: string
  source: string
  timestamp: string
  referenceDate: string
}

// ---------------------------------------------------------------------------
// Calibration filter configuration
// ---------------------------------------------------------------------------

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
}

export const IDB_STRADDLES_PRESET: CalibrationFilterConfig = {
  platforms: { idb: true, custy: false },
  packageTypes: {
    straddle: true,
    outright: false,
    riskReversal: false,
    verticalSpread: false,
    other: false,
  },
  minimumNotional: 25_000_000,
  maximumNotional: null,
  requireATMF: true,
  maxStrikeOffsetBps: null,
  actions: { newTrade: true, amendment: false, termination: false },
  observationHalfLife: 120,
  maxStalenessMinutes: 480,
}

export const ALL_IDB_PRESET: CalibrationFilterConfig = {
  ...IDB_STRADDLES_PRESET,
  packageTypes: {
    straddle: true,
    outright: true,
    riskReversal: false,
    verticalSpread: false,
    other: false,
  },
}

export const ALL_STRADDLES_PRESET: CalibrationFilterConfig = {
  ...IDB_STRADDLES_PRESET,
  platforms: { idb: true, custy: true },
}

export const CALIBRATION_PRESETS: Record<string, CalibrationFilterConfig> = {
  'IDB Straddles': IDB_STRADDLES_PRESET,
  'All IDB': ALL_IDB_PRESET,
  'All Straddles': ALL_STRADDLES_PRESET,
}

// ---------------------------------------------------------------------------
// Propagation parameters
// ---------------------------------------------------------------------------

export type PropagationConfig = {
  lengthScale: number
  expiryWeight: number
  tenorWeight: number
  noiseThresholdBpvol: number
}

export const DEFAULT_PROPAGATION_CONFIG: PropagationConfig = {
  lengthScale: 0.7,
  expiryWeight: 1.0,
  tenorWeight: 0.7,
  noiseThresholdBpvol: 0.1,
}

// ---------------------------------------------------------------------------
// View modes
// ---------------------------------------------------------------------------

export type ViewMode = 'vol' | 'premium' | 'change' | 'staleness'

// ---------------------------------------------------------------------------
// Annuity data from Python backend
// ---------------------------------------------------------------------------

export type AnnuityPoint = {
  expiry_years: number
  tenor_years: number
  forward_rate: number
  annuity: number
  discount_factor_to_expiry: number
}

export type AnnuityData = {
  curve_name: string
  source: string
  timestamp: string
  reference_date: string
  grid_points: AnnuityPoint[]
}
