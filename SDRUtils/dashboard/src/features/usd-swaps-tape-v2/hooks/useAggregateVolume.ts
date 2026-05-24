'use client'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { TAPE_V2_API_BASE } from '../constants'
import type { AggregateVolumeResponse } from '../types/aggregate-volume.types'
import type { VolumeMetric, VolumePeriod } from '../types/volume-grid.types'
import type { PackageTypeGroupId } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

export interface UseAggregateVolumeArgs {
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays?: number
  packageType: PackageTypeGroupId
  textFilter?: string
}

export interface UseAggregateVolumeReturn {
  data: AggregateVolumeResponse | undefined
  error: Error | null
  isLoading: boolean
  refresh: () => Promise<AggregateVolumeResponse | undefined>
}

const REFRESH_INTERVAL_MS = 30_000

function buildAggregateUrl(args: UseAggregateVolumeArgs): string {
  const q = new URLSearchParams({
    metric: args.metric,
    period: args.period,
    packageType: args.packageType,
  })
  if (args.lookbackDays != null) q.set('lookbackDays', String(args.lookbackDays))
  if (args.textFilter) q.set('textFilter', args.textFilter)
  return `${TAPE_V2_API_BASE}/volume-grid/aggregate?${q}`
}

export function useAggregateVolume(args: UseAggregateVolumeArgs): UseAggregateVolumeReturn {
  const url = buildAggregateUrl(args)
  const [data, setData] = useState<AggregateVolumeResponse | undefined>(undefined)
  const [error, setError] = useState<Error | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const urlRef = useRef(url)
  urlRef.current = url
  const generationRef = useRef(0)

  const runFetch = useCallback(async (): Promise<AggregateVolumeResponse | undefined> => {
    const target = urlRef.current
    const gen = ++generationRef.current
    setIsLoading(true)
    try {
      const res = await fetch(target)
      if (!res.ok) throw new Error(`aggregate-volume fetch failed: ${res.status} ${res.statusText}`)
      const payload = (await res.json()) as AggregateVolumeResponse
      if (generationRef.current !== gen) return undefined
      setData(payload)
      setError(null)
      return payload
    } catch (e) {
      if (generationRef.current !== gen) return undefined
      const err = e instanceof Error ? e : new Error(String(e))
      setError(err)
      return undefined
    } finally {
      if (generationRef.current === gen) setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void runFetch()
    let id: number | null = window.setInterval(() => { void runFetch() }, REFRESH_INTERVAL_MS)

    const onVisibilityChange = () => {
      if (document.hidden) {
        if (id != null) { window.clearInterval(id); id = null }
      } else {
        void runFetch()
        if (id == null) { id = window.setInterval(() => { void runFetch() }, REFRESH_INTERVAL_MS) }
      }
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      if (id != null) window.clearInterval(id)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [url, runFetch])

  return useMemo(() => ({ data, error, isLoading, refresh: runFetch }), [data, error, isLoading, runFetch])
}
