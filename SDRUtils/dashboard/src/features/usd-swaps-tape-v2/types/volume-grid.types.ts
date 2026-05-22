// ABOUTME: Response shapes for /volume-grid and /volume-grid/cell.
// Imported by the route handlers and the SWR hooks.

import type {
  ForwardSchemaId,
  PackageTypeGroupId,
  TenorSchemaId,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

export type VolumeMetric = 'notional' | 'dv01'
export type VolumePeriod = 'today' | '1h' | '24h' | '1w' | '2w' | '3w' | '1m' | '3m'
export type VolumeCellRange = '1M' | '3M' | '6M' | '1Y'
export type VolumeGridViewMode = 'volume' | 'idb_custy'
export type VolumeGridColorMode = 'activity' | 'grid'

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
  idbCurrent: number
  custyCurrent: number
  tradeCount: number
  baseline: VolumeGridBaseline
  percentile: number | null
  outrightCurrent: number
  curveCurrent: number
  flyCurrent: number
  otherCurrent: number
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
  viewMode: VolumeGridViewMode
  collapseAxis?: 'tenor' | 'forward'
  textFilter?: string
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
  ptsVwap: number | null
}

export interface VolumeGridIntradaySeasonalityPoint {
  minuteOfDay: number
  time: string
  current: number | null
  average: number | null
}

export interface VolumeGridIntradaySeasonality {
  bucketMinutes: number
  observedDays: number
  asOf: string | null
  asOfMinuteOfDay: number | null
  points: VolumeGridIntradaySeasonalityPoint[]
}

export interface RecentTradeLeg {
  tenorYears: number
  forwardStartYears: number
  notional: number
  risk: number
  inCell: boolean
  isRiskLeg?: boolean
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
  legs: RecentTradeLeg[] | null
}

export interface VolumeGridCellResponse {
  fwd: string
  tenor?: string
  metric: VolumeMetric
  range: VolumeCellRange
  forwardSchema: ForwardSchemaId
  tenorSchema: TenorSchemaId
  packageType: PackageTypeGroupId
  timeseries: VolumeGridCellTimeseriesPoint[]
  intradaySeasonality: VolumeGridIntradaySeasonality
  recentTrades: VolumeGridCellRecentTrade[]
}
