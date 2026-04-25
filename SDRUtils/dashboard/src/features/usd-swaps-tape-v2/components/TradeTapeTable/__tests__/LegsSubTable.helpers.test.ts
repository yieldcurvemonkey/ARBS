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
  it('rate = back - front, risk = back leg risk, opa = back - front', () => {
    const front = leg({
      tenor_years: 5,
      fixed_rate: 0.03605,
      risk: 25_100,
      other_payment_amount: 108_000,
    })
    const back = leg({
      tenor_years: 10,
      fixed_rate: 0.03849,
      risk: 24_900,
      other_payment_amount: 127_000,
    })
    const summary = computeLegSummary(row('CURVE', [front, back], {
      package_transaction_spread: 0.00244,
    }))
    expect(summary.rate).toBeCloseTo(0.03849 - 0.03605, 6)  // = 0.00244
    expect(summary.risk).toBe(24_900)
    expect(summary.opa).toBe(127_000 - 108_000)              // = 19_000
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
    })
    const belly = leg({
      tenor_years: 10,
      fixed_rate: 0.03849,
      risk: 50_000,
      other_payment_amount: 127_000,
    })
    const back = leg({
      tenor_years: 30,
      fixed_rate: 0.04132,
      risk: 25_000,
      other_payment_amount: 2_700,
    })
    const summary = computeLegSummary(row('FLY', [front, belly, back]))
    // 2 * 0.03849 - 0.03605 - 0.04132 = -0.00039
    expect(summary.rate).toBeCloseTo(-0.00039, 6)
    // Back leg risk
    expect(summary.risk).toBe(25_000)
    // 2 * 127 - 108 - 2.7 = 143.3 k
    expect(summary.opa).toBeCloseTo(143_300, 2)
  })

  it('handles unsorted FLY legs', () => {
    const belly = leg({ tenor_years: 7, fixed_rate: 0.038, risk: 50_000 })
    const back = leg({ tenor_years: 10, fixed_rate: 0.041, risk: 25_000 })
    const front = leg({ tenor_years: 5, fixed_rate: 0.036, risk: 25_000 })
    const summary = computeLegSummary(row('FLY', [back, front, belly]))
    expect(summary.rate).toBeCloseTo(2 * 0.038 - 0.036 - 0.041, 6)
    expect(summary.risk).toBe(25_000)
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
