import { describe, expect, it } from '@jest/globals'
import { buildFomcConstantMaturityMap, fomcAliasForLabel } from '../fomcConstantMaturity'

describe('buildFomcConstantMaturityMap', () => {
  it('maps FOMC1 to next upcoming meeting', () => {
    const now = new Date('2026-05-16T12:00:00Z')
    const map = buildFomcConstantMaturityMap(now)
    expect(map.get('FOMC1')).toBe('JUN26')
  })

  it('maps FOMC2 to second upcoming meeting', () => {
    const now = new Date('2026-05-16T12:00:00Z')
    const map = buildFomcConstantMaturityMap(now)
    expect(map.get('FOMC2')).toBe('SEP26')
  })

  it('returns empty map for far-future date with no meetings', () => {
    const now = new Date('2099-01-01T00:00:00Z')
    const map = buildFomcConstantMaturityMap(now)
    expect(map.size).toBe(0)
  })

  it('fomcAliasForLabel returns alias for known label', () => {
    const now = new Date('2026-05-16T12:00:00Z')
    const map = buildFomcConstantMaturityMap(now)
    expect(fomcAliasForLabel('JUN26', map)).toBe('FOMC1')
  })

  it('fomcAliasForLabel returns null for unknown label', () => {
    const now = new Date('2026-05-16T12:00:00Z')
    const map = buildFomcConstantMaturityMap(now)
    expect(fomcAliasForLabel('ZZZ99', map)).toBeNull()
  })
})
