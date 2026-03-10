'use client'

import { useCallback, useEffect, useState } from 'react'
import type {
  ListedVolGridResponse,
  ListedVolHistoryGridResponse,
  ListedVolProductClass
} from '../types'

type UseListedVolGridParams = {
  date?: string
  productClass: ListedVolProductClass
  includeHistory?: boolean
  lookback?: number
}

export function useListedVolGrid({
  date,
  productClass,
  includeHistory = false,
  lookback = 20
}: UseListedVolGridParams) {
  const [data, setData] = useState<ListedVolGridResponse | ListedVolHistoryGridResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        product_class: productClass
      })
      if (date) params.set('date', date)
      if (includeHistory) params.set('lookback', String(lookback))
      const endpoint = includeHistory ? '/api/listed-vol/history-grid' : '/api/listed-vol/grid'
      const response = await fetch(`${endpoint}?${params.toString()}`, {
        cache: 'no-store'
      })
      if (!response.ok) {
        throw new Error('Listed vol grid fetch failed')
      }
      setData(await response.json())
    } catch (fetchError: any) {
      setError(fetchError?.message || 'Unable to load listed vol grid')
    } finally {
      setLoading(false)
    }
  }, [date, includeHistory, lookback, productClass])

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
