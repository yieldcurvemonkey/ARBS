// ABOUTME: Vol surface engine that maintains the live ATMF vol grid state.
// Processes calibration observations, applies blending, propagation, and staleness.

import {
  EXPIRY_LABELS,
  TENOR_LABELS,
  EXPIRY_YEARS,
  TENOR_YEARS,
  ExpiryLabel,
  TenorLabel,
  VolGridCell,
  VolGridState,
  VolSource,
  StalenessCategory,
  CalibrationObservation,
  CalibrationFilterConfig,
  PropagationConfig,
  StalenessConfig,
  DEFAULT_PROPAGATION_CONFIG,
  DEFAULT_STALENESS_CONFIG,
  IDB_STRADDLES_PRESET,
  AnnuityPoint,
  Quadrant,
  CurveInfo,
} from '../types'
import {
  mapTradeToGridPoints,
  computeBlendWeight,
  computePropagation,
  SOURCE_CODES,
  SourceCode,
} from './propagation'
import { computePremiumGrid } from './premium'

// ---------------------------------------------------------------------------
// Internal state matrices
// ---------------------------------------------------------------------------

type SurfaceState = {
  volMatrix: (number | null)[][]
  priorMatrix: (number | null)[][]
  lastObsTime: number[][]
  observationCount: number[][]
  sourceCode: SourceCode[][]
  confidence: number[][]
  lastObservation: (CalibrationObservation | null)[][]
  lastPropagatedFrom: (string | null)[][]
}

const NUM_EXPIRIES = EXPIRY_LABELS.length
const NUM_TENORS = TENOR_LABELS.length

function createEmptyMatrix<T>(fill: T): T[][] {
  return Array.from({ length: NUM_EXPIRIES }, () =>
    Array.from({ length: NUM_TENORS }, () => fill),
  )
}

function createState(): SurfaceState {
  return {
    volMatrix: createEmptyMatrix<number | null>(null),
    priorMatrix: createEmptyMatrix<number | null>(null),
    lastObsTime: createEmptyMatrix(0),
    observationCount: createEmptyMatrix(0),
    sourceCode: createEmptyMatrix<SourceCode>(SOURCE_CODES.no_data),
    confidence: createEmptyMatrix(0),
    lastObservation: createEmptyMatrix<CalibrationObservation | null>(null),
    lastPropagatedFrom: createEmptyMatrix<string | null>(null),
  }
}

// ---------------------------------------------------------------------------
// Quadrant classification
// ---------------------------------------------------------------------------

const EXPIRY_BOUNDARY = 5   // 5Y
const TENOR_BOUNDARY = 10   // 10Y

function classifyQuadrant(expiryYears: number, tenorYears: number): Quadrant {
  if (expiryYears < EXPIRY_BOUNDARY && tenorYears < TENOR_BOUNDARY) return 'ULC'
  if (expiryYears < EXPIRY_BOUNDARY && tenorYears >= TENOR_BOUNDARY) return 'URC'
  if (expiryYears >= EXPIRY_BOUNDARY && tenorYears < TENOR_BOUNDARY) return 'LLC'
  return 'LRC'
}

// ---------------------------------------------------------------------------
// Staleness computation
// ---------------------------------------------------------------------------

function computeStalenessCategory(
  lastObsTime: number,
  currentTime: number,
  source: VolSource,
  config: StalenessConfig,
): StalenessCategory {
  if (source === 'no_data') return 'no_data'

  const minutes = lastObsTime > 0 ? (currentTime - lastObsTime) / 60_000 : Infinity

  if (source === 'direct_observation') {
    if (minutes < config.liveThresholdMinutes) return 'live'
    if (minutes < config.recentThresholdMinutes) return 'recent'
    if (minutes < config.staleThresholdMinutes) return 'stale'
    if (minutes < config.veryStaleThresholdMinutes) return 'very_stale'
    return 'no_data'
  }
  if (source === 'propagated') {
    if (minutes < config.liveThresholdMinutes * 2) return 'recent'
    return 'stale'
  }
  if (source === 'prior') return 'very_stale'
  if (source === 'interpolated') return 'stale'
  return 'no_data'
}

function sourceCodeToVolSource(code: SourceCode): VolSource {
  switch (code) {
    case SOURCE_CODES.no_data: return 'no_data'
    case SOURCE_CODES.prior: return 'prior'
    case SOURCE_CODES.propagated: return 'propagated'
    case SOURCE_CODES.interpolated: return 'interpolated'
    case SOURCE_CODES.direct_observation: return 'direct_observation'
    default: return 'no_data'
  }
}

