import {
  getSelectedForceableStraddleIds,
  getSelectedUndoableStraddleIds,
  type ManualStraddleSelectionRow
} from '../manualStraddles.utils'
import {
  SIMPLE_ADMIN_PASSWORD,
  isValidSimpleAdminPassword,
  normalizeSimpleAdminPassword
} from '../../../../lib/utils'

const ROWS: ManualStraddleSelectionRow[] = [
  {
    package_id: 'pkg-outright',
    package_type: 'OUTRIGHT',
    assumed_incomplete_straddle: false
  },
  {
    package_id: 'pkg-inferred',
    package_type: 'STRADDLE',
    assumed_incomplete_straddle: true
  },
  {
    package_id: 'pkg-real-straddle',
    package_type: 'STRADDLE',
    assumed_incomplete_straddle: false
  }
]

describe('manual straddle selection helpers', () => {
  test('returns selected outright rows that can be marked as inferred straddles', () => {
    expect(
      getSelectedForceableStraddleIds(ROWS, [
        'pkg-outright',
        'pkg-inferred',
        'pkg-outright'
      ])
    ).toEqual(['pkg-outright'])
  })

  test('returns only selected manual inferred straddles that can be undone', () => {
    expect(
      getSelectedUndoableStraddleIds(
        ROWS,
        ['pkg-inferred', 'pkg-real-straddle', 'pkg-outright'],
        new Set(['pkg-inferred', 'pkg-real-straddle'])
      )
    ).toEqual(['pkg-inferred'])
  })
})

describe('simple admin auth helpers', () => {
  test('normalizes non-empty password strings', () => {
    expect(normalizeSimpleAdminPassword(` ${SIMPLE_ADMIN_PASSWORD} `)).toBe(
      SIMPLE_ADMIN_PASSWORD
    )
    expect(normalizeSimpleAdminPassword('   ')).toBeNull()
    expect(normalizeSimpleAdminPassword(null)).toBeNull()
  })

  test('accepts only the configured admin password', () => {
    expect(isValidSimpleAdminPassword('admin')).toBe(true)
    expect(isValidSimpleAdminPassword(' admin ')).toBe(true)
    expect(isValidSimpleAdminPassword('ADMIN')).toBe(false)
    expect(isValidSimpleAdminPassword(undefined)).toBe(false)
  })
})
