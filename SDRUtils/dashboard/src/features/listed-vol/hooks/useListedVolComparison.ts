'use client'

import { useCallback, useEffect, useState } from 'react'
import type { ListedVolComparisonResponse, ListedVolProduct } from '../types'

export function useListedVolComparison(date: string | undefined, product: ListedVolProduct) {
  const [data, setData] = useState<ListedVolComparisonResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ product })
      if (date) params.set('date', date)
      const response = await fetch(`/api/listed-vol/comparison?${params.toString()}`, {
        cache: 'no-store'
      })
      if (!response.ok) {
        throw new Error('Listed vs swaption comparison fetch failed')
      }
      setData(await response.json())
    } catch (fetchError: any) {
      setError(fetchError?.message || 'Unable to load listed vs swaption comparison')
    } finally {
      setLoading(false)
    }
  }, [date, product])

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
