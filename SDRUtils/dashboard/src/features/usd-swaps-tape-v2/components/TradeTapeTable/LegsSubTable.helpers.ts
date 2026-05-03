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
//
// PTP / PTS are package-level (same value on every leg row) so the
// summary just passes through the package-level value.
import type { UsdSwapTapeLeg, UsdSwapTapeRow } from '../../types'

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

  // OUTRIGHT / other: pass-through the single leg.
  const one = legs[0]
  return {
    rate: toNum(one.fixed_rate),
    risk: toNum(one.risk),
    opa: toNum(one.other_payment_amount),
    ptp,
    pts,
  }
}
