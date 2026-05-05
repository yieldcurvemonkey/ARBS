import { describe, expect, it } from '@jest/globals'
import { computeEtag, matchesIfNoneMatch } from '../etag'

describe('computeEtag', () => {
  it('is deterministic for identical input', () => {
    const a = computeEtag({ x: 1, y: [2, 3] })
    const b = computeEtag({ x: 1, y: [2, 3] })
    expect(a).toBe(b)
  })

  it('differs for different input', () => {
    expect(computeEtag({ x: 1 })).not.toBe(computeEtag({ x: 2 }))
  })

  it('quotes the value (HTTP wire format)', () => {
    expect(computeEtag({ x: 1 })).toMatch(/^"[a-f0-9]{40}"$/)
  })
})

describe('matchesIfNoneMatch', () => {
  it('returns true on exact match', () => {
    const tag = computeEtag({ x: 1 })
    expect(matchesIfNoneMatch(tag, tag)).toBe(true)
  })

  it('returns true for wildcard "*"', () => {
    expect(matchesIfNoneMatch('"abc"', '*')).toBe(true)
  })

  it('returns false on mismatch', () => {
    expect(matchesIfNoneMatch('"abc"', '"def"')).toBe(false)
  })

  it('returns false when If-None-Match is missing', () => {
    expect(matchesIfNoneMatch('"abc"', null)).toBe(false)
  })

  it('handles comma-separated If-None-Match values', () => {
    expect(matchesIfNoneMatch('"b"', '"a", "b", "c"')).toBe(true)
  })
})
