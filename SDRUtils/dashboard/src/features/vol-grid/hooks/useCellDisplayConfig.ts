'use client'

import { useCallback, useState } from 'react'
import type {
  CellDisplayConfig,
  CellDisplayField,
  LastTradedLevelField,
  VolGridChangeMetric
} from '../types'
import { DEFAULT_CELL_DISPLAY_CONFIG } from '../types'

const STORAGE_KEY = 'vol-grid-cell-display-config'

function loadConfig(): CellDisplayConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_CELL_DISPLAY_CONFIG
    const parsed = JSON.parse(raw) as Partial<CellDisplayConfig>
    if (!Array.isArray(parsed.visibleFields) || parsed.visibleFields.length === 0) {
      return DEFAULT_CELL_DISPLAY_CONFIG
    }
    const lastTradedLevelFields = Array.isArray(parsed.lastTradedLevelFields)
      ? parsed.lastTradedLevelFields.filter(
          (field): field is LastTradedLevelField =>
            field === 'bpvol' || field === 'premiumBps'
        )
      : DEFAULT_CELL_DISPLAY_CONFIG.lastTradedLevelFields

    return {
      visibleFields: parsed.visibleFields,
      changeMetric:
        parsed.changeMetric === 'premium' || parsed.changeMetric === 'vol'
          ? parsed.changeMetric
          : DEFAULT_CELL_DISPLAY_CONFIG.changeMetric,
      lastTradedLevelFields: lastTradedLevelFields.length
        ? lastTradedLevelFields
        : DEFAULT_CELL_DISPLAY_CONFIG.lastTradedLevelFields
    }
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
          : [...prev.visibleFields, field],
        changeMetric: prev.changeMetric,
        lastTradedLevelFields: prev.lastTradedLevelFields
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      return next
    })
  }, [])

  const resetToDefaults = useCallback(() => {
    setConfig(DEFAULT_CELL_DISPLAY_CONFIG)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(DEFAULT_CELL_DISPLAY_CONFIG))
  }, [])

  const setChangeMetric = useCallback((changeMetric: VolGridChangeMetric) => {
    setConfig((prev) => {
      const next: CellDisplayConfig = { ...prev, changeMetric }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      return next
    })
  }, [])

  const toggleLastTradedLevelField = useCallback((field: LastTradedLevelField) => {
    setConfig((prev) => {
      const isEnabled = prev.lastTradedLevelFields.includes(field)
      if (isEnabled && prev.lastTradedLevelFields.length <= 1) {
        return prev
      }

      const next: CellDisplayConfig = {
        ...prev,
        lastTradedLevelFields: isEnabled
          ? prev.lastTradedLevelFields.filter((entry) => entry !== field)
          : [...prev.lastTradedLevelFields, field]
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      return next
    })
  }, [])

  return {
    config,
    toggleField,
    setChangeMetric,
    toggleLastTradedLevelField,
    resetToDefaults
  }
}
