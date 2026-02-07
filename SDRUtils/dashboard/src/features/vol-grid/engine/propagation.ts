// ABOUTME: Neighborhood propagation engine for the vol surface.
// When a new observation updates a grid point, the change propagates to neighbors
// with distance-decayed weighting in log-space with anisotropic decay.

import {
  EXPIRY_LABELS,
  TENOR_LABELS,
  EXPIRY_YEARS,
  TENOR_YEARS,
  ExpiryLabel,
  TenorLabel,
  PropagationConfig,
  DEFAULT_PROPAGATION_CONFIG,
} from '../types'

// ---------------------------------------------------------------------------
// Grid distance in log-space with anisotropic weighting
// ---------------------------------------------------------------------------

/**
 * Compute normalized distance between two grid points in log-space.
 *
 * Uses log-space so that 1Y→2Y and 10Y→20Y are equidistant (both doublings).
 * Anisotropic weights control propagation asymmetry:
 *   - tenorWeight < expiryWeight → vol changes propagate further along tenor axis
 *   - This reflects that 10Yx10Y and 10Yx20Y are more correlated than 10Yx10Y and 5Yx10Y
 */
export function gridDistance(
  expiry1: number,
  tenor1: number,
  expiry2: number,
  tenor2: number,
  config: PropagationConfig = DEFAULT_PROPAGATION_CONFIG,
): number {
  const logExpiryDist = Math.abs(Math.log(expiry1) - Math.log(expiry2))
  const logTenorDist = Math.abs(Math.log(tenor1) - Math.log(tenor2))

  return Math.sqrt(
    (config.expiryWeight * logExpiryDist) ** 2 +
    (config.tenorWeight * logTenorDist) ** 2,
  )
}

/**
 * Compute decay factor from distance. Returns 0-1 where:
 *   1 = same point (no decay)
 *   ~0.5 = one "step" away on same axis
 *   ~0 = very far away
 */
export function decayFactor(
  distance: number,
  config: PropagationConfig = DEFAULT_PROPAGATION_CONFIG,
): number {
  return Math.exp(-distance / config.lengthScale)
}

// ---------------------------------------------------------------------------
// Blend weight computation
// ---------------------------------------------------------------------------

/**
 * Source type codes matching the spec:
 *   0 = no_data, 1 = prior, 2 = propagated, 3 = interpolated, 4 = direct_observation
 */
export const SOURCE_CODES = {
  no_data: 0,
  prior: 1,
  propagated: 2,
  interpolated: 3,
  direct_observation: 4,
} as const

export type SourceCode = (typeof SOURCE_CODES)[keyof typeof SOURCE_CODES]

/**
 * Compute how much a new observation should move a grid point.
 *
 * @param observationWeight - 1.0 for direct grid hit, <1.0 for off-grid snapping
 * @param currentSource - source code of current cell value
 * @param lastObsTime - epoch ms of last observation at this cell
 * @param halfLifeMinutes - observation half-life from config
 * @returns blend weight in [0.05, 0.95]
 */
export function computeBlendWeight(
  observationWeight: number,
  currentSource: SourceCode,
  lastObsTime: number,
  halfLifeMinutes: number,
  currentTime: number = Date.now(),
): number {
  // Base weight depends on current source quality
  const sourceWeights: Record<number, number> = {
    0: 1.0,   // no_data: fully accept
    1: 0.8,   // prior: strongly prefer new
    2: 0.7,   // propagated: prefer direct
    3: 0.6,   // interpolated: prefer direct
    4: 0.4,   // direct: blend conservatively
  }
  const base = sourceWeights[currentSource] ?? 0.5

  // Staleness factor: how stale is the current value?
  const stalenessMinutes = lastObsTime > 0
    ? (currentTime - lastObsTime) / 60_000
    : Infinity

  // stalenessFactor → 0 when just updated, → 1 when very stale
  const stalenessFactor = stalenessMinutes === Infinity
    ? 1.0
    : 1.0 - Math.exp(-stalenessMinutes / halfLifeMinutes)

  const blend = base * observationWeight * (0.5 + 0.5 * stalenessFactor)

  return Math.max(0.05, Math.min(0.95, blend))
}

// ---------------------------------------------------------------------------
// Grid mapping: snap trade to nearest grid point(s)
// ---------------------------------------------------------------------------

const EXPIRY_SNAP_TOLERANCE = 0.15  // ±2 months
const TENOR_SNAP_TOLERANCE = 0.5    // ±6 months

export type GridPoint = { expiryIdx: number; tenorIdx: number }
export type GridMapping = { point: GridPoint; weight: number }[]

const expiryYearsArr = EXPIRY_LABELS.map(l => EXPIRY_YEARS[l])
const tenorYearsArr = TENOR_LABELS.map(l => TENOR_YEARS[l])

function findNearestIdx(target: number, arr: number[]): { idx: number; distance: number } {
  let bestIdx = 0
  let bestDist = Math.abs(target - arr[0])
  for (let i = 1; i < arr.length; i++) {
    const dist = Math.abs(target - arr[i])
    if (dist < bestDist) {
      bestDist = dist
      bestIdx = i
    }
  }
  return { idx: bestIdx, distance: bestDist }
}

