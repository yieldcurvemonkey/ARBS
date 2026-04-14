import { useCallback, useState } from 'react'
import type { UsdSwapTapeRow } from '../types'

export interface UseRowExpansionReturn {
  expandedRows: Record<string, boolean>
  onRowToggle: (e: { data: Record<string, boolean> }) => void
  toggleOne: (packageId: string) => void
  clear: () => void
  setExpanded: (rows: UsdSwapTapeRow[]) => void
}

export function useRowExpansion(): UseRowExpansionReturn {
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({})

  const onRowToggle = useCallback(
    (e: { data: Record<string, boolean> }) => setExpandedRows(e.data ?? {}),
    [],
  )

  const toggleOne = useCallback((packageId: string) => {
    setExpandedRows((prev) => {
      const next = { ...prev }
      if (next[packageId]) delete next[packageId]
      else next[packageId] = true
      return next
    })
  }, [])

  const clear = useCallback(() => setExpandedRows({}), [])

  const setExpanded = useCallback((rows: UsdSwapTapeRow[]) => {
    const next: Record<string, boolean> = {}
    for (const r of rows) next[r.package_id] = true
    setExpandedRows(next)
  }, [])

  return { expandedRows, onRowToggle, toggleOne, clear, setExpanded }
}
