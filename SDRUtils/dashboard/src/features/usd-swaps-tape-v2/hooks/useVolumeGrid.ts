// ABOUTME: Hook for /api/usd-swaps-tape-v2/volume-grid. Polls every
// 30s when expanded; pauses when collapsed.
//
// Implemented as a plain useState/useEffect+setInterval pair rather
// than a useSWR hook because the volume-grid SWR entries were never
// committing to the IndexedDB-backed SWR cache provider on prod —
// the dock dashboard left the heatmap stuck on its skeleton even
// though the API was returning 200s. The other dock hooks
// (analytics-timeseries / rarity / extremes) all use array keys via
// the analyticsCacheKeys helper, which the cache provider stores
// fine; the URL-string key path was the only one that produced no
// cache entries. Bypassing SWR entirely sidesteps the integration
// without forcing a wider refactor of the cache key layer.
'use client'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { TAPE_V2_API_BASE } from '../constants'
import type {
  VolumeGridResponse, VolumeGridViewMode, VolumeMetric, VolumePeriod,
} from '../types/volume-grid.types'
import type {
  ForwardSchemaId,
  PackageTypeGroupId,
  TenorSchemaId,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

export interface UseVolumeGridArgs {
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays?: number
  forwardSchema: ForwardSchemaId
  tenorSchema: TenorSchemaId
  packageType: PackageTypeGroupId
  viewMode: VolumeGridViewMode
  collapsed: boolean
  /** Test seam — defaults to the package-wide `fetch`. */
  fetcher?: typeof fetch
}

export interface UseVolumeGridReturn {
  data: VolumeGridResponse | undefined
  error: Error | null
  isLoading: boolean
  refresh: () => Promise<VolumeGridResponse | undefined>
}

const DEFAULT_REFRESH_INTERVAL_MS = 30_000

export function buildVolumeGridUrl(
  args: Pick<
    UseVolumeGridArgs,
    'metric' | 'period' | 'lookbackDays' | 'forwardSchema' | 'tenorSchema' | 'packageType' | 'viewMode'
  >,
): string {
  const q = new URLSearchParams({
    metric: args.metric,
    period: args.period,
    forwardSchema: args.forwardSchema,
    tenorSchema: args.tenorSchema,
    packageType: args.packageType,
    viewMode: args.viewMode,
  })
  if (args.lookbackDays != null) q.set('lookbackDays', String(args.lookbackDays))
  return `${TAPE_V2_API_BASE}/volume-grid?${q}`
}

export function useVolumeGrid(args: UseVolumeGridArgs): UseVolumeGridReturn {
  const fetcher = args.fetcher ?? (typeof fetch !== 'undefined' ? fetch : undefined)
  const url = args.collapsed ? null : buildVolumeGridUrl(args)
  const [data, setData] = useState<VolumeGridResponse | undefined>(undefined)
  const [error, setError] = useState<Error | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(false)
  // Latest URL ref so the polling timer always reads the current
  // params even if it tick-fires across a state change.
  const urlRef = useRef(url)
  urlRef.current = url
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  // Increments on every successful fetch start so an in-flight stale
  // request whose params changed mid-flight does not commit its
  // payload over the newer one.
  const generationRef = useRef(0)

  const runFetch = useCallback(async (): Promise<VolumeGridResponse | undefined> => {
    const target = urlRef.current
    const f = fetcherRef.current
    if (!target || !f) return undefined
    const gen = ++generationRef.current
    setIsLoading(true)
    try {
      const res = await f(target)
      if (!res.ok) throw new Error(`volume-grid fetch failed: ${res.status} ${res.statusText}`)
      const payload = (await res.json()) as VolumeGridResponse
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

  // Fire when any of the URL-shaping params change; stop when the card
  // is collapsed.
  useEffect(() => {
    if (!url) return
    void runFetch()
    const id = window.setInterval(() => {
      void runFetch()
    }, DEFAULT_REFRESH_INTERVAL_MS)
    return () => {
      window.clearInterval(id)
    }
  }, [url, runFetch])

  return useMemo(
    () => ({
      data,
      error,
      isLoading,
      refresh: runFetch,
    }),
    [data, error, isLoading, runFetch],
  )
}
