import { useCallback, useState } from 'react'
import type { UsdSwapTapeRow } from '../types'

export interface UseRowExpansionReturn {
  expandedRows: Record<string, boolean>
  onRowToggle: (e: { data: Record<string, boolean> }) => void
  toggleOne: (packageId: string) => void
  clear: () => void
  setExpanded: (rows: UsdSwapTapeRow[]) => void
}

// Exported so unit tests can exercise the functional-setState path without
// pulling in a full React renderer. Any call site that mutates expansion
// state should go through this helper so the "rapid clicks drop prior
// rows" regression stays fixed.
export function toggleRowExpansionReducer(
  prev: Record<string, boolean>,
  packageId: string,
): Record<string, boolean> {
  const next = { ...prev }
  if (next[packageId]) delete next[packageId]
  else next[packageId] = true
  return next
}

export function useRowExpansion(): UseRowExpansionReturn {
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({})

  const onRowToggle = useCallback(
    (e: { data: Record<string, boolean> }) => setExpandedRows(e.data ?? {}),
    [],
  )

  const toggleOne = useCallback((packageId: string) => {
    setExpandedRows((prev) => toggleRowExpansionReducer(prev, packageId))
  }, [])

  const clear = useCallback(() => setExpandedRows({}), [])

  const setExpanded = useCallback((rows: UsdSwapTapeRow[]) => {
    const next: Record<string, boolean> = {}
    for (const r of rows) next[r.package_id] = true
    setExpandedRows(next)
  }, [])

  return { expandedRows, onRowToggle, toggleOne, clear, setExpanded }
}
