// Guards the functional-setState toggle path against regression: prior
// implementations read `expandedRows` from a closure and, under rapid
// successive clicks, could drop previously-expanded rows. `toggleOne` must
// always merge with the latest state.
import { describe, expect, it } from '@jest/globals'
import { toggleRowExpansionReducer } from '../useRowExpansion'

describe('toggleRowExpansionReducer', () => {
  it('expands a fresh package id', () => {
    expect(toggleRowExpansionReducer({}, 'pkg-a')).toEqual({ 'pkg-a': true })
  })

  it('collapses a previously expanded row', () => {
    expect(toggleRowExpansionReducer({ 'pkg-a': true }, 'pkg-a')).toEqual({})
  })

  it('preserves previously-expanded rows when toggling a new one', () => {
    expect(toggleRowExpansionReducer({ 'pkg-a': true }, 'pkg-b')).toEqual({
      'pkg-a': true,
      'pkg-b': true,
    })
  })

  it('only collapses the requested row, leaving siblings expanded', () => {
    const next = toggleRowExpansionReducer(
      { 'pkg-a': true, 'pkg-b': true, 'pkg-c': true },
      'pkg-b',
    )
    expect(next).toEqual({ 'pkg-a': true, 'pkg-c': true })
  })

  it('returns a fresh object (never mutates input)', () => {
    const input = { 'pkg-a': true }
    const next = toggleRowExpansionReducer(input, 'pkg-b')
    expect(next).not.toBe(input)
    expect(input).toEqual({ 'pkg-a': true })
  })
})
