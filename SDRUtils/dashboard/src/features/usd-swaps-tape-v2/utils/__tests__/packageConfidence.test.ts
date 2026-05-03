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
