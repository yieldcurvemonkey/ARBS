// ABOUTME: Leg-level tape selection. Internal state is package-keyed
// (Map<packageId, Set<tradeId>>) so `selectedByPackage` is exact; the
// flattened `selectedTradeIds` Set drives the action-bar enablement.
import { useCallback, useMemo, useState } from 'react'

export interface UseTradeSelectionReturn {
  selectedTradeIds: Set<string>
  selectedByPackage: Map<string, string[]>
  toggleTrade: (tradeId: string, packageId: string) => void
  togglePackage: (packageId: string, legTradeIds: string[]) => void
  clear: () => void
  count: number
}

export function useTradeSelection(): UseTradeSelectionReturn {
  const [byPackage, setByPackage] = useState<Map<string, Set<string>>>(() => new Map())

  const toggleTrade = useCallback((tradeId: string, packageId: string) => {
    setByPackage((prev) => {
      const next = new Map(prev)
      const set = new Set(next.get(packageId) ?? [])
      if (set.has(tradeId)) set.delete(tradeId)
      else set.add(tradeId)
      if (set.size === 0) next.delete(packageId)
      else next.set(packageId, set)
      return next
    })
  }, [])

  const togglePackage = useCallback((packageId: string, legTradeIds: string[]) => {
    setByPackage((prev) => {
      const next = new Map(prev)
      const current = next.get(packageId)
      const allSelected =
        legTradeIds.length > 0 &&
        current != null &&
        legTradeIds.every((id) => current.has(id))
      if (allSelected) next.delete(packageId)
      else next.set(packageId, new Set(legTradeIds))
      return next
    })
  }, [])

  const clear = useCallback(() => setByPackage(new Map()), [])

  const selectedByPackage = useMemo(() => {
    const m = new Map<string, string[]>()
    for (const [pkg, set] of byPackage) m.set(pkg, Array.from(set))
    return m
  }, [byPackage])

  const selectedTradeIds = useMemo(() => {
    const s = new Set<string>()
    for (const set of byPackage.values()) for (const id of set) s.add(id)
    return s
  }, [byPackage])

  return {
    selectedTradeIds,
    selectedByPackage,
    toggleTrade,
    togglePackage,
    clear,
    count: selectedTradeIds.size,
  }
}
