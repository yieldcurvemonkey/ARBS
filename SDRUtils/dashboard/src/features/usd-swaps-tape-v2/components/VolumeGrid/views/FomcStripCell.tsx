// ABOUTME: A single wider FOMC cell for the FomcStripView.
// Displays volume, percentile, and IDB/custy share for one FOMC meeting bucket.
'use client'
import { memo, type JSX } from 'react'
import { colorForPercentile, foregroundForPercentile } from '../colorRamp'
import type { VolumeGridCell as Cell, VolumeMetric } from '../../../types/volume-grid.types'

const fmtCompact = (n: number): string => {
  const abs = Math.abs(n)
  if (abs >= 1e9) return `${(abs / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${(abs / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${(abs / 1e3).toFixed(0)}k`
  return abs.toFixed(0)
}

function safeShare(part: number, total: number): number {
  if (!Number.isFinite(total) || total <= 0) return 0
  return Math.max(0, Math.min(1, part / total))
}

export interface FomcStripCellProps {
  cell: Cell
  label: string
  aliasLabel: string | null
  metric: VolumeMetric
  onClick: () => void
}

export const FomcStripCell = memo(function FomcStripCell({
  cell, label, aliasLabel, metric, onClick,
}: FomcStripCellProps): JSX.Element {
  const isEmpty = cell.tradeCount === 0
  const bg = isEmpty ? 'transparent' : colorForPercentile(cell.percentile)
  const fg = foregroundForPercentile(cell.percentile)
  const idbShare = safeShare(cell.idbCurrent, cell.current)
  const custyShare = safeShare(cell.custyCurrent, cell.current)

  return (
    <button
      type="button"
      disabled={isEmpty}
      onClick={onClick}
      style={{ backgroundColor: bg }}
      className={`relative flex h-20 w-[120px] flex-col items-center justify-center rounded border border-slate-800/40 px-2 font-mono transition-colors ${fg} ${isEmpty ? 'cursor-not-allowed opacity-50' : 'hover:ring-1 hover:ring-indigo-300/60'}`}
    >
      <span className="text-[10px] uppercase tracking-wider text-slate-400">
        {label}
        {aliasLabel && <span className="ml-1 text-slate-600">({aliasLabel})</span>}
      </span>
      {isEmpty ? (
        <span className="text-slate-600">&mdash;</span>
      ) : (
        <>
          <span className="text-sm tabular-nums">{fmtCompact(cell.current)} {metric}</span>
          <span className="text-[9.5px] text-slate-400">
            P{cell.percentile != null ? Math.round(cell.percentile) : '-'}
          </span>
          <div className="absolute inset-x-0 bottom-0 flex h-1.5">
            <div className="bg-cyan-300/80" style={{ width: `${idbShare * 100}%` }} />
            <div className="bg-indigo-400/80" style={{ width: `${custyShare * 100}%` }} />
          </div>
          <span className="absolute bottom-2 right-1.5 text-[8px] text-slate-500">
            {cell.tradeCount}
          </span>
        </>
      )}
    </button>
  )
})
