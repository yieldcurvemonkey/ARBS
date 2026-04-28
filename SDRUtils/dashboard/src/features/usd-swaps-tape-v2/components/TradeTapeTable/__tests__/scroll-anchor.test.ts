import { describe, expect, it } from '@jest/globals'
import { computeAnchorAdjustedScrollTop } from '../scroll-anchor'

describe('computeAnchorAdjustedScrollTop', () => {
  // Helper: produce N rows with package ids "p0" … "pN-1" (or any prefix).
  const ids = (n: number, prefix = 'p') =>
    Array.from({ length: n }, (_, i) => ({ package_id: `${prefix}${i}` }))

  it('returns null when scrollTop === 0 (user at top — no anchor needed)', () => {
    const oldRows = ids(50)
    const newRows = [...ids(3, 'NEW'), ...oldRows]
    expect(
      computeAnchorAdjustedScrollTop({
        oldRows,
        newRows,
        oldScrollTop: 0,
        rowHeight: 40,
      }),
    ).toBeNull()
  })

  it('returns null when oldRows is empty (no anchor available)', () => {
    expect(
      computeAnchorAdjustedScrollTop({
        oldRows: [],
        newRows: [{ package_id: 'a' }, { package_id: 'b' }],
        oldScrollTop: 100,
        rowHeight: 40,
      }),
    ).toBeNull()
  })

  it('returns null when the anchor row is no longer present in newRows (filtered out)', () => {
    const oldRows = [{ package_id: 'a' }, { package_id: 'b' }, { package_id: 'c' }]
    // Anchor at scrollTop=80, rowHeight=40 ⇒ idx 2 ⇒ "c". Remove "c" from newRows.
    const newRows = [{ package_id: 'a' }, { package_id: 'b' }]
    expect(
      computeAnchorAdjustedScrollTop({
        oldRows,
        newRows,
        oldScrollTop: 80,
        rowHeight: 40,
      }),
    ).toBeNull()
  })

  it('bumps scrollTop by rowHeight × N when N rows landed above the anchor', () => {
    // Old: anchor at idx 5 ⇒ oldScrollTop = 5*40 = 200.
    const oldRows = ids(20)
    // New: 3 fresh rows landed above; anchor "p5" is now at idx 8.
    const newRows = [
      { package_id: 'NEW0' },
      { package_id: 'NEW1' },
      { package_id: 'NEW2' },
      ...oldRows,
    ]
    const next = computeAnchorAdjustedScrollTop({
      oldRows,
      newRows,
      oldScrollTop: 200,
      rowHeight: 40,
    })
    // Anchor moved from idx 5 → idx 8. Bump = 3 * 40 = 120. 200 + 120 = 320.
    expect(next).toBe(320)
  })

  it('returns null when the anchor index is unchanged (no shift)', () => {
    const rows = ids(20)
    expect(
      computeAnchorAdjustedScrollTop({
        oldRows: rows,
        newRows: rows,
        oldScrollTop: 200,
        rowHeight: 40,
      }),
    ).toBeNull()
  })

  it('returns null for invalid rowHeight (defensive)', () => {
    expect(
      computeAnchorAdjustedScrollTop({
        oldRows: [{ package_id: 'a' }],
        newRows: [{ package_id: 'a' }],
        oldScrollTop: 100,
        rowHeight: 0,
      }),
    ).toBeNull()
  })

  it('returns null when the computed anchor index is out of range', () => {
    // scrollTop=400 but only 5 rows ⇒ idx 10 ⇒ undefined ⇒ no anchor.
    expect(
      computeAnchorAdjustedScrollTop({
        oldRows: ids(5),
        newRows: ids(5),
        oldScrollTop: 400,
        rowHeight: 40,
      }),
    ).toBeNull()
  })

  it('handles a row whose package_id is null/undefined (skip anchor)', () => {
    const oldRows = [
      { package_id: 'a' },
      { package_id: null as unknown as string }, // simulate orphaned row
      { package_id: 'c' },
    ]
    expect(
      computeAnchorAdjustedScrollTop({
        oldRows,
        newRows: oldRows,
        oldScrollTop: 40, // anchor idx 1 = null id
        rowHeight: 40,
      }),
    ).toBeNull()
  })
})
