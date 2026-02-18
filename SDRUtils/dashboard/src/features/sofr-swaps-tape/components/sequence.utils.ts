import type { SofrSwapTapeRow } from '../types'

type SequenceEvent = {
  packageId: string
  packageType: string | null
  timestamp: number
  notional: number
  risk: number
}

export type SequenceCluster = {
  clusterId: string
  tradeCount: number
  startTime: string
  endTime: string
  durationSeconds: number
  avgGapSeconds: number | null
  paceTradesPerMinute: number | null
  grossNotional: number
  grossRisk: number
  avgClipNotional: number
  largestClipNotional: number
  dominantPackageType: string
  packageMix: Array<{ packageType: string; count: number }>
  riskConcentrationPct: number | null
}

function toNumber(value: unknown) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function toEvent(row: SofrSwapTapeRow): SequenceEvent | null {
  const ts = Date.parse(row.execution_start)
  if (!Number.isFinite(ts)) return null
  const notional = Math.abs(toNumber(row.total_notional))
  const risk = Math.abs(toNumber(row.total_risk))
  return {
    packageId: row.package_id,
    packageType: row.package_type,
    timestamp: ts,
    notional,
    risk
  }
}

function summarizeCluster(events: SequenceEvent[], index: number): SequenceCluster {
  const sorted = [...events].sort((a, b) => a.timestamp - b.timestamp)
  const start = sorted[0]?.timestamp ?? 0
  const end = sorted[sorted.length - 1]?.timestamp ?? start
  const durationSeconds = Math.max(0, (end - start) / 1000)
  const gaps: number[] = []
  for (let i = 1; i < sorted.length; i += 1) {
    gaps.push((sorted[i].timestamp - sorted[i - 1].timestamp) / 1000)
  }
  const avgGapSeconds = gaps.length
    ? gaps.reduce((acc, value) => acc + value, 0) / gaps.length
    : null
  const grossNotional = sorted.reduce((acc, item) => acc + item.notional, 0)
  const grossRisk = sorted.reduce((acc, item) => acc + item.risk, 0)
  const avgClipNotional = sorted.length ? grossNotional / sorted.length : 0
  const largestClipNotional = sorted.reduce(
    (acc, item) => Math.max(acc, item.notional),
    0
  )
  const paceTradesPerMinute =
    durationSeconds > 0 ? (sorted.length / durationSeconds) * 60 : null
  const maxRisk = sorted.reduce((acc, item) => Math.max(acc, item.risk), 0)
  const riskConcentrationPct =
    grossRisk > 0 ? (maxRisk / grossRisk) * 100 : null

  const packageCountMap = new Map<string, number>()
  sorted.forEach((event) => {
    const key = event.packageType || 'UNKNOWN'
    packageCountMap.set(key, (packageCountMap.get(key) || 0) + 1)
  })
  const packageMix = Array.from(packageCountMap.entries())
    .map(([packageType, count]) => ({ packageType, count }))
    .sort((a, b) => b.count - a.count)

  return {
    clusterId: `seq-${index + 1}`,
    tradeCount: sorted.length,
    startTime: new Date(start).toISOString(),
    endTime: new Date(end).toISOString(),
    durationSeconds,
    avgGapSeconds,
    paceTradesPerMinute,
    grossNotional,
    grossRisk,
    avgClipNotional,
    largestClipNotional,
    dominantPackageType: packageMix[0]?.packageType || 'UNKNOWN',
    packageMix,
    riskConcentrationPct
  }
}

export function buildSequenceClusters(
  rows: SofrSwapTapeRow[],
  maxGapSeconds = 180
): SequenceCluster[] {
  const events = rows
    .map((row) => toEvent(row))
    .filter((value): value is SequenceEvent => value !== null)
    .sort((a, b) => a.timestamp - b.timestamp)

  if (!events.length) return []
  const clusters: SequenceEvent[][] = []
  let current: SequenceEvent[] = [events[0]]
  for (let i = 1; i < events.length; i += 1) {
    const next = events[i]
    const prev = events[i - 1]
    const gapSeconds = (next.timestamp - prev.timestamp) / 1000
    if (gapSeconds <= maxGapSeconds) {
      current.push(next)
    } else {
      clusters.push(current)
      current = [next]
    }
  }
  clusters.push(current)

  return clusters
    .map((cluster, index) => summarizeCluster(cluster, index))
    .sort((a, b) => {
      if (b.grossRisk !== a.grossRisk) return b.grossRisk - a.grossRisk
      return b.tradeCount - a.tradeCount
    })
}
