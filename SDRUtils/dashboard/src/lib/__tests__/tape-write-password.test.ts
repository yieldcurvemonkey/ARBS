import { afterEach, beforeEach, describe, expect, it } from '@jest/globals'
import { isValidTapeWritePassword, TAPE_WRITE_AUTH_ERROR } from '../utils'

describe('isValidTapeWritePassword', () => {
  const ORIGINAL = process.env.TAPE_OVERRIDE_PASSWORD
  beforeEach(() => {
    process.env.TAPE_OVERRIDE_PASSWORD = 'letmein'
  })
  afterEach(() => {
    if (ORIGINAL === undefined) delete process.env.TAPE_OVERRIDE_PASSWORD
    else process.env.TAPE_OVERRIDE_PASSWORD = ORIGINAL
  })

  it('exposes the fixed error message', () => {
    expect(TAPE_WRITE_AUTH_ERROR).toBe('Invalid override password.')
  })
  it('accepts the exact password (trimmed)', () => {
    expect(isValidTapeWritePassword('letmein')).toBe(true)
    expect(isValidTapeWritePassword('  letmein  ')).toBe(true)
  })
  it('rejects a mismatch', () => {
    expect(isValidTapeWritePassword('nope')).toBe(false)
  })
  it('rejects non-strings', () => {
    expect(isValidTapeWritePassword(undefined)).toBe(false)
    expect(isValidTapeWritePassword(null)).toBe(false)
    expect(isValidTapeWritePassword(123)).toBe(false)
  })
  it('returns false when the env var is unset', () => {
    delete process.env.TAPE_OVERRIDE_PASSWORD
    expect(isValidTapeWritePassword('letmein')).toBe(false)
  })
  it('returns false when the env var is empty/whitespace', () => {
    process.env.TAPE_OVERRIDE_PASSWORD = '   '
    expect(isValidTapeWritePassword('   ')).toBe(false)
  })
})
