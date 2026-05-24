// ABOUTME: SWR hook for /api/usd-swaps-tape-v2/volume-grid/cell.
import useSWR from 'swr'
import { TAPE_V2_API_BASE } from '../constants'
import type {
  VolumeCellRange, VolumeMetric,
  VolumeGridCellResponse,
} from '../types/volume-grid.types'
import type {
  BucketDef,
  ForwardSchemaId,
  PackageTypeGroupId,
  TenorSchemaId,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

export interface UseVolumeGridCellArgs {
  cell: { fwd: string; tenor?: string } | null
  metric: VolumeMetric
  range: VolumeCellRange
  forwardSchema: ForwardSchemaId
  tenorSchema: TenorSchemaId
  packageType: PackageTypeGroupId
  recentLimit?: number
  textFilter?: string
  customForwardBuckets?: BucketDef[]
  customTenorBuckets?: BucketDef[]
  structureType?: 'curve' | 'fly'
  structureTenors?: number[]
  structureTolerance?: number
  intradayDate?: string
  fetcher?: typeof fetch
}

export interface UseVolumeGridCellReturn {
  data: VolumeGridCellResponse | undefined
  error: Error | null
  isLoading: boolean
  refresh: () => Promise<VolumeGridCellResponse | undefined>
}

export function buildVolumeGridCellUrl(
  args: Pick<
    UseVolumeGridCellArgs,
    'cell' | 'metric' | 'range' | 'recentLimit' | 'forwardSchema' | 'tenorSchema' | 'packageType' | 'textFilter' | 'customForwardBuckets' | 'customTenorBuckets' | 'structureType' | 'structureTenors' | 'structureTolerance' | 'intradayDate'
  >,
): string | null {
  if (!args.cell) return null
  const q = new URLSearchParams({
    fwd: args.cell.fwd,
    metric: args.metric,
    range: args.range,
    forwardSchema: args.forwardSchema,
    tenorSchema: args.tenorSchema,
    packageType: args.packageType,
  })
  if (args.cell.tenor) q.set('tenor', args.cell.tenor)
  if (args.recentLimit != null) q.set('recentLimit', String(args.recentLimit))
  if (args.textFilter) q.set('textFilter', args.textFilter)
  if (args.customForwardBuckets) q.set('forwardBuckets', JSON.stringify(args.customForwardBuckets))
  if (args.customTenorBuckets) q.set('tenorBuckets', JSON.stringify(args.customTenorBuckets))
  if (args.structureType) q.set('structureType', args.structureType)
  if (args.structureTenors) q.set('structureTenors', JSON.stringify(args.structureTenors))
  if (args.structureTolerance != null) q.set('structureTolerance', String(args.structureTolerance))
  if (args.intradayDate) q.set('intradayDate', args.intradayDate)
  return `${TAPE_V2_API_BASE}/volume-grid/cell?${q}`
}

export function useVolumeGridCell(args: UseVolumeGridCellArgs): UseVolumeGridCellReturn {
  const fetcher = args.fetcher ?? (typeof fetch !== 'undefined' ? fetch : undefined)
  const url = buildVolumeGridCellUrl(args)
  const swr = useSWR<VolumeGridCellResponse, Error>(
    url,
    async (u: string) => {
      if (!fetcher) throw new Error('fetch is not available in this environment')
      const res = await fetcher(u)
      if (!res.ok) throw new Error(`cell fetch failed: ${res.status} ${res.statusText}`)
      return res.json() as Promise<VolumeGridCellResponse>
    },
    { refreshInterval: 30_000, revalidateOnFocus: true, dedupingInterval: 5_000 },
  )
  return {
    data: swr.data,
    error: swr.error ?? null,
    isLoading: swr.isLoading,
    refresh: () => swr.mutate(),
  }
}
