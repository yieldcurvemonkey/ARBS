// Pure geometry helpers for the cluster timeline strip.
import type { TemporalCluster } from '../../../types'

export type LayoutOpts = {
  width: number
  startTs: number
  endTs: number
}

export type BarGeometry = {
  cluster_id: string
  x: number
  width: number
  heightPct: number
  dominantLifecycle: string | null
}

export function clusterGeometry(
  clusters: TemporalCluster[],
  opts: LayoutOpts,
): BarGeometry[] {
  const span = Math.max(1, opts.endTs - opts.startTs)
  const maxCount = Math.max(1, ...clusters.map((c) => c.trade_count))
  return clusters.map((c) => {
    const start = Date.parse(c.start_ts)
    const end = Date.parse(c.end_ts)
    const x = ((start - opts.startTs) / span) * opts.width
    const width = Math.max(3, ((end - start) / span) * opts.width)
    const heightPct = Math.min(
      100,
      (Math.log10(Math.max(1, c.trade_count)) / Math.log10(maxCount + 1)) * 100,
    )
    return {
      cluster_id: c.cluster_id,
      x,
      width,
      heightPct,
      dominantLifecycle: c.lifecycle_types?.[0] ?? null,
    }
  })
}
