// ABOUTME: Derives the contextual-action enablement matrix from the
// current leg selection + the visible tape rows. Pure `deriveSelectionContext`
// is unit-tested in node; `useSelectionContext` is a memoized wrapper.
import { useMemo } from 'react'
import type { UsdSwapTapeRow } from '../types'

export interface SelectionContext {
  canGroup: boolean
  canSplit: boolean
  canDetach: boolean
  canNote: boolean
  splitPackageId?: string
  detachPackageId?: string
}

interface PackageInfo {
  row: UsdSwapTapeRow
  legTradeIds: string[]
}

function indexPackages(rows: readonly UsdSwapTapeRow[]): {
  tradeToPackage: Map<string, string>
  packages: Map<string, PackageInfo>
} {
  const tradeToPackage = new Map<string, string>()
  const packages = new Map<string, PackageInfo>()
  for (const row of rows) {
    if (!row || !row.package_id) continue
    const legs = Array.isArray(row.legs_json) ? row.legs_json : []
    const legTradeIds: string[] = []
    for (const leg of legs) {
      const tid = leg?.trade_id
      if (typeof tid === 'string' && tid.length > 0) {
        legTradeIds.push(tid)
        tradeToPackage.set(tid, row.package_id)
      }
    }
    packages.set(row.package_id, { row, legTradeIds })
  }
  return { tradeToPackage, packages }
}

export function deriveSelectionContext(
  rows: readonly UsdSwapTapeRow[],
  selectedTradeIds: ReadonlySet<string>,
): SelectionContext {
  const empty: SelectionContext = {
    canGroup: false,
    canSplit: false,
    canDetach: false,
    canNote: false,
  }
  const count = selectedTradeIds.size
  if (count === 0) return empty

  const { tradeToPackage, packages } = indexPackages(rows)

  const perPackage = new Map<string, number>()
  for (const tid of selectedTradeIds) {
    const pkg = tradeToPackage.get(tid)
    if (!pkg) continue
    perPackage.set(pkg, (perPackage.get(pkg) ?? 0) + 1)
  }

  // Nothing resolved to a known package.
  if (perPackage.size === 0) return empty

  const canGroup = count >= 2

  if (perPackage.size === 1) {
    const pkgId = perPackage.keys().next().value as string
    const info = packages.get(pkgId)
    const totalLegs = info ? info.legTradeIds.length : 0
    const selInPkg = perPackage.get(pkgId) ?? 0
    const isAuto = !info?.row.override_type
    const canSplit = totalLegs >= 2 && selInPkg === totalLegs && isAuto
    const canDetach = selInPkg >= 1 && selInPkg < totalLegs
    return {
      canGroup,
      canSplit,
      canDetach,
      canNote: true,
      splitPackageId: canSplit ? pkgId : undefined,
      detachPackageId: canDetach ? pkgId : undefined,
    }
  }

  // Selection spans ≥2 packages: group only.
  return { canGroup, canSplit: false, canDetach: false, canNote: false }
}

export function useSelectionContext(
  rows: readonly UsdSwapTapeRow[],
  selectedTradeIds: ReadonlySet<string>,
): SelectionContext {
  return useMemo(
    () => deriveSelectionContext(rows, selectedTradeIds),
    [rows, selectedTradeIds],
  )
}
