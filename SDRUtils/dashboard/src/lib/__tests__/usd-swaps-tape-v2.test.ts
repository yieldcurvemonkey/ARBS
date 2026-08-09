import { describe, expect, it } from '@jest/globals'
import { TAPE_DISPLAY, TAPE_LEGS, TAPE_PACKAGES } from '@/lib/tape-tables'
import {
  DISPLAY_VIEW,
  PACKAGES_TABLE,
  LEGS_TABLE,
  EXCLUDED_VIEW_COLUMNS,
  __projectColumns,
} from '../usd-swaps-tape-v2'

describe('usd-swaps-tape-v2 constants', () => {
  it('exposes the current-generation display view', () => {
    expect(DISPLAY_VIEW).toBe(TAPE_DISPLAY)
  })

  it('exposes the current-generation backing table names', () => {
    expect(PACKAGES_TABLE).toBe(TAPE_PACKAGES)
    expect(LEGS_TABLE).toBe(TAPE_LEGS)
  })
})

describe('display view projection', () => {
  it('includes unknown new columns by default (audit C1 prevention)', () => {
    const viewCols = ['package_id', 'brand_new_column', 'confidence_score']
    const projected = __projectColumns(viewCols)
    expect(projected).toContain('d.brand_new_column')
    expect(projected).toContain('d.package_id')
  })

  it('drops only explicitly excluded columns', () => {
    const projected = __projectColumns(['package_id', 'confidence_score'])
    expect(projected).not.toContain('d.confidence_score')
    expect(EXCLUDED_VIEW_COLUMNS.has('confidence_score')).toBe(true)
  })
})
