import { describe, expect, it } from '@jest/globals'
import { matchActionSelection } from '../ActionColumnFilter.helpers'

describe('matchActionSelection', () => {
  it('returns true for empty / null selection (no-op filter)', () => {
    expect(matchActionSelection('UNWIND', null)).toBe(true)
    expect(matchActionSelection('UNWIND', [])).toBe(true)
  })

  it('returns true when the row lifecycle is in the selection', () => {
    expect(matchActionSelection('UNWIND', ['NEW_RISK', 'UNWIND'])).toBe(true)
  })

  it('returns false when the row lifecycle is not in the selection', () => {
    expect(matchActionSelection('COMPRESSION', ['UNWIND', 'NEW_RISK'])).toBe(false)
  })

  it('returns false for null row lifecycle when a selection is active', () => {
    expect(matchActionSelection(null, ['UNWIND'])).toBe(false)
  })
})
