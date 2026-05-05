// ABOUTME: Response shapes for /volume-grid and /volume-grid/cell.
// Imported by the route handlers and the SWR hooks.

import type {
  ForwardSchemaId,
  PackageTypeGroupId,
  TenorSchemaId,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

export type VolumeMetric = 'notional' | 'dv01'
export type VolumePeriod = 'today' | '1h' | '24h' | '1w'
export type VolumeCellRange = '1M' | '3M' | '6M' | '1Y'

export interface VolumeGridBaseline {
  p25: number
  p50: number
  p75: number
  min: number
  max: number
  n: number
}

export interface VolumeGridCell {
  fwd: string
  tenor: string
  current: number
  tradeCount: number
  baseline: VolumeGridBaseline
  /** 0..100 rank of `current` within the prior-window distribution; null when `n=0`. */
  percentile: number | null
}

export interface VolumeGridTotalEntry {
  current: number
  percentile: number | null
}

export interface VolumeGridSchemaAxis {
  id: string
  label: string
  buckets: ReadonlyArray<{ id: string; label: string }>
}

export interface VolumeGridResponse {
  asOf: string
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  forwardSchema: ForwardSchemaId
  tenorSchema: TenorSchemaId
  packageType: PackageTypeGroupId
  /** Echo of the resolved axes — clients use this to render headers without
   *  re-deriving them. Especially useful for IMM where buckets rotate. */
  axes: { forward: VolumeGridSchemaAxis; tenor: VolumeGridSchemaAxis }
  cells: VolumeGridCell[]
  totals: {
    rowTotals: Record<string, VolumeGridTotalEntry>
    colTotals: Record<string, VolumeGridTotalEntry>
    grand: VolumeGridTotalEntry
  }
}

export interface VolumeGridCellTimeseriesPoint {
  day: string
  notional: number
  dv01: number
  tradeCount: number
  idbCount: number
  custyCount: number
}

export interface VolumeGridCellRecentTrade {
  package_id: string
  execution_start: string
  tape_label: string | null
  package_type: string | null
  weighted_fixed_rate: number | null
  total_risk: number | null
  total_notional: number | null
  venue: string | null
  is_block_any: boolean | null
}

export interface VolumeGridCellResponse {
  fwd: string
  tenor: string
  metric: VolumeMetric
  range: VolumeCellRange
  forwardSchema: ForwardSchemaId
  tenorSchema: TenorSchemaId
  packageType: PackageTypeGroupId
  timeseries: VolumeGridCellTimeseriesPoint[]
  recentTrades: VolumeGridCellRecentTrade[]
}
