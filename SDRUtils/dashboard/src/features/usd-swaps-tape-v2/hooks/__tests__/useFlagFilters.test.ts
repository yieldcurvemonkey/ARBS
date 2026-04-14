import { describe, expect, it } from '@jest/globals'
import { __internal } from '../useFlagFilters'

describe('useFlagFilters internals', () => {
  it('parseCsvSet handles empty and trims values', () => {
    expect(__internal.parseCsvSet(null).size).toBe(0)
    expect(__internal.parseCsvSet('')).toEqual(new Set())
    expect(__internal.parseCsvSet('a, b ,c')).toEqual(new Set(['a', 'b', 'c']))
  })

  it('parseCsvSet lowercases when requested', () => {
    expect(__internal.parseCsvSet('NEW_RISK,UNWIND', true)).toEqual(
      new Set(['new_risk', 'unwind']),
    )
  })

  it('csvFromSet returns null on empty', () => {
    expect(__internal.csvFromSet(new Set())).toBeNull()
  })

  it('csvFromSet sorts deterministically', () => {
    expect(__internal.csvFromSet(new Set(['c', 'a', 'b']))).toBe('a,b,c')
  })
})
