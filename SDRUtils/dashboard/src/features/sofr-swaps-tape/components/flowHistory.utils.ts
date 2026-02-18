import type { FlowHistoryDay } from '../types'

type FlowBucketKey =
  | 'frontShort'
  | 'frontLong'
  | 'forwardShort'
  | 'forwardLong'

export const FLOW_BUCKET_LABELS: Record<FlowBucketKey, string> = {
  frontShort: 'Front / Short',
  frontLong: 'Front / Long',
  forwardShort: 'Forward / Short',
  forwardLong: 'Forward / Long'
}

export function getLatestFlowDay(days: FlowHistoryDay[]): FlowHistoryDay | null {
  if (!days.length) return null
  return [...days].sort((a, b) => a.date.localeCompare(b.date)).at(-1) ?? null
}

export function flattenFlowHistory(days: FlowHistoryDay[]) {
  return days.map((day) => ({
    date: day.date,
    frontShortNotional: day.quadrants.frontShort.grossNotional,
    frontLongNotional: day.quadrants.frontLong.grossNotional,
    forwardShortNotional: day.quadrants.forwardShort.grossNotional,
    forwardLongNotional: day.quadrants.forwardLong.grossNotional,
    boundaryNotional: day.boundary.grossNotional,
    unknownNotional: day.unknown.grossNotional,
    frontShortRisk: day.quadrants.frontShort.grossRisk,
    frontLongRisk: day.quadrants.frontLong.grossRisk,
    forwardShortRisk: day.quadrants.forwardShort.grossRisk,
    forwardLongRisk: day.quadrants.forwardLong.grossRisk
  }))
}

export function buildFlowGridRows(day: FlowHistoryDay | null) {
  if (!day) return []
  const buckets: FlowBucketKey[] = [
    'frontShort',
    'frontLong',
    'forwardShort',
    'forwardLong'
  ]
  return buckets.map((bucket) => ({
    bucket,
    label: FLOW_BUCKET_LABELS[bucket],
    tradeCount: day.quadrants[bucket].tradeCount,
    grossNotional: day.quadrants[bucket].grossNotional,
    grossRisk: day.quadrants[bucket].grossRisk,
    avgFixedRate: day.quadrants[bucket].avgFixedRate,
    idbTradeCount: day.quadrants[bucket].idbTradeCount,
    custyTradeCount: day.quadrants[bucket].custyTradeCount
  }))
}

export function formatUsdMillions(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '--'
  return `${(value / 1_000_000).toFixed(1)}m`
}
