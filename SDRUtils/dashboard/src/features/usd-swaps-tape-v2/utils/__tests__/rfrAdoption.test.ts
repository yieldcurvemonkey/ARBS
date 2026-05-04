import { describe, expect, it } from '@jest/globals'
import {
  computeRfrAdoptionRatio,
  computeRfrAdoptionMonthly,
  RFR_NUMERATOR_KEYS,
  RFR_DENOMINATOR_KEYS,
} from '../rfrAdoption'
import type { UsdSwapTapeRow } from '../../types'

const row = (
  canonical: string | null,
  risk: number,
  ts = '2026-05-04T15:00:00Z',
): UsdSwapTapeRow =>
  ({
    package_id: `P-${Math.random()}`,
    package_type: 'OUTRIGHT',
    legs_count: 1,
    canonical_underlier_key: canonical,
    total_risk: risk,
    legs_json: [{ risk, canonical_underlier_key: canonical }],
    execution_start: ts,
  } as any)

describe('RFR_NUMERATOR_KEYS', () => {
  it('covers SOFR-OIS, Term-SOFR, OBFR-OIS, Fed-Funds-OIS', () => {
    expect(RFR_NUMERATOR_KEYS).toContain('USD/SOFR-OIS/COMPOUND')
    expect(RFR_NUMERATOR_KEYS).toContain('USD/SOFR-TERM')
    expect(RFR_NUMERATOR_KEYS).toContain('USD/OBFR-OIS/COMPOUND')
    expect(RFR_NUMERATOR_KEYS).toContain('USD/FED-FUNDS-OIS/COMPOUND')
  })

  it('does NOT include LIBOR or BSBY', () => {
    expect(RFR_NUMERATOR_KEYS).not.toContain('USD/LIBOR/IBOR')
    expect(RFR_NUMERATOR_KEYS).not.toContain('USD/BSBY/IBOR')
  })
})

describe('RFR_DENOMINATOR_KEYS', () => {
  it('includes both RFR and legacy underliers', () => {
    expect(RFR_DENOMINATOR_KEYS).toContain('USD/SOFR-OIS/COMPOUND')
    expect(RFR_DENOMINATOR_KEYS).toContain('USD/LIBOR/IBOR')
    expect(RFR_DENOMINATOR_KEYS).toContain('USD/BSBY/IBOR')
  })
})

describe('computeRfrAdoptionRatio', () => {
  it('returns 1.0 when every row is RFR', () => {
    const rows = [
      row('USD/SOFR-OIS/COMPOUND', 10_000),
      row('USD/FED-FUNDS-OIS/COMPOUND', 5_000),
    ]
    const out = computeRfrAdoptionRatio(rows)
    expect(out.ratio).toBe(1)
    expect(out.numerator).toBe(15_000)
    expect(out.denominator).toBe(15_000)
  })

  it('returns 0 when every row is legacy LIBOR', () => {
    const rows = [row('USD/LIBOR/IBOR', 8_000)]
    const out = computeRfrAdoptionRatio(rows)
    expect(out.ratio).toBe(0)
    expect(out.numerator).toBe(0)
    expect(out.denominator).toBe(8_000)
  })

  it('mixes correctly: SOFR 70%, LIBOR 30%', () => {
    const rows = [
      row('USD/SOFR-OIS/COMPOUND', 7_000),
      row('USD/LIBOR/IBOR', 3_000),
    ]
    expect(computeRfrAdoptionRatio(rows).ratio).toBeCloseTo(0.7, 6)
  })

  it('ignores rows with canonical keys outside the denom whitelist', () => {
    const rows = [
      row('USD/SOFR-OIS/COMPOUND', 10_000),
      // CMS / SIFMA-MUNI not in denom
      row('USD/ISDA-CMS', 5_000),
      row('USD/SIFMA-MUNI', 5_000),
    ]
    expect(computeRfrAdoptionRatio(rows).ratio).toBe(1)
  })

  it('returns NaN ratio when denominator is zero', () => {
    expect(computeRfrAdoptionRatio([]).ratio).toBeNaN()
  })

  it('uses |risk|, not signed', () => {
    const rows = [
      row('USD/SOFR-OIS/COMPOUND', -10_000),
      row('USD/LIBOR/IBOR', 0),
    ]
    expect(computeRfrAdoptionRatio(rows).numerator).toBe(10_000)
  })
})

describe('computeRfrAdoptionMonthly', () => {
  it('groups rows into monthly buckets and computes per-month ratios', () => {
    const rows = [
      row('USD/SOFR-OIS/COMPOUND', 10_000, '2026-03-15T00:00:00Z'),
      row('USD/LIBOR/IBOR', 10_000, '2026-03-20T00:00:00Z'),
      row('USD/SOFR-OIS/COMPOUND', 20_000, '2026-04-10T00:00:00Z'),
    ]
    const out = computeRfrAdoptionMonthly(rows)
    expect(out).toEqual([
      { month: '2026-03', ratio: 0.5, numerator: 10_000, denominator: 20_000 },
      { month: '2026-04', ratio: 1, numerator: 20_000, denominator: 20_000 },
    ])
  })

  it('skips months with no in-scope rows', () => {
    expect(computeRfrAdoptionMonthly([])).toEqual([])
  })

  it('sorts by ascending month', () => {
    const rows = [
      row('USD/SOFR-OIS/COMPOUND', 1_000, '2025-12-01T00:00:00Z'),
      row('USD/SOFR-OIS/COMPOUND', 1_000, '2025-01-01T00:00:00Z'),
      row('USD/SOFR-OIS/COMPOUND', 1_000, '2026-04-01T00:00:00Z'),
    ]
    const out = computeRfrAdoptionMonthly(rows)
    expect(out.map((r) => r.month)).toEqual(['2025-01', '2025-12', '2026-04'])
  })
})
