import { describe, expect, it } from '@jest/globals'
import {
  computePackageAdjustedDv01,
  packageAdjustedDv01Denominator,
} from '../packageAdjustedDv01'
import type { UsdSwapTapeRow } from '../../types'

const rowOf = (
  packageType: string | null,
  legRisks: Array<number | null>,
  extra: Partial<UsdSwapTapeRow> = {},
): UsdSwapTapeRow =>
  ({
    package_id: 'P1',
    package_type: packageType,
    legs_count: legRisks.length,
    legs_json: legRisks.map((r) => ({ risk: r })) as any,
    ...extra,
  } as any)

describe('packageAdjustedDv01Denominator', () => {
  it('returns 1 for OUTRIGHT', () => {
    expect(packageAdjustedDv01Denominator('OUTRIGHT', 1)).toBe(1)
  })
  it('returns 2 for CURVE', () => {
    expect(packageAdjustedDv01Denominator('CURVE', 2)).toBe(2)
  })
  it('returns 3 for FLY', () => {
    expect(packageAdjustedDv01Denominator('FLY', 3)).toBe(3)
  })
  it('returns 2 for SPREADOVER (1 swap + 1 UST)', () => {
    expect(packageAdjustedDv01Denominator('SPREADOVER', 2)).toBe(2)
  })
  it('returns 3 for SPREADOVER_CURVE (2 swap + 1 UST)', () => {
    expect(packageAdjustedDv01Denominator('SPREADOVER_CURVE', 3)).toBe(3)
  })
  it('returns 4 for SPREADOVER_FLY (3 swap + 1 UST)', () => {
    expect(packageAdjustedDv01Denominator('SPREADOVER_FLY', 4)).toBe(4)
  })
  it('returns 3 for MATCHED_MATURITY (2 swap + 1 UST)', () => {
    expect(packageAdjustedDv01Denominator('MATCHED_MATURITY', 3)).toBe(3)
  })
  it('returns leg count for unknown types', () => {
    expect(packageAdjustedDv01Denominator('MAC', 5)).toBe(5)
    expect(packageAdjustedDv01Denominator(null, 3)).toBe(3)
  })
})

describe('computePackageAdjustedDv01', () => {
  it('returns |risk| for OUTRIGHT', () => {
    expect(computePackageAdjustedDv01(rowOf('OUTRIGHT', [-12_000]))).toBe(12_000)
  })

  it('averages |risk| across both legs of a CURVE', () => {
    // 5s10s: -10K front, +12K back → (10K + 12K)/2 = 11K
    expect(
      computePackageAdjustedDv01(rowOf('CURVE', [-10_000, 12_000])),
    ).toBe(11_000)
  })

  it('averages |risk| across all three legs of a FLY', () => {
    expect(
      computePackageAdjustedDv01(rowOf('FLY', [-9_000, 18_000, -9_000])),
    ).toBe(12_000)
  })

  it('averages |risk| across all legs of a SPREADOVER (UST counts in denom)', () => {
    // 1 swap leg, 1 UST leg → /2
    expect(
      computePackageAdjustedDv01(rowOf('SPREADOVER', [10_000, -10_000])),
    ).toBe(10_000)
  })

  it('returns null when there are no legs with numeric risk', () => {
    expect(computePackageAdjustedDv01(rowOf('OUTRIGHT', [null]))).toBeNull()
    expect(computePackageAdjustedDv01(rowOf('CURVE', [null, null]))).toBeNull()
  })

  it('falls back to total_risk when legs_json risk is missing', () => {
    const row = rowOf('OUTRIGHT', [null], { total_risk: -8_000 } as any)
    expect(computePackageAdjustedDv01(row)).toBe(8_000)
  })

  it('treats missing package_type as OUTRIGHT', () => {
    expect(
      computePackageAdjustedDv01(rowOf(null, [-7_000])),
    ).toBe(7_000)
  })
})
