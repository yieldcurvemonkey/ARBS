// Pure-function helpers for the expanded legs sub-table.
//
// Aggregation rules for the summary row at the bottom of the expanded
// leg-details table (per trader-desk convention):
//
//   OUTRIGHT: summary values = the single leg's values, verbatim.
//   CURVE:    summary.rate = back_rate - front_rate
//             summary.risk = back_leg.risk
//             summary.opa  = back_opa - front_opa
//   FLY:      summary.rate = (belly_rate - front_rate) - (back_rate - belly_rate)
//                          = 2*belly_rate - front_rate - back_rate
//             summary.risk = belly_leg.risk
//             summary.opa  = (belly_opa - front_opa) - (back_opa - belly_opa)
//                          = 2*belly_opa - front_opa - back_opa
//   PACKAGE:  summary.opa  = Σ(opa_sign_i × opa_i) with signs chosen
//                            so the signed sum ≈ PTP (subset-sum opt).
//             summary.risk = Σ|risk_i| across all legs.
//             summary.rate = DV01-weighted average rate.
//
// PTP / PTS are package-level (same value on every leg row) so the
// summary just passes through the package-level value.
import type { UsdSwapTapeLeg, UsdSwapTapeRow } from '../../types'
import { solveOpaSigns } from '../../utils/opaSignSolver'

export interface LegSummary {
  rate: number | null
  risk: number | null
  opa: number | null
  ptp: number | null
  pts: number | null
}


function toNum(v: unknown): number | null {
  if (v === null || v === undefined) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}


function sortByTenorAsc(legs: UsdSwapTapeLeg[]): UsdSwapTapeLeg[] {
  return [...legs].sort((a, b) => {
    const at = typeof a?.tenor_years === 'number' ? a.tenor_years : Number.POSITIVE_INFINITY
    const bt = typeof b?.tenor_years === 'number' ? b.tenor_years : Number.POSITIVE_INFINITY
    return at - bt
  })
}


export function computeLegSummary(row: UsdSwapTapeRow): LegSummary {
  const legs = sortByTenorAsc((row.legs_json ?? []) as UsdSwapTapeLeg[])
  const kindContext = [
    row.package_type,
    row.trade_type,
    row.tape_label,
    row.package_structure,
  ]
    .map((v) => String(v ?? '').toUpperCase())
    .join(' ')
  const isCurve = /(^|[^A-Z0-9])CURVE([^A-Z0-9]|$)/.test(kindContext)
  const isFly = /(^|[^A-Z0-9])FLY([^A-Z0-9]|$)/.test(kindContext)
  const ptp = toNum(row.package_transaction_price)
  const pts = toNum(row.package_transaction_spread)

  if (legs.length === 0) {
    return { rate: null, risk: null, opa: null, ptp, pts }
  }

  if (isCurve && legs.length >= 2) {
    const front = legs[0]
    const back = legs[legs.length - 1]
    const frate = toNum(front.fixed_rate)
    const brate = toNum(back.fixed_rate)
    const fopa = toNum(front.other_payment_amount)
    const bopa = toNum(back.other_payment_amount)
    return {
      rate: frate !== null && brate !== null ? brate - frate : null,
      risk: toNum(back.risk),
      opa: fopa !== null && bopa !== null ? bopa - fopa : null,
      ptp,
      pts,
    }
  }

  if (isFly && legs.length >= 3) {
    const front = legs[0]
    // Belly = middle-tenor leg after sort (len // 2).
    const belly = legs[Math.floor(legs.length / 2)]
    const back = legs[legs.length - 1]
    const frate = toNum(front.fixed_rate)
    const mrate = toNum(belly.fixed_rate)
    const brate = toNum(back.fixed_rate)
    const fopa = toNum(front.other_payment_amount)
    const mopa = toNum(belly.other_payment_amount)
    const bopa = toNum(back.other_payment_amount)
    return {
      rate:
        frate !== null && mrate !== null && brate !== null
          ? 2 * mrate - frate - brate
          : null,
      risk: toNum(belly.risk),
      opa:
        fopa !== null && mopa !== null && bopa !== null
          ? 2 * mopa - fopa - bopa
          : null,
      ptp,
      pts,
    }
  }

  // PACKAGE (multi-leg, not CURVE/FLY): signed OPA aggregation.
  if (legs.length > 1) {
    return computePackageSummary(row, legs, ptp, pts)
  }

  // OUTRIGHT: pass-through the single leg.
  const one = legs[0]
  return {
    rate: toNum(one.fixed_rate),
    risk: toNum(one.risk),
    opa: toNum(one.other_payment_amount),
    ptp,
    pts,
  }
}


function computePackageSummary(
  row: UsdSwapTapeRow,
  legs: UsdSwapTapeLeg[],
  ptp: number | null,
  pts: number | null,
): LegSummary {
  // --- OPA: 3-tier fallback ---
  // 1. Row-level pre-computed opa_signed_net (fastest, authoritative).
  // 2. Per-leg opa_sign × opa — sum the backend's sign assignments.
  // 3. Client-side subset-sum solver against PTP (fallback for old data).
  let opa: number | null = toNum(row.opa_signed_net)

  if (opa === null) {
    const hasAnySigns = legs.some((l) => l.opa_sign != null)
    if (hasAnySigns) {
      opa = 0
      for (const l of legs) {
        const amount = toNum(l.other_payment_amount)
        if (amount === null) continue
        const sign = l.opa_sign ?? 1
        opa += sign * amount
      }
    } else if (ptp !== null) {
      const opaValues = legs
        .map((l) => toNum(l.other_payment_amount))
        .filter((v): v is number => v !== null)
      if (opaValues.length > 0) {
        const result = solveOpaSigns(opaValues, ptp)
        opa = result.net
      }
    }
  }

  // --- Risk: sum of absolute DV01 across legs ---
  let risk: number | null = null
  let riskSum = 0
  let hasRisk = false
  for (const l of legs) {
    const r = toNum(l.risk)
    if (r !== null) {
      riskSum += Math.abs(r)
      hasRisk = true
    }
  }
  if (hasRisk) risk = riskSum

  // --- Rate: DV01-weighted average ---
  let rate: number | null = null
  let weightedRateSum = 0
  let totalWeight = 0
  for (const l of legs) {
    const r = toNum(l.fixed_rate)
    const w = toNum(l.risk)
    if (r !== null && w !== null && w !== 0) {
      weightedRateSum += r * Math.abs(w)
      totalWeight += Math.abs(w)
    }
  }
  if (totalWeight > 0) rate = weightedRateSum / totalWeight

  return { rate, risk, opa, ptp, pts }
}