// ---------------------------------------------------------------------------
// Vol Surface Engine
// ---------------------------------------------------------------------------

export class VolSurfaceEngine {
  private state: SurfaceState
  private propagationConfig: PropagationConfig
  private stalenessConfig: StalenessConfig
  private calibrationConfig: CalibrationFilterConfig
  private calibrationTrades: CalibrationObservation[] = []
  private filteredOutCount: number = 0
  private curveInfo: CurveInfo | null = null
  private annuityData: AnnuityPoint[] = []

  constructor(
    propagationConfig: PropagationConfig = DEFAULT_PROPAGATION_CONFIG,
    stalenessConfig: StalenessConfig = DEFAULT_STALENESS_CONFIG,
    calibrationConfig: CalibrationFilterConfig = IDB_STRADDLES_PRESET,
  ) {
    this.state = createState()
    this.propagationConfig = propagationConfig
    this.stalenessConfig = stalenessConfig
    this.calibrationConfig = calibrationConfig
  }

  // -----------------------------------------------------------------------
  // Initialization
  // -----------------------------------------------------------------------

  /**
   * Initialize from prior surface (historical median or previous close).
   */
  initializeFromPrior(priorVols: Record<string, number>, overnightDecay: number = 0.7): void {
    for (let i = 0; i < NUM_EXPIRIES; i++) {
      for (let j = 0; j < NUM_TENORS; j++) {
        const key = `${EXPIRY_LABELS[i]}x${TENOR_LABELS[j]}`
        const vol = priorVols[key]
        if (vol !== undefined && vol > 0) {
          this.state.volMatrix[i][j] = vol
          this.state.priorMatrix[i][j] = vol
          this.state.sourceCode[i][j] = SOURCE_CODES.prior
          this.state.confidence[i][j] = 0.3 * overnightDecay
        }
      }
    }
  }

  /**
   * Set annuity data from the Python backend for premium computation.
   */
  setAnnuityData(data: AnnuityPoint[], curveInfo: CurveInfo): void {
    this.annuityData = data
    this.curveInfo = curveInfo
  }

  // -----------------------------------------------------------------------
  // Observation processing
  // -----------------------------------------------------------------------

  /**
   * Process a batch of calibration observations into the surface.
   */
  processObservations(
    observations: CalibrationObservation[],
    filteredOutCount: number,
  ): void {
    this.filteredOutCount = filteredOutCount

    // Sort by timestamp (oldest first) so the surface evolves chronologically
    const sorted = [...observations].sort((a, b) => a.executionTimestamp - b.executionTimestamp)

    for (const obs of sorted) {
      this.processOneObservation(obs)
    }

    this.calibrationTrades = observations
  }

  private processOneObservation(obs: CalibrationObservation): void {
    // Map trade to grid points
    const mapping = mapTradeToGridPoints(obs.expiryYears, obs.tenorYears)

    // For each affected grid point, blend observation with current value
    for (const { point, weight } of mapping) {
      const { expiryIdx: i, tenorIdx: j } = point
      const currentVol = this.state.volMatrix[i][j]

      const blend = computeBlendWeight(
        weight,
        this.state.sourceCode[i][j],
        this.state.lastObsTime[i][j],
        this.calibrationConfig.observationHalfLife,
        obs.executionTimestamp,
      )

      if (currentVol === null) {
        this.state.volMatrix[i][j] = obs.bpvolYr
      } else {
        this.state.volMatrix[i][j] = currentVol * (1 - blend) + obs.bpvolYr * blend
      }

      this.state.lastObsTime[i][j] = obs.executionTimestamp
      this.state.observationCount[i][j] += 1
      this.state.sourceCode[i][j] = SOURCE_CODES.direct_observation
      this.state.confidence[i][j] = Math.min(1.0, this.state.confidence[i][j] + blend)
      this.state.lastObservation[i][j] = obs
    }

    // Propagate to neighbors
    const priorVol = this.state.priorMatrix[mapping[0].point.expiryIdx]?.[mapping[0].point.tenorIdx]
    const currentVol = this.state.volMatrix[mapping[0].point.expiryIdx]?.[mapping[0].point.tenorIdx]

    if (priorVol !== null && priorVol !== undefined && currentVol !== null) {
      const volChange = currentVol - priorVol

      const deltas = computePropagation(
        mapping,
        volChange,
        this.state.volMatrix as number[][],
        this.state.lastObsTime,
        this.state.sourceCode,
        obs.executionTimestamp,
        this.propagationConfig,
      )

      for (const [key, delta] of deltas) {
        const [ni, nj] = key.split(',').map(Number)
        if (this.state.volMatrix[ni][nj] !== null) {
          this.state.volMatrix[ni][nj] = (this.state.volMatrix[ni][nj] as number) + delta
        }
        if (this.state.sourceCode[ni][nj] < SOURCE_CODES.direct_observation) {
          this.state.sourceCode[ni][nj] = Math.max(
            this.state.sourceCode[ni][nj],
            SOURCE_CODES.propagated,
          ) as SourceCode
          this.state.confidence[ni][nj] = Math.min(
            1.0,
            this.state.confidence[ni][nj] + 0.1,
          )
        }
        this.state.lastPropagatedFrom[ni][nj] = obs.tradeLabel
      }
    }
  }

