// ABOUTME: SWR hook for /api/usd-swaps-tape-v2/volume-grid. Polls every
// 30s when expanded; pauses when collapsed.
import useSWR from 'swr'
import { TAPE_V2_API_BASE } from '../constants'
import type {
  VolumeGridResponse, VolumeMetric, VolumePeriod,
} from '../types/volume-grid.types'

export interface UseVolumeGridArgs {
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays?: number
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
  args: Pick<UseVolumeGridArgs, 'metric' | 'period' | 'lookbackDays'>,
): string {
  const q = new URLSearchParams({ metric: args.metric, period: args.period })
  if (args.lookbackDays != null) q.set('lookbackDays', String(args.lookbackDays))
  return `${TAPE_V2_API_BASE}/volume-grid?${q}`
}

export function useVolumeGrid(args: UseVolumeGridArgs): UseVolumeGridReturn {
  const fetcher = args.fetcher ?? (typeof fetch !== 'undefined' ? fetch : undefined)
  const url = args.collapsed ? null : buildVolumeGridUrl(args)
  const swr = useSWR<VolumeGridResponse, Error>(
    url,
    async (u: string) => {
      if (!fetcher) throw new Error('fetch is not available in this environment')
      const res = await fetcher(u)
      if (!res.ok) throw new Error(`volume-grid fetch failed: ${res.status} ${res.statusText}`)
      return res.json() as Promise<VolumeGridResponse>
    },
    {
      refreshInterval: args.collapsed ? 0 : DEFAULT_REFRESH_INTERVAL_MS,
      revalidateOnFocus: true,
      dedupingInterval: 5_000,
    },
  )
  return {
    data: swr.data,
    error: swr.error ?? null,
    isLoading: swr.isLoading,
    refresh: () => swr.mutate(),
  }
}
