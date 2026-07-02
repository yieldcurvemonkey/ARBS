import { describe, expect, it } from '@jest/globals'
import {
  DISPLAY_VIEW,
  PACKAGES_TABLE,
  LEGS_TABLE,
  EXCLUDED_VIEW_COLUMNS,
  __projectColumns,
} from '../usd-swaps-tape-v2'

describe('usd-swaps-tape-v2 constants', () => {
  it('exposes the v2 display view post-cutover', () => {
    expect(DISPLAY_VIEW).toBe('arbs_usd_swap_tape_display_v2')
  })

  it('exposes the v2 backing table names', () => {
    expect(PACKAGES_TABLE).toBe('arbs_usd_swap_tape_packages_v2')
    expect(LEGS_TABLE).toBe('arbs_usd_swap_tape_legs_v2')
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
