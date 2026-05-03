import { describe, expect, it } from '@jest/globals'
import type { UsdSwapTapeLeg, UsdSwapTapeRow } from '../../types'
import { computePackageConfidence } from '../packageConfidence'

const baseRow = (overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow =>
  ({
    package_id: 'P1',
    package_type: 'OUTRIGHT',
    package_indicator: null,
    n_package_legs: 1,
    legs_count: 1,
    legs_json: [],
    package_metrics: {},
    ...overrides,
  }) as UsdSwapTapeRow

describe('computePackageConfidence — OUTRIGHT', () => {
  it('returns 2/2 for a vanilla outright with no package indicator', () => {
    const result = computePackageConfidence(baseRow())
    expect(result.score).toBe(2)
    expect(result.total).toBe(2)
    expect(result.tone).toBe('info')
    expect(result.signals.map((s) => s.name)).toEqual([
      'package_indicator_off',
      'leg_count',
    ])
    expect(result.signals.every((s) => s.passed)).toBe(true)
  })
})

const curveLeg = (overrides: Partial<UsdSwapTapeLeg>): UsdSwapTapeLeg =>
  ({
    trade_id: 'T',
    tenor_years: 5,
    risk: 0,
    fixed_rate: 0,
    notional: 100_000_000,
    ...overrides,
  }) as UsdSwapTapeLeg

describe('computePackageConfidence — CURVE', () => {
  const curveRow = (overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow =>
    baseRow({
      package_type: 'CURVE',
      package_indicator: true,
      n_package_legs: 2,
      package_transaction_spread: 50,
      legs_json: [
        curveLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 3.5 }),
        curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.0 }),
      ],
      ...overrides,
    })

  it('returns 5/5 for a textbook 5s10s with PTS=50', () => {
    const result = computePackageConfidence(curveRow())
    expect(result.score).toBe(5)
    expect(result.total).toBe(5)
    expect(result.tone).toBe('high')
  })

  it('fails risk balance when belly-leg DV01 imbalanced > 10%', () => {
    const result = computePackageConfidence(
      curveRow({
        legs_json: [
          curveLeg({ tenor_years: 5, risk: -2_000, fixed_rate: 3.5 }),
          curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.0 }),
        ],
      }),
    )
    expect(result.score).toBe(4)
    expect(
      result.signals.find((s) => s.name === 'risk_balance')?.passed,
    ).toBe(false)
  })

  it('fails PTS match when derived spread is more than 0.5 bp off', () => {
    const result = computePackageConfidence(
      curveRow({
        package_transaction_spread: 50,
        legs_json: [
          curveLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 3.5 }),
          // 4.01 - 3.5 = 0.51% = 51 bp — 1 bp off reported 50.
          curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.01 }),
        ],
      }),
    )
    expect(result.score).toBe(4)
    expect(result.signals.find((s) => s.name === 'pts_match')?.passed).toBe(false)
  })

  it('fails leg count when 3 legs are stamped CURVE', () => {
    const result = computePackageConfidence(
      curveRow({
        n_package_legs: 3,
        legs_json: [
          curveLeg({ tenor_years: 2, risk: -2_500, fixed_rate: 3.0 }),
          curveLeg({ tenor_years: 5, risk: -2_500, fixed_rate: 3.5 }),
          curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.0 }),
        ],
      }),
    )
    expect(result.signals.find((s) => s.name === 'leg_count')?.passed).toBe(false)
  })

  it('fails tenor monotonicity when legs are not ascending', () => {
    const result = computePackageConfidence(
      curveRow({
        legs_json: [
          curveLeg({ tenor_years: 10, risk: -5_000, fixed_rate: 4.0 }),
          curveLeg({ tenor_years: 5, risk: 5_000, fixed_rate: 3.5 }),
        ],
      }),
    )
    expect(
      result.signals.find((s) => s.name === 'tenor_monotonic')?.passed,
    ).toBe(false)
  })
})

