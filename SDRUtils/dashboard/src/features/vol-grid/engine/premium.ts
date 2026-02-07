// ABOUTME: Premium computation engine using Bachelier (normal) model closed-form for ATMF straddles.
// Straddle = Call + Put at ATMF = 2 × Call = N × A × σ_N × √T × √(2/π)
// where √(2/π) = 2×φ(0) already accounts for the straddle doubling.

import {
  EXPIRY_LABELS,
  TENOR_LABELS,
  EXPIRY_YEARS,
  TENOR_YEARS,
  ExpiryLabel,
  TenorLabel,
  AnnuityPoint,
} from '../types'

const SQRT_2_OVER_PI = Math.sqrt(2 / Math.PI) // ≈ 0.7979

/**
 * Compute ATMF straddle premium using Bachelier closed-form.
 *
 * Straddle = N × A × σ_N × √T × √(2/π)
 *
 * @param normalVolDecimal - normal vol in decimal (not bpvol). E.g., 0.0075 for 75bpvol.
 * @param expiryYears - time to expiry in years
 * @param annuity - annuity factor of the underlying swap (sum of discounted day-count fractions)
 * @param notional - reference notional (e.g., 100_000_000)
 * @returns straddle premium in $
 */
export function bachelierATMFStraddlePremium(
  normalVolDecimal: number,
  expiryYears: number,
  annuity: number,
  notional: number = 100_000_000,
): number {
  if (normalVolDecimal <= 0 || expiryYears <= 0 || annuity <= 0) return 0
  const sqrtT = Math.sqrt(expiryYears)
  // √(2/π) = 2×φ(0) already includes the straddle factor of 2
  return annuity * normalVolDecimal * sqrtT * SQRT_2_OVER_PI * notional
}

/**
 * Compute premium in basis points of notional.
 */
export function premiumToBps(premium: number, notional: number = 100_000_000): number {
  return (premium / notional) * 10_000
}

// ---------------------------------------------------------------------------
// Flat-rate annuity computation (fallback when Python curve is unavailable)
// ---------------------------------------------------------------------------

/**
 * Compute annuity factor for a swap starting at T with tenor τ using flat-rate discounting.
 *
 * A(T,τ) = DF(T) × δ × DF(δ) × (1 - DF(τ)) / (1 - DF(δ))
 *
 * where DF(t) = e^{-rt}, δ = 1/frequency (payment period).
 * USD swaps pay semi-annually on the fixed leg.
 */
function flatRateAnnuity(
  expiryYears: number,
  tenorYears: number,
  flatRate: number,
  frequency: number = 2,
): number {
  const delta = 1 / frequency
  const dfExpiry = Math.exp(-flatRate * expiryYears)
  const dfPeriod = Math.exp(-flatRate * delta)
  const dfTenor = Math.exp(-flatRate * tenorYears)

  if (Math.abs(1 - dfPeriod) < 1e-10) {
    // Near-zero rate: annuity ≈ DF(T) × τ
    return dfExpiry * tenorYears
  }

  return dfExpiry * delta * dfPeriod * (1 - dfTenor) / (1 - dfPeriod)
}

/**
 * Generate AnnuityPoint[] for the full grid using flat-rate discounting.
 * Used as fallback when the Python SOFR curve backend is unavailable.
 *
 * @param flatRate - flat discount rate (default 4.3% ≈ current SOFR)
 * @param frequency - payment frequency (2 = semi-annual for USD swaps)
 */
export function computeFlatRateAnnuities(
  flatRate: number = 0.043,
  frequency: number = 2,
): AnnuityPoint[] {
  const points: AnnuityPoint[] = []

  for (const expiryLabel of EXPIRY_LABELS) {
    const T = EXPIRY_YEARS[expiryLabel as ExpiryLabel]
    for (const tenorLabel of TENOR_LABELS) {
      const tau = TENOR_YEARS[tenorLabel as TenorLabel]

      const annuity = flatRateAnnuity(T, tau, flatRate, frequency)
      const dfExpiry = Math.exp(-flatRate * T)

      points.push({
        expiry_years: T,
        tenor_years: tau,
        forward_rate: flatRate, // flat curve → forward = spot
        annuity,
        discount_factor_to_expiry: dfExpiry,
      })
    }
  }

  return points
}

// ---------------------------------------------------------------------------
// Premium grid computation
// ---------------------------------------------------------------------------

/**
 * Build a premium grid from the vol matrix and annuity data.
 *
 * @param volMatrix - bpvol/yr values [expiryIdx][tenorIdx], null for no data
 * @param annuityData - annuity points (from Python backend or flat-rate fallback)
 * @param notional - reference notional
 * @returns premium grid in $ and bps of notional
 */
export function computePremiumGrid(
  volMatrix: (number | null)[][],
  annuityData: AnnuityPoint[],
  notional: number = 100_000_000,
): { premiumGrid: (number | null)[][]; premiumBpsGrid: (number | null)[][] } {
  const expiryYearsArr = EXPIRY_LABELS.map(l => EXPIRY_YEARS[l])
  const tenorYearsArr = TENOR_LABELS.map(l => TENOR_YEARS[l])

  // Build lookup map for annuities: key = "expiryYears,tenorYears"
  const annuityMap = new Map<string, AnnuityPoint>()
  for (const pt of annuityData) {
    const ey = findClosest(pt.expiry_years, expiryYearsArr)
    const ty = findClosest(pt.tenor_years, tenorYearsArr)
    annuityMap.set(`${ey},${ty}`, pt)
  }

  const premiumGrid: (number | null)[][] = []
  const premiumBpsGrid: (number | null)[][] = []

  for (let i = 0; i < expiryYearsArr.length; i++) {
    premiumGrid.push([])
    premiumBpsGrid.push([])
    for (let j = 0; j < tenorYearsArr.length; j++) {
      const vol = volMatrix[i]?.[j]
      if (vol === null || vol === undefined) {
        premiumGrid[i].push(null)
        premiumBpsGrid[i].push(null)
        continue
      }

      const annuityPt = annuityMap.get(`${expiryYearsArr[i]},${tenorYearsArr[j]}`)
      if (!annuityPt) {
        premiumGrid[i].push(null)
        premiumBpsGrid[i].push(null)
        continue
      }

      const normalVolDecimal = vol / 10_000
      const premium = bachelierATMFStraddlePremium(
        normalVolDecimal,
        expiryYearsArr[i],
        annuityPt.annuity,
        notional,
      )
      premiumGrid[i].push(Math.round(premium))
      premiumBpsGrid[i].push(Math.round(premiumToBps(premium, notional) * 10) / 10)
    }
  }

  return { premiumGrid, premiumBpsGrid }
}

function findClosest(target: number, arr: number[]): number {
  let best = arr[0]
  let bestDist = Math.abs(target - arr[0])
  for (let i = 1; i < arr.length; i++) {
    const dist = Math.abs(target - arr[i])
    if (dist < bestDist) {
      bestDist = dist
      best = arr[i]
    }
  }
  return best
}
