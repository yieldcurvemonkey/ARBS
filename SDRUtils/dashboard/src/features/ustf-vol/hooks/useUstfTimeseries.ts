import { useCallback, useEffect, useState } from 'react'

import type { SeriesConfig, TimeRange, TimeseriesMode, TimeseriesResponse } from '../types'

export function useUstfTimeseries(params: {
  series1: SeriesConfig
  series2: SeriesConfig | null
  mode: TimeseriesMode
  range: TimeRange
}) {
  const [data, setData] = useState<TimeseriesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const { series1, series2, mode, range } = params

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const qs = new URLSearchParams()
      qs.set('series1_type', series1.type)
      if (series1.product) qs.set('series1_product', series1.product)
      qs.set('series1_expiry', series1.expiry)
      if (series1.tail) qs.set('series1_tail', series1.tail)

      if (series2) {
        qs.set('series2_type', series2.type)
        if (series2.product) qs.set('series2_product', series2.product)
        qs.set('series2_expiry', series2.expiry)
        if (series2.tail) qs.set('series2_tail', series2.tail)
      }

      qs.set('mode', mode)
      qs.set('range', range)

      const res = await fetch(`/api/ustf-vol/timeseries?${qs}`, { cache: 'no-store' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (e: any) {
      setError(e?.message ?? 'Unable to load timeseries')
    } finally {
      setLoading(false)
    }
  }, [
    series1.type, series1.product, series1.expiry, series1.tail,
    series2?.type, series2?.product, series2?.expiry, series2?.tail,
    mode, range,
  ])

  useEffect(() => { load() }, [load])

  return { data, loading, error, reload: load }
}
