'use client'

import { useCallback, useEffect, useState } from 'react'
import type {
  ListedVolExpiry,
  ListedVolProduct,
  ListedVolRange,
  ListedVolTimeseriesResponse
} from '../types'

type UseListedVolTimeseriesParams = {
  date?: string
  product: ListedVolProduct | null
  expiry: ListedVolExpiry | null
  range: ListedVolRange
  includeSwaption: boolean
  includeRealized: boolean
  enabled?: boolean
}

export function useListedVolTimeseries({
  date,
  product,
  expiry,
  range,
  includeSwaption,
  includeRealized,
  enabled = true
}: UseListedVolTimeseriesParams) {
  const [data, setData] = useState<ListedVolTimeseriesResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!enabled || !product || !expiry) {
      setData(null)
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        range,
        include_swaption: String(includeSwaption),
        include_realized: String(includeRealized)
      })
      if (date) params.set('date', date)
      const response = await fetch(`/api/listed-vol/timeseries/${product}/${expiry}?${params.toString()}`, {
        cache: 'no-store'
      })
      if (!response.ok) {
        throw new Error('Listed vol timeseries fetch failed')
      }
      setData(await response.json())
    } catch (fetchError: any) {
      setError(fetchError?.message || 'Unable to load listed vol timeseries')
    } finally {
      setLoading(false)
    }
  }, [date, enabled, expiry, includeRealized, includeSwaption, product, range])

  useEffect(() => {
    load()
  }, [load])

  return {
    data,
    loading,
    error,
    reload: load
  }
}
