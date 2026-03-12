'use client'

import { useCallback, useEffect, useState } from 'react'

import type { ComparisonSnapshotResponse } from '../types'

export function useUstfComparisonSnapshot() {
  const [data, setData] = useState<ComparisonSnapshotResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      const response = await fetch('/api/ustf-vol/snapshot', { cache: 'no-store' })
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      setData(await response.json())
    } catch (loadError: any) {
      setError(loadError?.message ?? 'Unable to load snapshot')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return {
    data,
    loading,
    error,
    reload: load,
  }
}