describe('computePackageConfidence — FLY', () => {
  const flyRow = (overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow =>
    baseRow({
      package_type: 'FLY',
      package_indicator: true,
      n_package_legs: 3,
      // 2*3.85 - 3.50 - 4.00 = 0.20% = 20 bp.
      package_transaction_spread: 20,
      legs_json: [
        curveLeg({ tenor_years: 5, risk: -2_500, fixed_rate: 3.5 }),
        curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 3.85 }),
        curveLeg({ tenor_years: 30, risk: -2_500, fixed_rate: 4.0 }),
      ],
      ...overrides,
    })

  it('returns 5/5 for a textbook 5/10/30 fly', () => {
    const result = computePackageConfidence(flyRow())
    expect(result.score).toBe(5)
    expect(result.total).toBe(5)
    expect(result.tone).toBe('high')
  })

  it('fails belly = -2*wings when belly DV01 is off by 25%', () => {
    const result = computePackageConfidence(
      flyRow({
        legs_json: [
          curveLeg({ tenor_years: 5, risk: -2_500, fixed_rate: 3.5 }),
          // belly under-weighted: should be 5000, given 3750
          curveLeg({ tenor_years: 10, risk: 3_750, fixed_rate: 3.85 }),
          curveLeg({ tenor_years: 30, risk: -2_500, fixed_rate: 4.0 }),
        ],
      }),
    )
    expect(result.score).toBe(4)
    expect(
      result.signals.find((s) => s.name === 'risk_balance')?.passed,
    ).toBe(false)
  })

  it('fails PTS match when derived bfly is 0.8 bp off reported PTS', () => {
    const result = computePackageConfidence(
      flyRow({
        package_transaction_spread: 20,
        legs_json: [
          curveLeg({ tenor_years: 5, risk: -2_500, fixed_rate: 3.5 }),
          // 2*3.854 - 3.5 - 4.0 = 0.208% = 20.8 bp; off by 0.8 bp.
          curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 3.854 }),
          curveLeg({ tenor_years: 30, risk: -2_500, fixed_rate: 4.0 }),
        ],
      }),
    )
    expect(result.signals.find((s) => s.name === 'pts_match')?.passed).toBe(false)
  })

  it('fails leg count when only 2 legs are stamped FLY', () => {
    const result = computePackageConfidence(
      flyRow({
        n_package_legs: 2,
        legs_json: [
          curveLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 3.5 }),
          curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 3.85 }),
        ],
      }),
    )
    expect(result.signals.find((s) => s.name === 'leg_count')?.passed).toBe(false)
  })
})

describe('computePackageConfidence — SPREADOVER', () => {
  it('returns 3/3 when indicator on, has_spread true, PTS non-zero', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'SPREADOVER',
        package_indicator: true,
        has_spread: true,
        package_transaction_spread: 12,
        n_package_legs: 1,
        legs_json: [curveLeg({ tenor_years: 5 })],
      }),
    )
    expect(result.score).toBe(3)
    expect(result.total).toBe(3)
  })

  it('fails PTS-non-zero signal when PTS is missing', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'SPREADOVER',
        package_indicator: true,
        has_spread: true,
        package_transaction_spread: null,
        n_package_legs: 1,
        legs_json: [curveLeg({ tenor_years: 5 })],
      }),
    )
    expect(result.signals.find((s) => s.name === 'pts_present')?.passed).toBe(false)
  })
})

describe('computePackageConfidence — MATCHED_MATURITY', () => {
  it('returns 3/3 when legs share maturity and rate indices differ', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'MATCHED_MATURITY',
        package_indicator: true,
        n_package_legs: 2,
        legs_json: [
          curveLeg({
            tenor_years: 10,
            swap_maturity_date: '2036-05-01',
            rate_index_clean: 'USD-SOFR',
          }),
          curveLeg({
            tenor_years: 10,
            swap_maturity_date: '2036-05-01',
            rate_index_clean: 'USD-LIBOR',
          }),
        ],
      }),
    )
    expect(result.score).toBe(3)
    expect(result.total).toBe(3)
  })

  it('fails same-maturity when leg maturities differ', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'MATCHED_MATURITY',
        package_indicator: true,
        n_package_legs: 2,
        legs_json: [
          curveLeg({
            tenor_years: 10,
            swap_maturity_date: '2036-05-01',
            rate_index_clean: 'USD-SOFR',
          }),
          curveLeg({
            tenor_years: 10,
            swap_maturity_date: '2037-05-01',
            rate_index_clean: 'USD-LIBOR',
          }),
        ],
      }),
    )
    expect(result.signals.find((s) => s.name === 'same_maturity')?.passed).toBe(false)
  })
})
