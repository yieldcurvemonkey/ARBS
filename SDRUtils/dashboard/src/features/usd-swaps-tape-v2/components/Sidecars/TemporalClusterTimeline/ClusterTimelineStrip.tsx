'use client'
// ABOUTME: Full-width SVG strip rendering temporal clusters per day.
import type { JSX } from 'react'
import { useTemporalClusters } from '../../../hooks/useTemporalClusters'
import { LIFECYCLE_TONES } from '../../../constants'
import type { LifecycleType } from '../../../types'
import { clusterGeometry } from './ClusterTimelineStrip.helpers'

export { clusterGeometry } from './ClusterTimelineStrip.helpers'

const STRIP_HEIGHT = 48
const STRIP_WIDTH = 1400

function dominantFill(lifecycle: string | null): string {
  if (!lifecycle) return '#334155'
  const key = lifecycle as LifecycleType
  const className = LIFECYCLE_TONES[key]
  if (!className) return '#334155'
  if (className.includes('emerald')) return '#059669'
  if (className.includes('red')) return '#dc2626'
  if (className.includes('purple')) return '#a855f7'
  if (className.includes('amber')) return '#f59e0b'
  if (className.includes('rose')) return '#e11d48'
  if (className.includes('sky')) return '#0ea5e9'
  if (className.includes('zinc')) return '#71717a'
  return '#334155'
}

export interface ClusterTimelineStripProps {
  date: string
  onSelectCluster?: (clusterId: string) => void
}

export function ClusterTimelineStrip(props: ClusterTimelineStripProps): JSX.Element {
  const { data, isLoading } = useTemporalClusters({ date: props.date })
  const clusters = data?.clusters ?? []
  const startTs = clusters.length ? Date.parse(clusters[0].start_ts) : 0
  const endTs = clusters.length
    ? Date.parse(clusters[clusters.length - 1].end_ts)
    : startTs + 1
  const bars = clusterGeometry(clusters, {
    width: STRIP_WIDTH,
    startTs,
    endTs,
  })

  return (
    <div
      className="w-full bg-slate-900/50 border-b border-slate-800 px-2 py-1 overflow-x-auto"
      data-testid="cluster-timeline-strip"
    >
      {isLoading ? (
        <p className="text-slate-400 text-xs">Loading clusters…</p>
      ) : null}
      <svg
        width={STRIP_WIDTH}
        height={STRIP_HEIGHT}
        role="img"
        aria-label="temporal cluster timeline"
      >
        <rect width={STRIP_WIDTH} height={STRIP_HEIGHT} fill="#0f172a" />
        {bars.map((b) => (
          <g key={b.cluster_id}>
            <title>{b.cluster_id}</title>
            <rect
              x={b.x}
              y={STRIP_HEIGHT - (b.heightPct / 100) * STRIP_HEIGHT}
              width={b.width}
              height={(b.heightPct / 100) * STRIP_HEIGHT}
              fill={dominantFill(b.dominantLifecycle)}
              onClick={() => props.onSelectCluster?.(b.cluster_id)}
              style={{ cursor: 'pointer' }}
            />
          </g>
        ))}
      </svg>
    </div>
  )
}
