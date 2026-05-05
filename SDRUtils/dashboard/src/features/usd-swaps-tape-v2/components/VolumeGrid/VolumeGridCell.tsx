'use client'
// ABOUTME: One cell of the volume-grid heatmap. Pure render.

import type { JSX } from 'react'
import { colorForPercentile, foregroundForPercentile } from './colorRamp'
import { fwdLabel, tenorLabel } from './buckets'
import type {
  VolumeGridCell as Cell, VolumeMetric, VolumePeriod,
} from '../../types/volume-grid.types'

export const fmtCompact = (n: number, _metric: VolumeMetric): string => {
  void _metric
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(0)}k`
  return `${sign}${abs.toFixed(0)}`
}

export interface VolumeGridCellProps {
  cell: Cell
  metric: VolumeMetric
  period: VolumePeriod
  onClick: (id: { fwd: Cell['fwd']; tenor: Cell['tenor'] }) => void
}

export function VolumeGridCell({ cell, metric, period, onClick }: VolumeGridCellProps): JSX.Element {
  const isEmpty = cell.tradeCount === 0 || cell.percentile == null
  const bg = isEmpty ? 'transparent' : colorForPercentile(cell.percentile)
  const fg = foregroundForPercentile(cell.percentile)
  const label = `${fwdLabel(cell.fwd)} x ${tenorLabel(cell.tenor)} — ${fmtCompact(cell.current, metric)} ${metric}, ${cell.percentile == null ? 'no history' : `${Math.round(cell.percentile)}th percentile vs lookback`}`
  const tooltip = isEmpty
    ? 'No trades in this bucket for the current window'
    : `${fmtCompact(cell.current, metric)} ${metric} (${cell.tradeCount} trades, ${period}) | vs P25=${fmtCompact(cell.baseline.p25, metric)} P50=${fmtCompact(cell.baseline.p50, metric)} P75=${fmtCompact(cell.baseline.p75, metric)} min=${fmtCompact(cell.baseline.min, metric)} max=${fmtCompact(cell.baseline.max, metric)} (n=${cell.baseline.n})`
  return (
    <button
      type="button"
      disabled={isEmpty}
      aria-disabled={isEmpty}
      aria-label={label}
      title={tooltip}
      onClick={() => onClick({ fwd: cell.fwd, tenor: cell.tenor })}
      style={{ backgroundColor: bg }}
      className={`flex h-12 w-full flex-col items-center justify-center rounded-sm border border-slate-800/40 px-1 text-center font-mono text-[11px] leading-tight transition-colors ${fg} ${isEmpty ? 'cursor-not-allowed opacity-50' : 'hover:ring-1 hover:ring-indigo-300/60'}`}
    >
      {isEmpty ? <span className="text-slate-600">—</span> : (
        <>
          <span className="tabular-nums">{fmtCompact(cell.current, metric)}</span>
          <span className="text-[9.5px] text-slate-400">P{Math.round(cell.percentile ?? 0)}</span>
        </>
      )}
    </button>
  )
}
