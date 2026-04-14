// Timeseries fetch wrapper around /api/usd-swaps-tape-v2/timeseries.
import { useCallback, useEffect, useState } from 'react'
import { TAPE_V2_API_BASE } from '../constants'
import type {
  TimeseriesGroupByKey,
  TimeseriesMetricKey,
  TimeseriesViewKey,
  TimeseriesPoint,
} from '../types'

export interface UseTimeseriesDataParams {
  groupBy: TimeseriesGroupByKey
  value: string | null
  metric: TimeseriesMetricKey
  view: TimeseriesViewKey
  range?: string
}

export interface UseTimeseriesDataReturn {
  points: TimeseriesPoint[]
  rows: any[]
  loading: boolean
  error: string | null
  refetch: () => void
}

export function useTimeseriesData(
  params: UseTimeseriesDataParams,
): UseTimeseriesDataReturn {
  const [points, setPoints] = useState<TimeseriesPoint[]>([])
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    if (!params.value) {
      setPoints([])
      setRows([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const q = new URLSearchParams({
        groupBy: params.groupBy,
        value: params.value,
        metric: params.metric,
        view: params.view,
        range: params.range ?? '1D',
      })
      const res = await fetch(`${TAPE_V2_API_BASE}/timeseries?${q}`)
      if (!res.ok) throw new Error(`timeseries fetch failed: ${res.statusText}`)
      const data = await res.json()
      setPoints(data.points ?? [])
      setRows(data.rows ?? [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'timeseries failed')
    } finally {
      setLoading(false)
    }
  }, [params.groupBy, params.value, params.metric, params.view, params.range])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  return { points, rows, loading, error, refetch: fetchData }
}
