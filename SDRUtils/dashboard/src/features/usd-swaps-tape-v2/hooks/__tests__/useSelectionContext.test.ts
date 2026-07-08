import { describe, expect, it } from '@jest/globals'
import type { UsdSwapTapeRow } from '../../types'
import { deriveSelectionContext } from '../useSelectionContext'

function pkg(
  id: string,
  tradeIds: string[],
  extra: Partial<UsdSwapTapeRow> = {},
): UsdSwapTapeRow {
  return {
    package_id: id,
    legs_json: tradeIds.map((t) => ({ trade_id: t })),
    ...extra,
  } as unknown as UsdSwapTapeRow
}

const ROWS: UsdSwapTapeRow[] = [
  pkg('PKG1', ['a', 'b', 'c']), // 3-leg auto package
  pkg('PKG2', ['d']), // lone outright
  pkg('PKG3', ['e', 'f'], { override_type: 'GROUP' }), // already a manual group
]

const ctx = (ids: string[]) => deriveSelectionContext(ROWS, new Set(ids))

describe('deriveSelectionContext', () => {
  it('empty selection → all false', () => {
    expect(ctx([])).toEqual({ canGroup: false, canSplit: false, canDetach: false, canNote: false })
  })

  it('single leg in a multi-leg package → detach + note, no group/split', () => {
    const c = ctx(['a'])
    expect(c).toMatchObject({ canGroup: false, canSplit: false, canDetach: true, canNote: true })
    expect(c.detachPackageId).toBe('PKG1')
    expect(c.splitPackageId).toBeUndefined()
  })

  it('all legs of a multi-leg auto package → group + split + note', () => {
    const c = ctx(['a', 'b', 'c'])
    expect(c).toMatchObject({ canGroup: true, canSplit: true, canDetach: false, canNote: true })
    expect(c.splitPackageId).toBe('PKG1')
  })

  it('two legs of a 3-leg package → group + detach + note (not split — not full)', () => {
    const c = ctx(['a', 'b'])
    expect(c).toMatchObject({ canGroup: true, canSplit: false, canDetach: true, canNote: true })
    expect(c.detachPackageId).toBe('PKG1')
  })

  it('trades spanning two packages → group only', () => {
    expect(ctx(['a', 'd'])).toMatchObject({
      canGroup: true, canSplit: false, canDetach: false, canNote: false,
    })
  })

  it('lone outright fully selected → note only (no split: single leg; no detach: nothing remains)', () => {
    expect(ctx(['d'])).toMatchObject({
      canGroup: false, canSplit: false, canDetach: false, canNote: true,
    })
  })

  it('fully-selected already-manual GROUP package → no split (not auto), note yes', () => {
    const c = ctx(['e', 'f'])
    expect(c.canSplit).toBe(false)
    expect(c.canGroup).toBe(true)
    expect(c.canNote).toBe(true)
  })

  it('ignores trade ids not present in any row', () => {
    expect(ctx(['zzz'])).toEqual({ canGroup: false, canSplit: false, canDetach: false, canNote: false })
  })
})
