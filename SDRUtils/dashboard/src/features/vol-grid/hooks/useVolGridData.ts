// ABOUTME: Hook for fetching vol grid surface data with session-aware polling.
// Automatically disables polling when market is closed (weekends, after hours).
'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  VolGridState,
  CalibrationObservation,
} from '../types'

const POLL_INTERVAL_MS = 5_000

type UseVolGridDataOptions = {
  presetName: string
  pollEnabled: boolean
  lengthScale?: number
  expiryWeight?: number
  tenorWeight?: number
}

type UseVolGridDataReturn = {
  gridState: VolGridState | null
  calibrationTrades: CalibrationObservation[]
  isLoading: boolean
  error: string | null
  lastFetchTime: number | null
  refetch: () => void
}

export function useVolGridData(options: UseVolGridDataOptions): UseVolGridDataReturn {
  const {
    presetName,
    pollEnabled,
    lengthScale,
    expiryWeight,
    tenorWeight,
  } = options

  const [gridState, setGridState] = useState<VolGridState | null>(null)
  const [calibrationTrades, setCalibrationTrades] = useState<CalibrationObservation[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastFetchTime, setLastFetchTime] = useState<number | null>(null)
  const fetchInFlight = useRef(false)

  const fetchSurface = useCallback(async () => {
    if (fetchInFlight.current) return
    fetchInFlight.current = true

    try {
      const params = new URLSearchParams({
        calibration_preset: presetName,
      })
      if (lengthScale !== undefined) params.set('length_scale', String(lengthScale))
      if (expiryWeight !== undefined) params.set('expiry_weight', String(expiryWeight))
      if (tenorWeight !== undefined) params.set('tenor_weight', String(tenorWeight))

      const [surfaceRes, tradesRes] = await Promise.all([
        fetch(`/api/vol-grid/surface?${params}`),
        fetch(`/api/vol-grid/calibration-trades?${params}&limit=50`),
      ])

      if (!surfaceRes.ok) {
        const errBody = await surfaceRes.json().catch(() => ({}))
        throw new Error(errBody.error || `Surface API returned ${surfaceRes.status}`)
      }

      const surfaceData: VolGridState = await surfaceRes.json()
      setGridState(surfaceData)

      if (tradesRes.ok) {
        const tradesData = await tradesRes.json()
        setCalibrationTrades(tradesData.trades || [])
      }

      setError(null)
      setLastFetchTime(Date.now())
    } catch (e: any) {
      setError(e.message || 'Failed to fetch vol grid data')
    } finally {
      setIsLoading(false)
      fetchInFlight.current = false
    }
  }, [presetName, lengthScale, expiryWeight, tenorWeight])

  // Initial fetch
  useEffect(() => {
    setIsLoading(true)
    fetchSurface()
  }, [fetchSurface])

  // Polling — only when user wants it AND market session says to poll
  const sessionShouldPoll = gridState?.session?.shouldPoll ?? true
  useEffect(() => {
    if (!pollEnabled || !sessionShouldPoll) return
    const interval = setInterval(fetchSurface, POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [pollEnabled, sessionShouldPoll, fetchSurface])

  return {
    gridState,
    calibrationTrades,
    isLoading,
    error,
    lastFetchTime,
    refetch: fetchSurface,
  }
}
