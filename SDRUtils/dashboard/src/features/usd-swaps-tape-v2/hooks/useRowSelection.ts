import { useCallback, useState } from 'react'
import type { UsdSwapTapeRow } from '../types'

export interface UseRowSelectionReturn {
  selected: UsdSwapTapeRow[]
  onSelectionChange: (e: { value: UsdSwapTapeRow[] }) => void
  clear: () => void
  count: number
}

export function useRowSelection(): UseRowSelectionReturn {
  const [selected, setSelected] = useState<UsdSwapTapeRow[]>([])
  const onSelectionChange = useCallback(
    (e: { value: UsdSwapTapeRow[] }) => setSelected(e.value ?? []),
    [],
  )
  return {
    selected,
    onSelectionChange,
    clear: () => setSelected([]),
    count: selected.length,
  }
}
