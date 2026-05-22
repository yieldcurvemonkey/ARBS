import { describe, expect, it } from '@jest/globals'
import {
  ALL_CURVES, ALL_FLIES, BENCHMARK_CURVES, BENCHMARK_FLIES,
  MICRO_CURVES, MICRO_FLIES, WIDE_CURVES, WIDE_FLIES,
} from '../structureDefs'

describe('structureDefs', () => {
  it('all curves are 2-leg structures sorted by tenors', () => {
    for (const s of ALL_CURVES) {
      expect(s.tenors).toHaveLength(2)
      expect(s.tenors[0]).toBeLessThan(s.tenors[1])
    }
    for (let i = 1; i < ALL_CURVES.length; i++) {
      const prev = ALL_CURVES[i - 1].tenors
      const curr = ALL_CURVES[i].tenors
      expect(prev[0] < curr[0] || (prev[0] === curr[0] && prev[1] <= curr[1])).toBe(true)
    }
  })
  it('all flies are 3-leg structures sorted by tenors', () => {
    for (const s of ALL_FLIES) {
      expect(s.tenors).toHaveLength(3)
      expect(s.tenors[0]).toBeLessThan(s.tenors[1])
      expect(s.tenors[1]).toBeLessThan(s.tenors[2])
    }
  })
  it('ALL_CURVES deduplicates across categories', () => {
    const combined = [...BENCHMARK_CURVES, ...WIDE_CURVES, ...MICRO_CURVES]
    expect(ALL_CURVES.length).toBeLessThanOrEqual(combined.length)
    expect(ALL_CURVES.length).toBeGreaterThanOrEqual(BENCHMARK_CURVES.length)
  })
  it('ALL_FLIES deduplicates across categories', () => {
    const combined = [...BENCHMARK_FLIES, ...WIDE_FLIES, ...MICRO_FLIES]
    expect(ALL_FLIES.length).toBeLessThanOrEqual(combined.length)
    expect(ALL_FLIES.length).toBeGreaterThanOrEqual(BENCHMARK_FLIES.length)
  })
  it('micro curves include consecutive-year pairs', () => {
    expect(MICRO_CURVES.some(s => s.id === '3s4s')).toBe(true)
    expect(MICRO_CURVES.some(s => s.id === '7s8s')).toBe(true)
  })
  it('micro flies include consecutive-year triples', () => {
    expect(MICRO_FLIES.some(s => s.id === '3s4s5s')).toBe(true)
    expect(MICRO_FLIES.some(s => s.id === '7s8s9s')).toBe(true)
  })
  it('all structure ids are unique across curves and flies', () => {
    const allIds = [...ALL_CURVES, ...ALL_FLIES].map((s) => s.id)
    expect(new Set(allIds).size).toBe(allIds.length)
  })
  it('comprehensive: at least 30 curves and 30 flies', () => {
    expect(ALL_CURVES.length).toBeGreaterThanOrEqual(30)
    expect(ALL_FLIES.length).toBeGreaterThanOrEqual(30)
  })
})
