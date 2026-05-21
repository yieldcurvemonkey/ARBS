// ABOUTME: Hook for /api/usd-swaps-tape-v2/volume-grid/structure. Same
// polling pattern as useVolumeGrid — plain useState/setInterval, pauses
// when collapsed or tab hidden.
'use client'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { TAPE_V2_API_BASE } from '../constants'
import type {
  StructureDef, StructureType, StructureGridResponse,
} from '../types/structure-grid.types'
import type { VolumeMetric, VolumePeriod } from '../types/volume-grid.types'

export interface UseStructureGridArgs {
  structureType: StructureType
  structures: readonly StructureDef[]
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays?: number
  forwardSchema?: string
  collapsed: boolean
  textFilter?: string
  /** Test seam — defaults to the package-wide `fetch`. */
  fetcher?: typeof fetch
}

export interface UseStructureGridReturn {
  data: StructureGridResponse | undefined
  error: Error | null
  isLoading: boolean
  refresh: () => Promise<StructureGridResponse | undefined>
}

const DEFAULT_REFRESH_INTERVAL_MS = 30_000

export function buildStructureGridUrl(
  args: Pick<
    UseStructureGridArgs,
    'structureType' | 'structures' | 'metric' | 'period' | 'lookbackDays' | 'forwardSchema' | 'textFilter'
  >,
): string {
  const q = new URLSearchParams({
    structureType: args.structureType,
    structures: JSON.stringify(args.structures),
    metric: args.metric,
    period: args.period,
    forwardSchema: args.forwardSchema ?? 'structure_default',
  })
  if (args.lookbackDays != null) q.set('lookbackDays', String(args.lookbackDays))
  if (args.textFilter) q.set('textFilter', args.textFilter)
  return `${TAPE_V2_API_BASE}/volume-grid/structure?${q}`
}

export function useStructureGrid(args: UseStructureGridArgs): UseStructureGridReturn {
  const fetcher = args.fetcher ?? (typeof fetch !== 'undefined' ? fetch : undefined)
  const url = args.collapsed ? null : buildStructureGridUrl(args)
  const [data, setData] = useState<StructureGridResponse | undefined>(undefined)
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

  const runFetch = useCallback(async (): Promise<StructureGridResponse | undefined> => {
    const target = urlRef.current
    const f = fetcherRef.current
    if (!target || !f) return undefined
    const gen = ++generationRef.current
    setIsLoading(true)
    try {
      const res = await f(target)
      if (!res.ok) throw new Error(`structure-grid fetch failed: ${res.status} ${res.statusText}`)
      const payload = (await res.json()) as StructureGridResponse
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
    if (!url) return
    void runFetch()
    let id: number | null = window.setInterval(() => {
      void runFetch()
    }, DEFAULT_REFRESH_INTERVAL_MS)

    const onVisibilityChange = () => {
      if (document.hidden) {
        if (id != null) {
          window.clearInterval(id)
          id = null
        }
      } else {
        void runFetch()
        if (id == null) {
          id = window.setInterval(() => {
            void runFetch()
          }, DEFAULT_REFRESH_INTERVAL_MS)
        }
      }
    }
    document.addEventListener('visibilitychange', onVisibilityChange)

    return () => {
      if (id != null) window.clearInterval(id)
      document.removeEventListener('visibilitychange', onVisibilityChange)
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
