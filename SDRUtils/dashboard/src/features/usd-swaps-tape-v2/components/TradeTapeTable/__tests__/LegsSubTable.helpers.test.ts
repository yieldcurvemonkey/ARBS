import { describe, expect, it } from '@jest/globals'
import type { UsdSwapTapeLeg, UsdSwapTapeRow } from '../../../types'
import { computeLegSummary } from '../LegsSubTable.helpers'


function leg(overrides: Partial<UsdSwapTapeLeg>): UsdSwapTapeLeg {
  return {
    trade_id: 'T',
    tenor_years: 5,
    fixed_rate: 0.03,
    risk: 10_000,
    other_payment_amount: 0,
    other_payment_currency: 'USD',
    ...overrides,
  } as unknown as UsdSwapTapeLeg
}

function row(pkg: string, legs: UsdSwapTapeLeg[], overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow {
  return {
    package_id: 'P',
    package_type: pkg,
    legs_json: legs,
    package_transaction_spread: null,
    package_transaction_price: null,
    package_transaction_price_currency: null,
    ...overrides,
  } as unknown as UsdSwapTapeRow
}


describe('computeLegSummary — OUTRIGHT', () => {
  it('passes through the single leg values verbatim', () => {
    const onlyLeg = leg({
      tenor_years: 10,
      fixed_rate: 0.04161,
      risk: 30_000,
      other_payment_amount: 125_000,
    })
    const summary = computeLegSummary(
      row('OUTRIGHT', [onlyLeg], {
        package_transaction_price: 100,
        package_transaction_spread: -0.003,
      }),
    )
    expect(summary.rate).toBeCloseTo(0.04161, 6)
    expect(summary.risk).toBe(30_000)
    expect(summary.opa).toBe(125_000)
    expect(summary.ptp).toBe(100)
    expect(summary.pts).toBeCloseTo(-0.003, 6)
  })
})

describe('computeLegSummary — CURVE', () => {
  it('rate = back - front, risk = back leg risk, opa = signed net', () => {
    const front = leg({
      tenor_years: 5,
      fixed_rate: 0.03605,
      risk: 25_100,
      other_payment_amount: 108_000,
      opa_sign: -1,
    })
    const back = leg({
      tenor_years: 10,
      fixed_rate: 0.03849,
      risk: 24_900,
      other_payment_amount: 127_000,
      opa_sign: 1,
    })
    const summary = computeLegSummary(row('CURVE', [front, back], {
      package_transaction_spread: 0.00244,
    }))
    expect(summary.rate).toBeCloseTo(0.03849 - 0.03605, 6)  // = 0.00244
    expect(summary.risk).toBe(24_900)
    // Signed net (ties out with the reported PTP), NOT back - front.
    expect(summary.opa).toBe(-108_000 + 127_000)             // = 19_000
    expect(summary.pts).toBeCloseTo(0.00244, 6)
  })

  it('handles unsorted legs by sorting tenor ASC first', () => {
    const back = leg({ tenor_years: 30, fixed_rate: 0.04132, risk: 25_000 })
    const front = leg({ tenor_years: 5, fixed_rate: 0.03605, risk: 25_100 })
    const summary = computeLegSummary(row('CURVE', [back, front]))
    expect(summary.rate).toBeCloseTo(0.04132 - 0.03605, 6)
    expect(summary.risk).toBe(25_000)
  })
})

describe('computeLegSummary — FLY', () => {
  it('rate = (belly-front) - (back-belly) = 2*belly - front - back', () => {
    const front = leg({
      tenor_years: 5,
      fixed_rate: 0.03605,
      risk: 25_000,
      other_payment_amount: 108_000,
      opa_sign: -1,
    })
    const belly = leg({
      tenor_years: 10,
      fixed_rate: 0.03849,
      risk: 50_000,
      other_payment_amount: 127_000,
      opa_sign: 1,
    })
    const back = leg({
      tenor_years: 30,
      fixed_rate: 0.04132,
      risk: 25_000,
      other_payment_amount: 2_700,
      opa_sign: -1,
    })
    const summary = computeLegSummary(row('FLY', [front, belly, back]))
    // 2 * 0.03849 - 0.03605 - 0.04132 = -0.00039
    expect(summary.rate).toBeCloseTo(-0.00039, 6)
    // Belly leg risk
    expect(summary.risk).toBe(50_000)
    // Signed net: -108k + 127k - 2.7k. OPAs are settlement amounts that
    // tie out with the reported PTP — fly-weighting does not apply.
    expect(summary.opa).toBeCloseTo(16_300, 2)
  })

  it('handles unsorted FLY legs', () => {
    const belly = leg({ tenor_years: 7, fixed_rate: 0.038, risk: 50_000 })
    const back = leg({ tenor_years: 10, fixed_rate: 0.041, risk: 25_000 })
    const front = leg({ tenor_years: 5, fixed_rate: 0.036, risk: 25_000 })
    const summary = computeLegSummary(row('FLY', [back, front, belly]))
    expect(summary.rate).toBeCloseTo(2 * 0.038 - 0.036 - 0.041, 6)
    expect(summary.risk).toBe(50_000)
  })

  it('detects fly packages from composite labels', () => {
    const front = leg({ tenor_years: 2, fixed_rate: 0.03612, risk: 50_000 })
    const belly = leg({ tenor_years: 5, fixed_rate: 0.03613, risk: 100_000 })
    const back = leg({ tenor_years: 10, fixed_rate: 0.03849, risk: 50_000 })
    const summary = computeLegSummary(
      row('USD-SOFR-OIS Compound 1D Constant Spot 2Y/5Y/10Y FLY PHYS', [
        front,
        belly,
        back,
      ]),
    )
    expect(summary.rate).toBeCloseTo(2 * 0.03613 - 0.03612 - 0.03849, 6)
    expect(summary.risk).toBe(100_000)
  })
})

describe('computeLegSummary — PACKAGE (multi-leg)', () => {
  it('uses row.opa_signed_net when available', () => {
    const legs = [
      leg({ tenor_years: 5, fixed_rate: 0.04, risk: 50_000, other_payment_amount: 500_000 }),
      leg({ tenor_years: 10, fixed_rate: 0.045, risk: 100_000, other_payment_amount: 800_000 }),
      leg({ tenor_years: 30, fixed_rate: 0.04, risk: 50_000, other_payment_amount: 300_000 }),
    ]
    const summary = computeLegSummary(
      row('PACKAGE', legs, {
        opa_signed_net: 1_000_000,
        package_transaction_price: 1_000_000,
      }),
    )
    expect(summary.opa).toBe(1_000_000)
  })

  it('sums per-leg opa_sign × opa when opa_signed_net missing', () => {
    const legs = [
      leg({ tenor_years: 5, risk: 50_000, other_payment_amount: 500_000, opa_sign: 1 }),
      leg({ tenor_years: 10, risk: 100_000, other_payment_amount: 800_000, opa_sign: -1 }),
      leg({ tenor_years: 30, risk: 50_000, other_payment_amount: 300_000, opa_sign: 1 }),
    ]
    const summary = computeLegSummary(row('PACKAGE', legs))
    // 500K - 800K + 300K = 0
    expect(summary.opa).toBe(0)
  })

  it('falls back to client-side solver when no signs or opa_signed_net', () => {
    const legs = [
      leg({ tenor_years: 5, risk: 50_000, other_payment_amount: 500_000 }),
      leg({ tenor_years: 10, risk: 100_000, other_payment_amount: 300_000 }),
    ]
    const summary = computeLegSummary(
      row('PACKAGE', legs, { package_transaction_price: 200_000 }),
    )
    // 500K - 300K = 200K is the exact match to PTP
    expect(summary.opa).toBeCloseTo(200_000, 0)
  })

  it('computes correct OPA for the 15-leg 7/2/2026 example', () => {
    const opaValues = [
      1_800_000, 1_700_000, 192_000, 6_800, 2_400,
      580_000, 82_600, 1_400_000, 3_500_000, 334_000,
      1_200_000, 19_600, 966_000, 1_100_000, 1_700_000,
    ]
    const riskValues = [
      100_000, 100_000, 36_000, 3_000, 2_000,
      150_000, 17_000, 169_000, 170_000, 100_000,
      150_000, 185_000, 108_000, 200_000, 200_000,
    ]
    const rateValues = [
      0.04395, 0.04381, 0.04271, 0.04237, 0.04231,
      0.04172, 0.04164, 0.04135, 0.04011, 0.04251,
      0.04296, 0.04220, 0.04130, 0.04167, 0.04136,
    ]
    const pkgLegs = opaValues.map((opa, i) =>
      leg({
        tenor_years: 30,
        other_payment_amount: opa,
        risk: riskValues[i],
        fixed_rate: rateValues[i],
      }),
    )
    const summary = computeLegSummary(
      row('PACKAGE', pkgLegs, { package_transaction_price: 13_200_000 }),
    )
    // Optimal: ~13,200,600 — within 1K of PTP
    expect(summary.opa).not.toBeNull()
    expect(Math.abs(summary.opa! - 13_200_000)).toBeLessThan(1_000)
  })

  it('sums absolute risk across all legs', () => {
    const legs = [
      leg({ tenor_years: 5, risk: 50_000, other_payment_amount: 100_000, opa_sign: 1 }),
      leg({ tenor_years: 10, risk: -30_000, other_payment_amount: 200_000, opa_sign: 1 }),
      leg({ tenor_years: 30, risk: 20_000, other_payment_amount: 300_000, opa_sign: 1 }),
    ]
    const summary = computeLegSummary(row('PACKAGE', legs))
    expect(summary.risk).toBe(100_000) // 50K + 30K + 20K
  })

  it('computes DV01-weighted average rate', () => {
    const legs = [
      leg({ tenor_years: 5, fixed_rate: 0.03, risk: 100_000, other_payment_amount: 0, opa_sign: 1 }),
      leg({ tenor_years: 10, fixed_rate: 0.04, risk: 100_000, other_payment_amount: 0, opa_sign: 1 }),
    ]
    const summary = computeLegSummary(row('PACKAGE', legs))
    // Equal-weighted average: (0.03 + 0.04) / 2 = 0.035
    expect(summary.rate).toBeCloseTo(0.035, 6)
  })

  it('does not enter PACKAGE path for non-CURVE/FLY multi-leg with only 1 leg', () => {
    const onlyLeg = leg({
      tenor_years: 10,
      fixed_rate: 0.04,
      risk: 30_000,
      other_payment_amount: 125_000,
    })
    const summary = computeLegSummary(row('OUTRIGHT', [onlyLeg]))
    expect(summary.rate).toBeCloseTo(0.04, 6)
    expect(summary.risk).toBe(30_000)
    expect(summary.opa).toBe(125_000)
  })
})

describe('computeLegSummary — pkg fallbacks', () => {
  it('passes package-level PTP and PTS unchanged for all pkg types', () => {
    const legs = [
      leg({ tenor_years: 5, fixed_rate: 0.03, risk: 20_000 }),
      leg({ tenor_years: 10, fixed_rate: 0.04, risk: 20_000 }),
    ]
    const summary = computeLegSummary(
      row('CURVE', legs, {
        package_transaction_price: 250,
        package_transaction_price_currency: 'USD',
        package_transaction_spread: 0.01,
      }),
    )
    expect(summary.ptp).toBe(250)
    expect(summary.pts).toBeCloseTo(0.01, 6)
  })

  it('returns nulls for missing values without throwing', () => {
    const summary = computeLegSummary(row('OUTRIGHT', []))
    expect(summary.rate).toBeNull()
    expect(summary.risk).toBeNull()
    expect(summary.opa).toBeNull()
    expect(summary.ptp).toBeNull()
    expect(summary.pts).toBeNull()
  })
})
