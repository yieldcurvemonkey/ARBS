// ABOUTME: Pure helper for keeping the trader's visible row stable across
// poll-merge updates. When a poll inserts new rows above the anchor, the
// PrimeReact VirtualScroller naively shifts everything down by N*rowHeight
// while scrollTop stays constant — so a different row appears under the
// cursor. This helper computes the new scrollTop that re-anchors the same
// package to the same on-screen position.

interface RowLike {
  package_id?: string | null
}

export interface ComputeAnchorParams<R extends RowLike> {
  oldRows: R[]
  newRows: R[]
  oldScrollTop: number
  rowHeight: number
}

/**
 * @returns the new scrollTop to use after the rows array changed, or
 *   null if no adjustment is needed (user at top, no anchor available,
 *   anchor row no longer present in newRows, anchor index out of range,
 *   or position unchanged).
 */
export function computeAnchorAdjustedScrollTop<R extends RowLike>(
  p: ComputeAnchorParams<R>,
): number | null {
  const { oldRows, newRows, oldScrollTop, rowHeight } = p
  if (oldScrollTop <= 0) return null
  if (!oldRows.length || rowHeight <= 0) return null

  const oldAnchorIdx = Math.floor(oldScrollTop / rowHeight)
  if (oldAnchorIdx < 0 || oldAnchorIdx >= oldRows.length) return null

  const anchor = oldRows[oldAnchorIdx]
  const anchorId = anchor?.package_id
  if (!anchorId) return null

  const newAnchorIdx = newRows.findIndex((r) => r.package_id === anchorId)
  if (newAnchorIdx < 0) return null

  const idxDelta = newAnchorIdx - oldAnchorIdx
  if (idxDelta === 0) return null

  return oldScrollTop + idxDelta * rowHeight
}
