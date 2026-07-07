import { describe, expect, it } from '@jest/globals'
import { solveOpaSigns } from '../opaSignSolver'

describe('solveOpaSigns', () => {
  it('returns UNRESOLVED for empty opa list', () => {
    const result = solveOpaSigns([], 1_000_000)
    expect(result.signs).toEqual([])
    expect(result.confidence).toBe('UNRESOLVED')
  })

  it('returns all +1 when ptp is 0', () => {
    const result = solveOpaSigns([100, 200], 0)
    expect(result.signs).toEqual([1, 1])
    expect(result.confidence).toBe('UNRESOLVED')
  })

  it('EXACT match on simple 2-leg case', () => {
    const result = solveOpaSigns([500_000, 300_000], 200_000)
    expect(result.net).toBeCloseTo(200_000, 0)
    expect(result.confidence).toBe('EXACT')
    const computed = result.signs[0] * 500_000 + result.signs[1] * 300_000
    expect(Math.abs(computed - 200_000)).toBeLessThan(100)
  })

  it('solves the 15-leg 7/2/2026 package correctly (~13.2M target)', () => {
    const opaValues = [
      1_800_000, 1_700_000, 192_000, 6_800, 2_400,
      580_000, 82_600, 1_400_000, 3_500_000, 334_000,
      1_200_000, 19_600, 966_000, 1_100_000, 1_700_000,
    ]
    const ptp = 13_200_000
    const result = solveOpaSigns(opaValues, ptp)

    expect(Math.abs(result.net - ptp)).toBeLessThan(1_000)
    // Residual = 600 → TIGHT tier (100 < 600 < 1000).
    expect(result.confidence).toBe('TIGHT')
    expect(result.residual).toBeLessThan(700)
  })

  it('prefers net closer to +ptp over -ptp on ties', () => {
    const result = solveOpaSigns([100], 100)
    expect(result.signs).toEqual([1])
    expect(result.net).toBe(100)
  })

  it('handles single leg matching PTP exactly', () => {
    const result = solveOpaSigns([5_000_000], 5_000_000)
    expect(result.signs).toEqual([1])
    expect(result.net).toBe(5_000_000)
    expect(result.residual).toBe(0)
    expect(result.confidence).toBe('EXACT')
  })

  it('uses greedy for N > 20', () => {
    const opa = Array.from({ length: 22 }, (_, i) => (i + 1) * 10_000)
    const ptp = opa.reduce((s, v) => s + v, 0) - 2 * 30_000
    const result = solveOpaSigns(opa, ptp)
    expect(result.signs.length).toBe(22)
    expect(result.residual).toBeLessThan(50_000)
  })
})
