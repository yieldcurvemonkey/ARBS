import { describe, expect, it } from '@jest/globals'
import { fuzzyScore, fuzzyMatches } from '../fuzzy'

describe('fuzzyScore', () => {
  it('returns 0 for empty query (match all)', () => {
    expect(fuzzyScore('', 'anything')).toBeGreaterThanOrEqual(0)
  })

  it('returns positive score for exact substring match', () => {
    expect(fuzzyScore('sofr', 'USD-SOFR 5Y Outright')).toBeGreaterThan(0)
  })

  it('returns positive score for subsequence match (fuzzy)', () => {
    // q=sfr should still match USD-SOFR
    expect(fuzzyScore('sfr', 'USD-SOFR 5Y')).toBeGreaterThan(0)
  })

  it('returns negative for impossible match', () => {
    expect(fuzzyScore('zzz', 'USD-SOFR 5Y')).toBeLessThan(0)
  })

  it('is case-insensitive', () => {
    expect(fuzzyScore('SOFR', 'usd-sofr-compound')).toBeGreaterThan(0)
  })

  it('ranks contiguous matches higher than scattered subsequence', () => {
    const contig = fuzzyScore('outright', 'Outright 5Y')
    const scatter = fuzzyScore('otrh', 'Outright 5Y')
    expect(contig).toBeGreaterThan(scatter)
  })
})

describe('fuzzyMatches', () => {
  it('returns true when score is non-negative', () => {
    expect(fuzzyMatches('sofr', 'USD-SOFR 5Y')).toBe(true)
    expect(fuzzyMatches('zzz', 'USD-SOFR 5Y')).toBe(false)
  })

  it('treats empty query as always-match', () => {
    expect(fuzzyMatches('', 'anything')).toBe(true)
  })
})
