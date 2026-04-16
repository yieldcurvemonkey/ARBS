// ABOUTME: Pure-logic match helper for the ActionColumnFilter.
import type { LifecycleType } from '../../types'

export function matchActionSelection(
  rowLifecycle: LifecycleType | string | null | undefined,
  selection: LifecycleType[] | null | undefined,
): boolean {
  if (!selection || selection.length === 0) return true
  if (!rowLifecycle) return false
  return selection.includes(rowLifecycle as LifecycleType)
}
