'use client'

import { useEffect, useState } from 'react'
import type { CalibrationPresetKey, CellDetailResponse } from '../types'

export function useCellDetail(
  expiry: string | null,
  tenor: string | null,
  preset: CalibrationPresetKey,
  asOfDate?: string | null
) {
  const [data, setData] = useState<CellDetailResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!expiry || !tenor) {
      setData(null)
      setLoading(false)
      setError(null)
      return
    }

    const controller = new AbortController()
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const params = new URLSearchParams({
          calibration_preset: preset
        })
        if (asOfDate) {
          params.set('date', asOfDate)
        }
        const response = await fetch(
          `/api/vol-grid/cell-detail/${encodeURIComponent(expiry)}/${encodeURIComponent(tenor)}?${params.toString()}`,
          { signal: controller.signal }
        )
        if (!response.ok) {
          throw new Error('Cell detail fetch failed')
        }
        const payload = (await response.json()) as CellDetailResponse
        setData(payload)
      } catch (err: any) {
        if (controller.signal.aborted) return
        setError(err?.message || 'Unable to load cell detail')
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    load()
    return () => controller.abort()
  }, [expiry, tenor, preset, asOfDate])

  return { data, loading, error }
}
