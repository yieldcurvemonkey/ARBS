import { describe, expect, it } from '@jest/globals'
import { matchTimestampRange } from '../TimestampColumnFilter.helpers'

describe('matchTimestampRange', () => {
  const at = (hhmmss: string) => `2026-04-14T${hhmmss}Z`

  it('returns true when the range is null or both endpoints are empty', () => {
    expect(matchTimestampRange(at('14:30:00'), null)).toBe(true)
    expect(matchTimestampRange(at('14:30:00'), [null, null])).toBe(true)
  })

  it('from-only: includes rows at or after the lower bound', () => {
    expect(matchTimestampRange(at('09:30:00'), ['09:00:00', null])).toBe(true)
    expect(matchTimestampRange(at('08:30:00'), ['09:00:00', null])).toBe(false)
  })

  it('to-only: includes rows at or before the upper bound', () => {
    expect(matchTimestampRange(at('14:00:00'), [null, '15:00:00'])).toBe(true)
    expect(matchTimestampRange(at('15:30:00'), [null, '15:00:00'])).toBe(false)
  })

  it('from + to: includes rows inside the closed interval', () => {
    expect(matchTimestampRange(at('10:30:00'), ['09:30', '11:00'])).toBe(true)
    expect(matchTimestampRange(at('09:00:00'), ['09:30', '11:00'])).toBe(false)
    expect(matchTimestampRange(at('11:30:00'), ['09:30', '11:00'])).toBe(false)
  })

  it('returns false for a null timestamp when a range is active', () => {
    expect(matchTimestampRange(null, ['09:00', null])).toBe(false)
  })
})
