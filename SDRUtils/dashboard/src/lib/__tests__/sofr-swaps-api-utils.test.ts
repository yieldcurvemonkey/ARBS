import { describe, expect, it } from '@jest/globals'
import {
  normalizeFilterOperator,
  parseColumnFilters,
  parseSeriesKey
} from '../sofr-swaps-api-utils'

describe('sofr-swaps-api-utils', () => {
  it('parses strict forward x tenor keys', () => {
    // parseSeriesKey now also derives numeric year values alongside the labels
    expect(parseSeriesKey('3Mx10Y')).toEqual({
      forwardLabel: '3M',
      forwardYears: 0.25,
      tenorLabel: '10Y',
      tenorYears: 10,
      isValid: true
    })
    expect(parseSeriesKey('bad-key').isValid).toBe(false)
  })

  it('normalizes filter operator', () => {
    expect(normalizeFilterOperator('or')).toBe('or')
    expect(normalizeFilterOperator('OR')).toBe('or')
    expect(normalizeFilterOperator('and')).toBe('and')
    expect(normalizeFilterOperator(null)).toBe('and')
  })

  it('parses column filter json payloads safely', () => {
    const parsed = parseColumnFilters(
      JSON.stringify({
        action: { operator: 'and', constraints: [{ value: 'TRAD', matchMode: 'contains' }] }
      })
    )
    expect(parsed.action?.constraints?.[0]?.value).toBe('TRAD')
    expect(parseColumnFilters('not-json')).toEqual({})
    expect(parseColumnFilters(null)).toEqual({})
  })
})
