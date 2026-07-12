import { describe, expect, it } from '@jest/globals'
import type { UsdSwapTapeRow } from '../../types'
import {
  deriveAnalyticsSelection,
  normalizeFocusedTrade,
} from '../useFocusedTrade'

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

  it('uses the stored package_type for analytics trade_type (inferredType override removed)', () => {
    const focused = normalizeFocusedTrade(
      row({
        package_type: 'SPREADOVER_FLY',
        package_indicator: true,
        package_transaction_spread: 0.0000125,
        legs_json: [
          {
            tenor_years: 8,
            risk: -1_500,
            notional: 220_000_000,
            fixed_rate: 0.03795,
            package_transaction_spread: 0.0000125,
          } as any,
          {
            tenor_years: 9,
            risk: 3_000,
            notional: 400_000_000,
            fixed_rate: 0.0384125,
            package_transaction_spread: 0.0000125,
          } as any,
          {
            tenor_years: 10,
            risk: -1_500,
            notional: 180_000_000,
            fixed_rate: 0.0388625,
            package_transaction_spread: 0.0000125,
          } as any,
        ],
      }),
    )

    // Override removed: confidence.inferredType is always null now, so
    // trade_type falls through to row.package_type verbatim — this row
    // used to downgrade to 'FLY' via the uniform-per-leg-PTS heuristic;
    // it now trusts the stored SPREADOVER_FLY tag.
    expect(focused?.trade_type).toBe('SPREADOVER_FLY')
  })
})

// Phase C of the multi-trade dock workstream extends the focus
// surface with a `mode` enum and a `sequence: FocusedTrade[]` so
// downstream tabs can branch on selection size. The dashboard test
// runner is `node` (no jsdom), so we cover the derivation logic via
// a pure helper rather than a renderHook against the React state
// shell.
describe('deriveAnalyticsSelection — mode + sequence derivation', () => {
  it('mode = empty when nothing is selected', () => {
    const r = deriveAnalyticsSelection([])
    expect(r.mode).toBe('empty')
    expect(r.focused).toBeNull()
    expect(r.sequence).toBeNull()
  })

  it('mode = single when exactly one row is selected', () => {
    const r = deriveAnalyticsSelection([row()])
    expect(r.mode).toBe('single')
    expect(r.focused).not.toBeNull()
    expect(r.focused?.id).toBe('PKG1')
    expect(r.sequence).toBeNull()
  })

  it('mode = sequence when 2+ rows are selected', () => {
    const a = row({ package_id: 'PKG-A' })
    const b = row({ package_id: 'PKG-B' })
    const r = deriveAnalyticsSelection([a, b])
    expect(r.mode).toBe('sequence')
    expect(r.focused).toBeNull()
    expect(r.sequence).not.toBeNull()
    expect(r.sequence).toHaveLength(2)
    expect(r.sequence?.[0].id).toBe('PKG-A')
    expect(r.sequence?.[1].id).toBe('PKG-B')
  })

  it('preserves selection order in the sequence', () => {
    const a = row({ package_id: 'PKG-A' })
    const b = row({ package_id: 'PKG-B' })
    const c = row({ package_id: 'PKG-C' })
    const r = deriveAnalyticsSelection([c, a, b])
    expect(r.sequence?.map((t) => t.id)).toEqual(['PKG-C', 'PKG-A', 'PKG-B'])
  })

  it('drops null/unnormalisable entries from the sequence', () => {
    const r = deriveAnalyticsSelection([
      row({ package_id: 'PKG-A' }),
      null as unknown as UsdSwapTapeRow,
      row({ package_id: 'PKG-B' }),
    ])
    // Two valid rows survive; mode stays 'sequence' (≥2).
    expect(r.mode).toBe('sequence')
    expect(r.sequence?.map((t) => t.id)).toEqual(['PKG-A', 'PKG-B'])
  })

  it('readonly UsdSwapTapeRow[] is accepted without copy', () => {
    const ro: readonly UsdSwapTapeRow[] = [row({ package_id: 'PKG-A' })]
    const r = deriveAnalyticsSelection(ro)
    expect(r.mode).toBe('single')
  })
})
