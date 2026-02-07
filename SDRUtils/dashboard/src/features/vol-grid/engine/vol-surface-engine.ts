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
  MarketSessionInfo,
} from '../types'
import type { MarketSession } from './market-session'
import {
  mapTradeToGridPoints,
  computeBlendWeight,
  computePropagation,
  SOURCE_CODES,
  SourceCode,
  gridDistance,
  decayFactor,
} from './propagation'
import { computePremiumGrid, computeFlatRateAnnuities } from './premium'

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
  referenceTime: number,
  source: VolSource,
  config: StalenessConfig,
  isSessionClosed: boolean,
): StalenessCategory {
  if (source === 'no_data') return 'no_data'

  const minutes = lastObsTime > 0 ? (referenceTime - lastObsTime) / 60_000 : Infinity

  // When the market session is closed, staleness is measured from session close.
  // Friday's last print at 4:55 PM is only 5 minutes "stale" relative to the 5 PM close,
  // even if it's now Saturday. This prevents the entire grid from going red over weekends.
  if (isSessionClosed) {
    if (source === 'direct_observation') {
      if (minutes < config.recentThresholdMinutes) return 'recent'
      if (minutes < config.staleThresholdMinutes) return 'stale'
      if (minutes < config.veryStaleThresholdMinutes) return 'very_stale'
      return 'very_stale' // never degrade to no_data for closed sessions with observations
    }
    if (source === 'propagated') return 'recent'
    if (source === 'interpolated') return 'recent'
    if (source === 'prior') return 'stale'
    return 'no_data'
  }

  // Live session staleness
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
   * After all observations are blended and propagated, runs IDW interpolation
   * to fill any remaining empty cells in the grid.
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

    // Fill remaining empty cells via IDW interpolation from observed/prior cells
    this.interpolateEmptyCells()
  }

  private processOneObservation(obs: CalibrationObservation): void {
    const mapping = mapTradeToGridPoints(obs.expiryYears, obs.tenorYears)

    // Save old vol at primary grid point before blending (for propagation reference)
    const primaryI = mapping[0].point.expiryIdx
    const primaryJ = mapping[0].point.tenorIdx
    const volBeforeBlend = this.state.volMatrix[primaryI][primaryJ]

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

    // Propagate change to neighbors.
    // Use pre-blend value as reference (if available), otherwise fall back to prior.
    // This allows propagation to work even without a prior surface — the first observation
    // at a cell establishes a reference for subsequent observations.
    const referenceVol = volBeforeBlend ?? this.state.priorMatrix[primaryI]?.[primaryJ] ?? null
    const newVol = this.state.volMatrix[primaryI][primaryJ]

    if (referenceVol !== null && newVol !== null) {
      const volChange = newVol - referenceVol

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
  }

  // -----------------------------------------------------------------------
  // IDW Interpolation — fills empty cells from observed anchors
  // -----------------------------------------------------------------------

  /**
   * Fill all remaining empty cells using Inverse Distance Weighting (IDW)
   * from cells that have values (direct observations, prior, or propagated).
   *
   * Uses the same log-space anisotropic distance metric as propagation,
   * so vol changes propagate more readily along the tenor axis than the
   * expiry axis, reflecting the correlation structure of the swaption grid.
   */
  private interpolateEmptyCells(): void {
    // Collect all cells that have values as interpolation anchors
    const anchors: { i: number; j: number; vol: number; time: number }[] = []
    for (let i = 0; i < NUM_EXPIRIES; i++) {
      for (let j = 0; j < NUM_TENORS; j++) {
        if (this.state.volMatrix[i][j] !== null) {
          anchors.push({
            i, j,
            vol: this.state.volMatrix[i][j] as number,
            time: this.state.lastObsTime[i][j],
          })
        }
      }
    }

    if (anchors.length < 2) return // Need at least 2 anchors for meaningful interpolation

    // For each empty cell, compute IDW interpolated value
    for (let i = 0; i < NUM_EXPIRIES; i++) {
      for (let j = 0; j < NUM_TENORS; j++) {
        if (this.state.volMatrix[i][j] !== null) continue

        const targetExpiry = EXPIRY_YEARS[EXPIRY_LABELS[i]]
        const targetTenor = TENOR_YEARS[TENOR_LABELS[j]]

        let weightedSum = 0
        let totalWeight = 0
        let latestTime = 0

        for (const anchor of anchors) {
          const anchorExpiry = EXPIRY_YEARS[EXPIRY_LABELS[anchor.i]]
          const anchorTenor = TENOR_YEARS[TENOR_LABELS[anchor.j]]

          const dist = gridDistance(
            targetExpiry, targetTenor,
            anchorExpiry, anchorTenor,
            this.propagationConfig,
          )
          const w = decayFactor(dist, this.propagationConfig)

          if (w < 0.01) continue // Too far to contribute meaningfully

          weightedSum += w * anchor.vol
          totalWeight += w
          if (anchor.time > latestTime) latestTime = anchor.time
        }

        if (totalWeight > 0) {
          this.state.volMatrix[i][j] = weightedSum / totalWeight
          this.state.sourceCode[i][j] = SOURCE_CODES.interpolated
          this.state.confidence[i][j] = Math.min(0.7, totalWeight / (2 + totalWeight))
          this.state.lastObsTime[i][j] = latestTime
        }
      }
    }
  }

  // -----------------------------------------------------------------------
  // Build grid state for API response / UI
  // -----------------------------------------------------------------------

  buildGridState(session: MarketSession): VolGridState {
    const now = Date.now()
    const isSessionClosed = !session.isMarketOpen
    // When closed, measure staleness from session close time, not wall clock
    const stalenessRef = session.stalenessReferenceTime
    const cells: VolGridCell[][] = []

    // Compute premium grid — use external annuity data if available,
    // otherwise fall back to flat-rate approximation (~4.3% SOFR)
    const annuityData = this.annuityData.length > 0
      ? this.annuityData
      : computeFlatRateAnnuities()
    const { premiumGrid, premiumBpsGrid } = computePremiumGrid(this.state.volMatrix, annuityData)

    for (let i = 0; i < NUM_EXPIRIES; i++) {
      cells.push([])
      for (let j = 0; j < NUM_TENORS; j++) {
        const vol = this.state.volMatrix[i][j]
        const prior = this.state.priorMatrix[i][j]
        const source = sourceCodeToVolSource(this.state.sourceCode[i][j])
        const lastObs = this.state.lastObservation[i][j]
        const lastObsTime = this.state.lastObsTime[i][j]
        // Staleness measured from session close when market is closed
        const staleness = lastObsTime > 0 ? (stalenessRef - lastObsTime) / 60_000 : Infinity

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
            lastObsTime, stalenessRef, source, this.stalenessConfig, isSessionClosed,
          ),

          lastPropagatedFrom: this.state.lastPropagatedFrom[i][j],
          propagationFactor: source === 'propagated' ? 0.5 : source === 'direct_observation' ? 0 : 1,

          quadrant: classifyQuadrant(EXPIRY_YEARS[EXPIRY_LABELS[i]], TENOR_YEARS[TENOR_LABELS[j]]),
        }

        cells[i].push(cell)
      }
    }

    const sessionInfo: MarketSessionInfo = {
      status: session.status,
      isMarketOpen: session.isMarketOpen,
      tradingDate: session.tradingDate,
      sessionLabel: session.sessionLabel,
      shouldPoll: session.shouldPoll,
    }

    return {
      cells,
      lastUpdateTime: now,
      calibrationTradeCount: this.calibrationTrades.length,
      filteredOutCount: this.filteredOutCount,
      curveInfo: this.curveInfo,
      priorSource: this.hasPrior() ? 'historical_median' : 'none',
      session: sessionInfo,
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
