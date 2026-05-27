import type { VolumeMetric, VolumePeriod, VolumeGridIntradaySeasonality } from './volume-grid.types'
import type { PackageTypeGroupId } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

export interface AggregateDailyPoint {
  day: string
  total: number
  idb: number
  custy: number
  outright: number
  curve: number
  fly: number
  invoice: number
  other: number
  tradeCount: number
  avgTradeSize: number
  blockCount: number
  blockVolume: number
  weightedAvgTenor: number
}

export interface AggregateSummary {
  currentTotal: number
  percentileRank: number | null
  adv: number
  currentVsAdv: number
  tradeCount: number
  tradeCountPercentile: number | null
  blockCount: number
  blockVolume: number
  weightedAvgTenor: number
}

export interface AggregateDistributionEntry {
  id: string
  label: string
  current: number
  historicalAvg: number
  share: number
  historicalShare: number
}

export interface StructureProjectionEntry {
  structureKey: string
  todayVolume: number
  todayCount: number
  lastTradeTime: string | null
  latestPlatform: string | null
  lastLevel: number | null
  adv1w: number
  adv1m: number
}

export interface AggregateVolumeResponse {
  asOf: string
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  packageType: PackageTypeGroupId
  dailySeries: AggregateDailyPoint[]
  summary: AggregateSummary
  intradayCurve: VolumeGridIntradaySeasonality
  tenorDistribution: AggregateDistributionEntry[]
  packageMix: AggregateDistributionEntry[]
  venueSplit: {
    idb: AggregateDistributionEntry
    custy: AggregateDistributionEntry
  }
  structureProjection: StructureProjectionEntry[]
}
