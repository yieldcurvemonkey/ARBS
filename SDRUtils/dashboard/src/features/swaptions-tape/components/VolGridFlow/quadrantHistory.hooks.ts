// ABOUTME: React hook for fetching quadrant history data with simple SWR caching.

import { useEffect, useMemo, useRef, useState } from 'react'
import type { QuadrantConfig, QuadrantHistoryResponse, HistoryLookback } from './quadrantHistory.types'
import { lookbackToDateRange } from './quadrantHistory.utils'

type QuadrantHistoryParams = {
  lookback: HistoryLookback
  platform: 'combined' | 'idb' | 'custy'
  quadrantConfig: QuadrantConfig
  referenceDate?: string
  excludeLargeCustyNotional?: boolean
}

type QuadrantHistoryState = {
  data: QuadrantHistoryResponse | null
  isLoading: boolean
  error: Error | null
}

type CacheEntry = {
  data: QuadrantHistoryResponse
  timestamp: number
}

const historyCache = new Map<string, CacheEntry>()

export function useQuadrantHistory(params: QuadrantHistoryParams): QuadrantHistoryState {
  const { lookback, platform, quadrantConfig, referenceDate, excludeLargeCustyNotional } = params
  const [data, setData] = useState<QuadrantHistoryResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const inFlightRef = useRef<string | null>(null)

  const range = useMemo(
    () => lookbackToDateRange(lookback, referenceDate),
    [lookback, referenceDate],
  )

  const cacheKey = useMemo(
    () =>
      JSON.stringify({
        start: range.start,
        end: range.end,
        expiryBoundary: quadrantConfig.expiryBoundaryYears,
        tenorBoundary: quadrantConfig.tenorBoundaryYears,
        tolerance: quadrantConfig.boundaryToleranceYears,
        platform,
        excludeLargeCustyNotional: !!excludeLargeCustyNotional,
      }),
    [excludeLargeCustyNotional, platform, quadrantConfig, range.end, range.start],
  )

  useEffect(() => {
    if (!range.start || !range.end) return

    const cached = historyCache.get(cacheKey)
    if (cached) {
      setData(cached.data)
    }

    if (inFlightRef.current === cacheKey) return
    inFlightRef.current = cacheKey

    const controller = new AbortController()
    const fetchHistory = async () => {
      setIsLoading(!cached)
      setError(null)
      try {
        const params = new URLSearchParams()
        params.set('start', range.start)
        params.set('end', range.end)
        params.set('expiry_boundary', String(quadrantConfig.expiryBoundaryYears))
        params.set('tenor_boundary', String(quadrantConfig.tenorBoundaryYears))
        params.set('tolerance', String(quadrantConfig.boundaryToleranceYears))
        params.set('platform', platform)
        if (excludeLargeCustyNotional) {
          params.set('excludeLargeCustyNotional', 'true')
        }

        const res = await fetch(`/api/swaptions-tape/quadrant-history?${params.toString()}`,
          { signal: controller.signal },
        )
        if (!res.ok) {
          const text = await res.text()
          throw new Error(text || 'Failed to load quadrant history')
        }
        const payload = (await res.json()) as QuadrantHistoryResponse
        historyCache.set(cacheKey, { data: payload, timestamp: Date.now() })
        setData(payload)
      } catch (err) {
        if ((err as any)?.name === 'AbortError') return
        setError(err instanceof Error ? err : new Error('Failed to load quadrant history'))
      } finally {
        setIsLoading(false)
        if (inFlightRef.current === cacheKey) {
          inFlightRef.current = null
        }
      }
    }

    fetchHistory()

    return () => {
      controller.abort()
      if (inFlightRef.current === cacheKey) {
        inFlightRef.current = null
      }
    }
  }, [cacheKey])

  return { data, isLoading, error }
}
