import { describe, expect, it } from '@jest/globals'
import {
  ALL_CURVES, ALL_FLIES, BENCHMARK_CURVES, STANDARD_FLIES,
  TIGHT_CURVES, TIGHT_FLIES,
} from '../structureDefs'

describe('structureDefs', () => {
  it('benchmark curves are 2-leg structures', () => {
    for (const s of BENCHMARK_CURVES) {
      expect(s.tenors).toHaveLength(2)
      expect(s.tenors[0]).toBeLessThan(s.tenors[1])
    }
  })
  it('standard flies are 3-leg structures', () => {
    for (const s of STANDARD_FLIES) {
      expect(s.tenors).toHaveLength(3)
      expect(s.tenors[0]).toBeLessThan(s.tenors[1])
      expect(s.tenors[1]).toBeLessThan(s.tenors[2])
    }
  })
  it('ALL_CURVES = benchmark + tight', () => {
    expect(ALL_CURVES.length).toBe(BENCHMARK_CURVES.length + TIGHT_CURVES.length)
  })
  it('ALL_FLIES = standard + tight', () => {
    expect(ALL_FLIES.length).toBe(STANDARD_FLIES.length + TIGHT_FLIES.length)
  })
  it('all structure ids are unique', () => {
    const allIds = [...ALL_CURVES, ...ALL_FLIES].map((s) => s.id)
    expect(new Set(allIds).size).toBe(allIds.length)
  })
})
