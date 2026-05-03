import { describe, expect, it } from '@jest/globals'
import type { UsdSwapTapeRow } from '../../types'
import { normalizeFocusedTrade } from '../useFocusedTrade'

function row(overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow {
  return {
    package_id: 'PKG1',
    package_type: 'FLY',
    package_structure: '5Y/10Y/30Y FLY',
    package_tenors: '5Y/10Y/30Y',
    as_of_date: '2026-04-23',
    execution_start: '2026-04-23T09:41:02Z',
    execution_end: '2026-04-23T09:41:02Z',
    legs_count: 3,
    total_risk: 50_000,
    total_notional: 60_000_000,
    weighted_fixed_rate: 0.03875,
    package_metrics: null,
    tape_label: 'USD-SOFR-COMPOUND 1D Constant Spot 5Y/10Y/30Y FLY PHYS',
    venue: 'D2C',
    legs_json: [
      { tenor_years: 5, risk: 25_000, notional: 55_000_000, fixed_rate: 0.03637 },
      { tenor_years: 10, risk: 50_000, notional: 60_000_000, fixed_rate: 0.03875 },
      { tenor_years: 30, risk: 25_000, notional: 15_000_000, fixed_rate: 0.04145 },
    ],
    ...overrides,
  } as unknown as UsdSwapTapeRow
}

describe('normalizeFocusedTrade', () => {
  it('uses package-convention DV01/rate and package-level notional', () => {
    const focused = normalizeFocusedTrade(row())

    expect(focused?.dv01_usd_per_bp).toBe(50_000)
    expect(focused?.fixed_rate_bps).toBeCloseTo(-3.2, 2)
    expect(focused?.notional_usd).toBe(60_000_000)
  })

  it('keeps fly belly DV01 even when package totals are missing', () => {
    const focused = normalizeFocusedTrade(
      row({
        total_risk: null,
        gross_risk: null,
        total_notional: null,
        gross_notional: null,
      }),
    )

    expect(focused?.dv01_usd_per_bp).toBe(50_000)
    expect(focused?.notional_usd).toBe(130_000_000)
  })

  it('normalizes screenshot-style 2Y/5Y/10Y flies to belly DV01 and fly spread', () => {
    const focused = normalizeFocusedTrade(
      row({
        package_structure: '2Y/5Y/10Y FLY',
        package_tenors: '2Y/5Y/10Y',
        total_risk: 200_000,
        total_notional: 540_000_000,
        weighted_fixed_rate: 0.036125,
        legs_json: [
          { tenor_years: 2, risk: 50_000, notional: 260_000_000, fixed_rate: 0.03612 },
          { tenor_years: 5, risk: 100_000, notional: 220_000_000, fixed_rate: 0.03613 },
          { tenor_years: 10, risk: 50_000, notional: 60_000_000, fixed_rate: 0.03849 },
        ],
      }),
    )

    expect(focused?.dv01_usd_per_bp).toBe(100_000)
    expect(focused?.fixed_rate_bps).toBeCloseTo(-23.5, 2)
    expect(focused?.notional_usd).toBe(540_000_000)
  })
})
