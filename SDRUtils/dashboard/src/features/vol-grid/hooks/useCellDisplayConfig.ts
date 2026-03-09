'use client'

import { useCallback, useEffect, useState } from 'react'
import type {
  CellDisplayConfig,
  CellDisplayField,
  LastTradedLevelField,
  VolGridChangeMetric,
  VolGridHeatmapMetric,
  VolGridHeatmapStrategy
} from '../types'
import { DEFAULT_CELL_DISPLAY_CONFIG } from '../types'

const STORAGE_KEY = 'vol-grid-cell-display-config'

function persistConfig(config: CellDisplayConfig) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
  } catch {
    /* no-op */
  }
}

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
    const parsedHeatmap = parsed.heatmap
    const strategy =
      parsedHeatmap?.strategy === 'absolute' ||
      parsedHeatmap?.strategy === 'delta' ||
      parsedHeatmap?.strategy === 'custom' ||
      parsedHeatmap?.strategy === 'none'
        ? parsedHeatmap.strategy
        : DEFAULT_CELL_DISPLAY_CONFIG.heatmap.strategy
    const metric =
      parsedHeatmap?.metric === 'vol' || parsedHeatmap?.metric === 'premium'
        ? parsedHeatmap.metric
        : DEFAULT_CELL_DISPLAY_CONFIG.heatmap.metric

    return {
      visibleFields: parsed.visibleFields,
      changeMetric:
        parsed.changeMetric === 'premium' || parsed.changeMetric === 'vol'
          ? parsed.changeMetric
          : DEFAULT_CELL_DISPLAY_CONFIG.changeMetric,
      lastTradedLevelFields: lastTradedLevelFields.length
        ? lastTradedLevelFields
        : DEFAULT_CELL_DISPLAY_CONFIG.lastTradedLevelFields,
      heatmap: {
        strategy,
        metric,
        inverted:
          typeof parsedHeatmap?.inverted === 'boolean'
            ? parsedHeatmap.inverted
            : DEFAULT_CELL_DISPLAY_CONFIG.heatmap.inverted,
        customTargets:
          typeof parsedHeatmap?.customTargets === 'string'
            ? parsedHeatmap.customTargets
            : DEFAULT_CELL_DISPLAY_CONFIG.heatmap.customTargets
      }
    }
  } catch {
    return DEFAULT_CELL_DISPLAY_CONFIG
  }
}

export function useCellDisplayConfig() {
  const [config, setConfig] = useState<CellDisplayConfig>(DEFAULT_CELL_DISPLAY_CONFIG)

  useEffect(() => {
    setConfig(loadConfig())
  }, [])

  const toggleField = useCallback((field: CellDisplayField) => {
    setConfig((prev) => {
      const isVisible = prev.visibleFields.includes(field)
      if (isVisible && prev.visibleFields.length <= 1) return prev
      const next: CellDisplayConfig = {
        visibleFields: isVisible
          ? prev.visibleFields.filter((f) => f !== field)
          : [...prev.visibleFields, field],
        changeMetric: prev.changeMetric,
        lastTradedLevelFields: prev.lastTradedLevelFields,
        heatmap: prev.heatmap
      }
      persistConfig(next)
      return next
    })
  }, [])

  const resetToDefaults = useCallback(() => {
    setConfig(DEFAULT_CELL_DISPLAY_CONFIG)
    persistConfig(DEFAULT_CELL_DISPLAY_CONFIG)
  }, [])

  const setChangeMetric = useCallback((changeMetric: VolGridChangeMetric) => {
    setConfig((prev) => {
      const next: CellDisplayConfig = { ...prev, changeMetric }
      persistConfig(next)
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
      persistConfig(next)
      return next
    })
  }, [])

  const setHeatmapStrategy = useCallback((strategy: VolGridHeatmapStrategy) => {
    setConfig((prev) => {
      const next: CellDisplayConfig = {
        ...prev,
        heatmap: {
          ...prev.heatmap,
          strategy
        }
      }
      persistConfig(next)
      return next
    })
  }, [])

  const setHeatmapMetric = useCallback((metric: VolGridHeatmapMetric) => {
    setConfig((prev) => {
      const next: CellDisplayConfig = {
        ...prev,
        heatmap: {
          ...prev.heatmap,
          metric
        }
      }
      persistConfig(next)
      return next
    })
  }, [])

  const toggleHeatmapInversion = useCallback(() => {
    setConfig((prev) => {
      const next: CellDisplayConfig = {
        ...prev,
        heatmap: {
          ...prev.heatmap,
          inverted: !prev.heatmap.inverted
        }
      }
      persistConfig(next)
      return next
    })
  }, [])

  const setHeatmapCustomTargets = useCallback((customTargets: string) => {
    setConfig((prev) => {
      const next: CellDisplayConfig = {
        ...prev,
        heatmap: {
          ...prev.heatmap,
          customTargets
        }
      }
      persistConfig(next)
      return next
    })
  }, [])

  return {
    config,
    toggleField,
    setChangeMetric,
    toggleLastTradedLevelField,
    setHeatmapStrategy,
    setHeatmapMetric,
    toggleHeatmapInversion,
    setHeatmapCustomTargets,
    resetToDefaults
  }
}
