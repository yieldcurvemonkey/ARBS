// ABOUTME: Premium computation engine using Bachelier (normal) model closed-form for ATMF straddles.
// Straddle premium = 2 × Annuity × σ_n × √T × √(2/π)

import {
  EXPIRY_LABELS,
  TENOR_LABELS,
  EXPIRY_YEARS,
  TENOR_YEARS,
  AnnuityPoint,
} from '../types'

const SQRT_2_OVER_PI = Math.sqrt(2 / Math.PI) // ≈ 0.7979

/**
 * Compute ATMF straddle premium using Bachelier closed-form.
 *
 * @param normalVolDecimal - normal vol in decimal (not bpvol). E.g., 0.0100 for 100bpvol.
 * @param expiryYears - time to expiry in years
 * @param annuity - annuity of the underlying swap (PV of 1bp per $1 notional × 10000)
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
  return 2 * annuity * normalVolDecimal * sqrtT * SQRT_2_OVER_PI * notional
}

/**
 * Compute premium in basis points of notional.
 */
export function premiumToBps(premium: number, notional: number = 100_000_000): number {
  return (premium / notional) * 10_000
}

/**
 * Build a premium grid from the vol matrix and annuity data.
 *
 * @param volMatrix - bpvol/yr values [expiryIdx][tenorIdx], NaN for no data
 * @param annuityData - annuity points from the Python backend
 * @param notional - reference notional
 * @returns premium grid [expiryIdx][tenorIdx] in $ per notional
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
    // Find closest grid match
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
