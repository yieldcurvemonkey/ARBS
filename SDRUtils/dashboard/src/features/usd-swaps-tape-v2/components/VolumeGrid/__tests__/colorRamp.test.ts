import { describe, expect, it } from '@jest/globals'
import { colorForPercentile, foregroundForPercentile } from '../colorRamp'

describe('colorForPercentile', () => {
  it('returns the slate fallback for null', () => {
    const out = colorForPercentile(null)
    expect(out).toMatch(/hsl/)
  })
  it('returns a slate hue at low percentiles', () => {
    expect(colorForPercentile(10)).toMatch(/^hsl\(210/)
  })
  it('returns an indigo hue at percentile 70', () => {
    expect(colorForPercentile(70)).toMatch(/^hsl\(2[0-9]{2}/)
  })
  it('returns a fuchsia hue at percentile 90', () => {
    expect(colorForPercentile(90)).toMatch(/^hsl\(3[0-9]{2}/)
  })
  it('returns a rose hue at percentile 99', () => {
    expect(colorForPercentile(99)).toMatch(/^hsl\(34[0-9]/)
  })
})

describe('foregroundForPercentile', () => {
  it('uses slate-300 at low percentile', () => {
    expect(foregroundForPercentile(10)).toMatch(/slate-300/)
  })
  it('uses slate-100 at high percentile', () => {
    expect(foregroundForPercentile(95)).toMatch(/slate-100/)
  })
  it('uses slate-500 when null', () => {
    expect(foregroundForPercentile(null)).toMatch(/slate-500/)
  })
})
