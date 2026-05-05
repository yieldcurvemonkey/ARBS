import { describe, expect, it } from '@jest/globals'
import { colorForPercentile, foregroundForPercentile } from '../colorRamp'

describe('colorForPercentile', () => {
  it('returns the slate fallback for null', () => {
    const out = colorForPercentile(null)
    expect(out).toBe('rgb(30, 41, 59)')
  })
  it('returns cool blue at low percentiles', () => {
    expect(colorForPercentile(0)).toBe('rgb(59, 76, 192)')
  })
  it('returns a neutral midpoint', () => {
    expect(colorForPercentile(50)).toBe('rgb(221, 221, 221)')
  })
  it('returns warm red at high percentiles', () => {
    expect(colorForPercentile(100)).toBe('rgb(180, 4, 38)')
  })
})

describe('foregroundForPercentile', () => {
  it('uses light text at the dark blue tail', () => {
    expect(foregroundForPercentile(10)).toMatch(/slate-100/)
  })
  it('uses dark text near the neutral midpoint', () => {
    expect(foregroundForPercentile(50)).toMatch(/slate-950/)
  })
  it('uses light text at the dark red tail', () => {
    expect(foregroundForPercentile(95)).toMatch(/slate-100/)
  })
  it('uses slate-500 when null', () => {
    expect(foregroundForPercentile(null)).toMatch(/slate-500/)
  })
})
