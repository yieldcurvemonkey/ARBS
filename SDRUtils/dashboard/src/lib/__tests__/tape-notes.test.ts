import { describe, expect, it } from '@jest/globals'
import { isValidNoteTargetType, normalizeAuthor, normalizeNoteBody } from '../tape-notes'

describe('tape-notes helpers', () => {
  it('validates target type', () => {
    expect(isValidNoteTargetType('TRADE')).toBe(true)
    expect(isValidNoteTargetType('PACKAGE')).toBe(true)
    expect(isValidNoteTargetType('trade')).toBe(false)
    expect(isValidNoteTargetType(42)).toBe(false)
  })
  it('normalizes body + author (trim, blank->null)', () => {
    expect(normalizeNoteBody('  hi  ')).toBe('hi')
    expect(normalizeNoteBody('   ')).toBeNull()
    expect(normalizeAuthor(123)).toBeNull()
    expect(normalizeAuthor(' me ')).toBe('me')
  })
})