function findBracketingIndices(target: number, arr: number[]): { lo: number; hi: number } | null {
  for (let i = 0; i < arr.length - 1; i++) {
    if (arr[i] <= target && target <= arr[i + 1]) {
      return { lo: i, hi: i + 1 }
    }
  }
  return null
}

/**
 * Map a trade's (expiryYears, tenorYears) to grid point(s) with weights.
 * If within snap tolerance, maps directly. Otherwise, distributes via bilinear weighting.
 */
export function mapTradeToGridPoints(
  expiryYears: number,
  tenorYears: number,
): GridMapping {
  const nearestExpiry = findNearestIdx(expiryYears, expiryYearsArr)
  const nearestTenor = findNearestIdx(tenorYears, tenorYearsArr)

  // Direct snap if within tolerance
  if (nearestExpiry.distance < EXPIRY_SNAP_TOLERANCE && nearestTenor.distance < TENOR_SNAP_TOLERANCE) {
    return [{ point: { expiryIdx: nearestExpiry.idx, tenorIdx: nearestTenor.idx }, weight: 1.0 }]
  }

  // Bilinear interpolation to surrounding grid points
  const expiryBracket = findBracketingIndices(expiryYears, expiryYearsArr)
  const tenorBracket = findBracketingIndices(tenorYears, tenorYearsArr)

  if (!expiryBracket || !tenorBracket) {
    // Outside grid, snap to nearest
    return [{ point: { expiryIdx: nearestExpiry.idx, tenorIdx: nearestTenor.idx }, weight: 1.0 }]
  }

  const { lo: eLo, hi: eHi } = expiryBracket
  const { lo: tLo, hi: tHi } = tenorBracket

  const eRange = expiryYearsArr[eHi] - expiryYearsArr[eLo]
  const tRange = tenorYearsArr[tHi] - tenorYearsArr[tLo]

  const eFrac = eRange > 0 ? (expiryYears - expiryYearsArr[eLo]) / eRange : 0.5
  const tFrac = tRange > 0 ? (tenorYears - tenorYearsArr[tLo]) / tRange : 0.5

  const mapping: GridMapping = []
  const weights = [
    { expiryIdx: eLo, tenorIdx: tLo, w: (1 - eFrac) * (1 - tFrac) },
    { expiryIdx: eLo, tenorIdx: tHi, w: (1 - eFrac) * tFrac },
    { expiryIdx: eHi, tenorIdx: tLo, w: eFrac * (1 - tFrac) },
    { expiryIdx: eHi, tenorIdx: tHi, w: eFrac * tFrac },
  ]

  for (const { expiryIdx, tenorIdx, w } of weights) {
    if (w > 0.01) {
      mapping.push({ point: { expiryIdx, tenorIdx }, weight: w })
    }
  }

  return mapping
}

// ---------------------------------------------------------------------------
// Surface propagation
// ---------------------------------------------------------------------------

/**
 * Propagate vol change from source grid points to neighbors.
 * Returns a map of (expiryIdx,tenorIdx) → vol delta to apply.
 */
export function computePropagation(
  sourcePoints: GridMapping,
  volChange: number,
  _sourceVolMatrix: number[][],      // current vol matrix (reserved for future smile-aware propagation)
  sourceTimeMatrix: number[][],      // last observation times
  sourceCodeMatrix: SourceCode[][],  // source codes
  observationTime: number,
  config: PropagationConfig = DEFAULT_PROPAGATION_CONFIG,
): Map<string, number> {
  const deltas = new Map<string, number>()

  if (Math.abs(volChange) < config.noiseThresholdBpvol) {
    return deltas // below noise threshold
  }

  for (const { point: src, weight: srcWeight } of sourcePoints) {
    const srcExpiry = expiryYearsArr[src.expiryIdx]
    const srcTenor = tenorYearsArr[src.tenorIdx]

    for (let ni = 0; ni < expiryYearsArr.length; ni++) {
      for (let nj = 0; nj < tenorYearsArr.length; nj++) {
        if (ni === src.expiryIdx && nj === src.tenorIdx) continue

        const dist = gridDistance(srcExpiry, srcTenor, expiryYearsArr[ni], tenorYearsArr[nj], config)
        const decay = decayFactor(dist, config)

        if (decay < 0.05) continue // too far

        // Don't override recent direct observations
        if (sourceCodeMatrix[ni]?.[nj] === SOURCE_CODES.direct_observation) {
          const neighborTime = sourceTimeMatrix[ni]?.[nj] ?? 0
          if (neighborTime > observationTime - 5 * 60_000) continue // within 5 min
        }

        const propagatedDelta = volChange * decay * srcWeight
        const key = `${ni},${nj}`
        deltas.set(key, (deltas.get(key) ?? 0) + propagatedDelta)
      }
    }
  }

  return deltas
}
