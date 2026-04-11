import { describe, expect, it } from '@jest/globals'
import {
  normalizeStirFilterOperator,
  parseCsvList,
  parseIsoDate
} from '@/lib/stir-dashboard-api-utils'

describe('stir-dashboard api utils', () => {
  it('normalizes filter operator to and/or', () => {
    expect(normalizeStirFilterOperator('or')).toBe('or')
    expect(normalizeStirFilterOperator('OR')).toBe('or')
    expect(normalizeStirFilterOperator('and')).toBe('and')
    expect(normalizeStirFilterOperator(undefined)).toBe('and')
  })

  it('parses iso date and rejects invalid values', () => {
    expect(parseIsoDate('2026-02-20')).toBe('2026-02-20T00:00:00.000Z')
    expect(parseIsoDate('2026-02-20T15:30:00Z')).toBe('2026-02-20T15:30:00.000Z')
    expect(parseIsoDate('not-a-date')).toBeNull()
    expect(parseIsoDate(null)).toBeNull()
  })

  it('parses comma separated lists', () => {
    expect(parseCsvList('FOMC, ECB,BOE')).toEqual(['FOMC', 'ECB', 'BOE'])
    expect(parseCsvList(' , , ')).toEqual([])
    expect(parseCsvList(undefined)).toEqual([])
  })
})
