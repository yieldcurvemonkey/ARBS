'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  ListedOptionRange,
  ListedOptionSeriesConfig,
  ListedOptionTimeseriesMultiResponse,
} from '../types'
import {
  getTimeseriesHistoricalWindow,
  mergeTimeseriesCollection,
} from '../utils'

type Params = {
  series: ListedOptionSeriesConfig[]
  range: ListedOptionRange
  startDate?: string
  endDate?: string
  periodBusinessDays: number
}

export function useListedOptionTimeseriesMulti(params: Params) {
  const [data, setData] = useState<ListedOptionTimeseriesMultiResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingHistorical, setLoadingHistorical] = useState(false)
  const [hasMoreHistorical, setHasMoreHistorical] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestVersionRef = useRef(0)
  const historicalRequestInFlightRef = useRef(false)

  const serializedSeries = JSON.stringify(params.series)

  const fetchWindow = useCallback(
    async (windowStartDate?: string, windowEndDate?: string) => {
      const response = await fetch('/api/listed-option-oi-volume/timeseries-multi', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          series: JSON.parse(serializedSeries),
          range: params.range,
          startDate: windowStartDate,
          endDate: windowEndDate,
          periodBusinessDays: params.periodBusinessDays,
        }),
      })

      const payload = await response.json()
      if (!response.ok) {
        throw new Error(payload?.error ?? `HTTP ${response.status}`)
      }

      return payload as ListedOptionTimeseriesMultiResponse
    },
    [params.periodBusinessDays, params.range, serializedSeries]
  )

  const load = useCallback(async () => {
    const requestVersion = ++requestVersionRef.current
    historicalRequestInFlightRef.current = false
    setLoadingHistorical(false)

    if (!params.series.length) {
      setData({
        startDate: null,
        endDate: null,
        asOfDate: null,
        series: [],
        warnings: [],
      })
      setError(null)
      setHasMoreHistorical(false)
      setLoading(false)
      return
    }

    setLoading(true)
    setError(null)
    setHasMoreHistorical(true)

    try {
      const payload = await fetchWindow(params.startDate, params.endDate)
      if (requestVersionRef.current !== requestVersion) return
      setData(payload)
      setHasMoreHistorical(Boolean(payload.startDate))
    } catch (loadError: any) {
      if (requestVersionRef.current !== requestVersion) return
      setError(loadError?.message ?? 'Unable to load timeseries')
      setHasMoreHistorical(false)
    } finally {
      if (requestVersionRef.current === requestVersion) {
        setLoading(false)
      }
    }
  }, [fetchWindow, params.endDate, params.series.length, params.startDate])

  const loadHistorical = useCallback(async () => {
    if (
      !params.series.length ||
      !data?.startDate ||
      loading ||
      historicalRequestInFlightRef.current ||
      !hasMoreHistorical
    ) {
      return false
    }

    const window = getTimeseriesHistoricalWindow({
      currentStartDate: data.startDate,
      range: params.range,
      initialStartDate: params.startDate,
      initialEndDate: params.endDate,
    })

    historicalRequestInFlightRef.current = true
    const requestVersion = requestVersionRef.current
    const currentStartDate = data.startDate
    setLoadingHistorical(true)

    try {
      const payload = await fetchWindow(window.startDate, window.endDate)
      if (requestVersionRef.current !== requestVersion) {
        return false
      }

      const hasEarlierPoints =
        typeof payload.startDate === 'string' && payload.startDate < currentStartDate

      if (hasEarlierPoints) {
        setData((current) => (current ? mergeTimeseriesCollection(current, payload) : current))
      } else {
        setHasMoreHistorical(false)
      }

      return hasEarlierPoints
    } catch (loadError: any) {
      if (requestVersionRef.current !== requestVersion) {
        return false
      }

      setError(loadError?.message ?? 'Unable to load timeseries history')
      return false
    } finally {
      if (requestVersionRef.current === requestVersion) {
        historicalRequestInFlightRef.current = false
        setLoadingHistorical(false)
      }
    }
  }, [
    data,
    fetchWindow,
    hasMoreHistorical,
    loading,
    params.endDate,
    params.range,
    params.series.length,
    params.startDate,
  ])

  useEffect(() => {
    load()
  }, [load])

  return {
    data,
    loading,
    loadingHistorical,
    hasMoreHistorical,
    error,
    reload: load,
    loadHistorical,
  }
}
