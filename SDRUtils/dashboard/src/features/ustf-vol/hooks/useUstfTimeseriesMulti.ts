'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import type { SeriesConfig, TimeRange, UstfTimeseriesMultiResponse } from '../types'
import {
  getTimeseriesHistoricalWindow,
  mergeTimeseriesCollection,
} from '../utils'

type Params = {
  series: SeriesConfig[]
  range: TimeRange
  startDate?: string
  endDate?: string
}

export function useUstfTimeseriesMulti(params: Params) {
  const [data, setData] = useState<UstfTimeseriesMultiResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingHistorical, setLoadingHistorical] = useState(false)
  const [hasMoreHistorical, setHasMoreHistorical] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const seriesCount = params.series.length
  const requestVersionRef = useRef(0)
  const historicalRequestInFlightRef = useRef(false)

  const serializedSeries = JSON.stringify(
    params.series.map((series) => ({
      type: series.type,
      product: series.product ?? null,
      expiry: series.expiry,
      tail: series.tail ?? null,
      volMetric: series.volMetric ?? null,
    }))
  )

  const fetchWindow = useCallback(
    async (windowStartDate?: string, windowEndDate?: string) => {
      const response = await fetch('/api/ustf-vol/timeseries-multi', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          series: JSON.parse(serializedSeries),
          range: params.range,
          startDate: windowStartDate,
          endDate: windowEndDate,
        }),
      })

      const payload = await response.json()
      if (!response.ok) {
        throw new Error(payload?.error ?? `HTTP ${response.status}`)
      }

      return payload as UstfTimeseriesMultiResponse
    },
    [params.range, serializedSeries]
  )

  const load = useCallback(async () => {
    const requestVersion = ++requestVersionRef.current
    historicalRequestInFlightRef.current = false
    setLoadingHistorical(false)

    if (seriesCount === 0) {
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
      if (requestVersionRef.current !== requestVersion) {
        return
      }

      setData(payload)
      setHasMoreHistorical(Boolean(payload.startDate))
    } catch (loadError: any) {
      if (requestVersionRef.current !== requestVersion) {
        return
      }

      setError(loadError?.message ?? 'Unable to load timeseries')
      setHasMoreHistorical(false)
    } finally {
      if (requestVersionRef.current === requestVersion) {
        setLoading(false)
      }
    }
  }, [fetchWindow, params.endDate, params.startDate, seriesCount])

  const loadHistorical = useCallback(async () => {
    if (
      seriesCount === 0 ||
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

    if (!window) {
      setHasMoreHistorical(false)
      return false
    }

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
    params.startDate,
    seriesCount,
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
