'use client'

import { useCallback, useState } from 'react'
import type { CellDisplayConfig, CellDisplayField } from '../types'
import { DEFAULT_CELL_DISPLAY_CONFIG } from '../types'

const STORAGE_KEY = 'vol-grid-cell-display-config'

function loadConfig(): CellDisplayConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_CELL_DISPLAY_CONFIG
    const parsed = JSON.parse(raw) as CellDisplayConfig
    if (!Array.isArray(parsed.visibleFields) || parsed.visibleFields.length === 0) {
      return DEFAULT_CELL_DISPLAY_CONFIG
    }
    return parsed
  } catch {
    return DEFAULT_CELL_DISPLAY_CONFIG
  }
}

export function useCellDisplayConfig() {
  const [config, setConfig] = useState<CellDisplayConfig>(loadConfig)

  const toggleField = useCallback((field: CellDisplayField) => {
    setConfig((prev) => {
      const isVisible = prev.visibleFields.includes(field)
      if (isVisible && prev.visibleFields.length <= 1) return prev
      const next: CellDisplayConfig = {
        visibleFields: isVisible
          ? prev.visibleFields.filter((f) => f !== field)
          : [...prev.visibleFields, field]
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      return next
    })
  }, [])

  const resetToDefaults = useCallback(() => {
    setConfig(DEFAULT_CELL_DISPLAY_CONFIG)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(DEFAULT_CELL_DISPLAY_CONFIG))
  }, [])

  return { config, toggleField, resetToDefaults }
}