  // -----------------------------------------------------------------------
  // Build grid state for API response / UI
  // -----------------------------------------------------------------------

  buildGridState(): VolGridState {
    const now = Date.now()
    const cells: VolGridCell[][] = []

    // Compute premium grid if annuity data is available
    let premiumGrid: (number | null)[][] | null = null
    let premiumBpsGrid: (number | null)[][] | null = null
    if (this.annuityData.length > 0) {
      const result = computePremiumGrid(this.state.volMatrix, this.annuityData)
      premiumGrid = result.premiumGrid
      premiumBpsGrid = result.premiumBpsGrid
    }

    for (let i = 0; i < NUM_EXPIRIES; i++) {
      cells.push([])
      for (let j = 0; j < NUM_TENORS; j++) {
        const vol = this.state.volMatrix[i][j]
        const prior = this.state.priorMatrix[i][j]
        const source = sourceCodeToVolSource(this.state.sourceCode[i][j])
        const lastObs = this.state.lastObservation[i][j]
        const lastObsTime = this.state.lastObsTime[i][j]
        const staleness = lastObsTime > 0 ? (now - lastObsTime) / 60_000 : Infinity

        const cell: VolGridCell = {
          expiry: EXPIRY_LABELS[i],
          tenor: TENOR_LABELS[j],
          expiryYears: EXPIRY_YEARS[EXPIRY_LABELS[i]],
          tenorYears: TENOR_YEARS[TENOR_LABELS[j]],

          atmfVol: vol !== null ? Math.round(vol * 10) / 10 : null,
          atmfVolSource: source,
          atmfVolConfidence: Math.round(this.state.confidence[i][j] * 100) / 100,
          atmfVolChange: vol !== null && prior !== null
            ? Math.round((vol - prior) * 10) / 10
            : null,
          atmfVolChangeTime: lastObsTime > 0 ? lastObsTime : null,

          atmfPremium: premiumGrid?.[i]?.[j] ?? null,
          atmfPremiumBps: premiumBpsGrid?.[i]?.[j] ?? null,

          lastObservation: lastObs,
          observationCount: this.state.observationCount[i][j],
          staleness: staleness === Infinity ? -1 : Math.round(staleness),
          stalenessCategory: computeStalenessCategory(
            lastObsTime, now, source, this.stalenessConfig,
          ),

          lastPropagatedFrom: this.state.lastPropagatedFrom[i][j],
          propagationFactor: source === 'propagated' ? 0.5 : source === 'direct_observation' ? 0 : 1,

          quadrant: classifyQuadrant(EXPIRY_YEARS[EXPIRY_LABELS[i]], TENOR_YEARS[TENOR_LABELS[j]]),
        }

        cells[i].push(cell)
      }
    }

    return {
      cells,
      lastUpdateTime: now,
      calibrationTradeCount: this.calibrationTrades.length,
      filteredOutCount: this.filteredOutCount,
      curveInfo: this.curveInfo,
      priorSource: this.hasPrior() ? 'historical_median' : 'none',
    }
  }

  private hasPrior(): boolean {
    for (let i = 0; i < NUM_EXPIRIES; i++) {
      for (let j = 0; j < NUM_TENORS; j++) {
        if (this.state.priorMatrix[i][j] !== null) return true
      }
    }
    return false
  }

  // -----------------------------------------------------------------------
  // Getters
  // -----------------------------------------------------------------------

  getCalibrationTrades(): CalibrationObservation[] {
    return this.calibrationTrades
  }

  getFilteredOutCount(): number {
    return this.filteredOutCount
  }
}
