// ABOUTME: Debounced prefetch for the volume-grid cell modal. On cell
// hover (200ms debounce), pre-warms the SWR cache so a subsequent click
// renders the modal instantly. Pattern mirrors useAnalyticsPrefetch.
'use client'
import { useCallback, useEffect, useRef } from 'react'
import { useSWRConfig } from 'swr'
import { buildVolumeGridCellUrl } from './useVolumeGridCell'
import type { VolumeMetric } from '../types/volume-grid.types'
import type {
  ForwardSchemaId,
  PackageTypeGroupId,
  TenorSchemaId,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

const DEBOUNCE_MS = 200

export interface UseVolumeGridCellPrefetchArgs {
  metric: VolumeMetric
  forwardSchema: ForwardSchemaId
  tenorSchema: TenorSchemaId
  packageType: PackageTypeGroupId
}

export function useVolumeGridCellPrefetch(args: UseVolumeGridCellPrefetchArgs) {
  const { mutate, cache } = useSWRConfig()
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const onCellHover = useCallback(
    (cellId: { fwd: string; tenor: string }) => {
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => {
        const url = buildVolumeGridCellUrl({
          cell: cellId,
          metric: args.metric,
          range: '3M',
          forwardSchema: args.forwardSchema,
          tenorSchema: args.tenorSchema,
          packageType: args.packageType,
        })
        if (!url) return

        const cacheGet = (cache as { get: (k: string) => unknown }).get
        const existing = cacheGet ? cacheGet.call(cache, url) : undefined
        if (existing) return

        mutate(
          url,
          async () => {
            const res = await fetch(url)
            if (!res.ok) throw new Error(`prefetch ${res.status}`)
            return res.json()
          },
          { revalidate: false },
        ).catch(() => {})
      }, DEBOUNCE_MS)
    },
    [mutate, cache, args.metric, args.forwardSchema, args.tenorSchema, args.packageType],
  )

  const onCellLeave = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
  }, [])

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current)
    }
  }, [])

  return { onCellHover, onCellLeave }
}
