'use client'
// ABOUTME: One cell of the volume-grid heatmap. Pure render. Two view
// modes:
//   - volume:    single number colored by percentile
//   - idb_custy: a dual-stack bar showing IDB share (cyan) vs CUSTY
//                share (indigo), still tinted by the cell's percentile

import { memo, type JSX } from 'react'
import { colorForPercentile, foregroundForPercentile } from './colorRamp'
import type {
  VolumeGridCell as Cell, VolumeGridColorMode, VolumeGridViewMode, VolumeMetric, VolumePeriod,
  VolumeGridSchemaAxis,
} from '../../types/volume-grid.types'
import { lookupLabel } from './buckets'

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
  viewMode: VolumeGridViewMode
  colorMode?: VolumeGridColorMode
  colorPercentile?: number | null
  forwardAxis?: VolumeGridSchemaAxis
  tenorAxis?: VolumeGridSchemaAxis
  onClick: (id: { fwd: string; tenor: string }) => void
}

function comparisonForPeriod(period: VolumePeriod): string {
  switch (period) {
    case 'today': return 'vs prior days at the same time-of-day ET'
    case '1h':    return 'vs prior days in the same 1h slot ET'
    case '24h':   return 'vs rolling 24h windows in lookback'
    case '1w':    return 'vs prior weeks in lookback'
    case '2w':    return 'vs prior 2w windows in lookback'
    case '3w':    return 'vs prior 3w windows in lookback'
    case '1m':    return 'vs prior months in lookback'
    case '3m':    return 'vs prior quarters in lookback'
  }
}

function safeShare(part: number, total: number): number {
  if (!Number.isFinite(total) || total <= 0) return 0
  const s = part / total
  if (!Number.isFinite(s)) return 0
  return Math.max(0, Math.min(1, s))
}

export const VolumeGridCell = memo(function VolumeGridCell({
  cell, metric, period, viewMode, colorMode = 'activity', colorPercentile, forwardAxis, tenorAxis, onClick,
}: VolumeGridCellProps): JSX.Element {
  const isEmpty = cell.tradeCount === 0
  const heatmapPercentile =
    colorMode === 'grid' ? colorPercentile : cell.percentile
  const bg = isEmpty ? 'transparent' : colorForPercentile(heatmapPercentile ?? null)
  const fg = foregroundForPercentile(heatmapPercentile ?? null)
  const comparison = comparisonForPeriod(period)
  const fwdLabelText = lookupLabel(forwardAxis, cell.fwd)
  const tenorLabelText = lookupLabel(tenorAxis, cell.tenor)
  const idbShare = safeShare(cell.idbCurrent, cell.current)
  const custyShare = safeShare(cell.custyCurrent, cell.current)
  const idbPct = Math.round(idbShare * 100)
  const custyPct = Math.round(custyShare * 100)
  const splitNote = `IDB ${fmtCompact(cell.idbCurrent, metric)} (${idbPct}%) / CUSTY ${fmtCompact(cell.custyCurrent, metric)} (${custyPct}%)`
  const colorLabel =
    colorMode === 'grid'
      ? `${Math.round(colorPercentile ?? 0)}% of max visible bucket`
      : cell.percentile == null
        ? 'no history'
        : `${Math.round(cell.percentile)}th percentile ${comparison}`
  const label = `${fwdLabelText} x ${tenorLabelText} — ${fmtCompact(cell.current, metric)} ${metric}, ${colorLabel}; ${splitNote}`
  const tooltip = isEmpty
    ? 'No trades in this bucket for the current window'
    : `${fmtCompact(cell.current, metric)} ${metric} (${cell.tradeCount} trades, ${period}) | color: ${colorLabel} | ${comparison} P25=${fmtCompact(cell.baseline.p25, metric)} P50=${fmtCompact(cell.baseline.p50, metric)} P75=${fmtCompact(cell.baseline.p75, metric)} min=${fmtCompact(cell.baseline.min, metric)} max=${fmtCompact(cell.baseline.max, metric)} (n=${cell.baseline.n}) | ${splitNote}`
  const isSplitView = viewMode === 'idb_custy'
  return (
    <button
      type="button"
      disabled={isEmpty}
      aria-disabled={isEmpty}
      aria-label={label}
      title={tooltip}
      onClick={() => onClick({ fwd: cell.fwd, tenor: cell.tenor })}
      style={{ backgroundColor: bg }}
      className={`relative flex h-12 w-full flex-col items-center justify-center overflow-hidden rounded-sm border border-slate-800/40 px-1 text-center font-mono text-[11px] leading-tight transition-colors ${fg} ${isEmpty ? 'cursor-not-allowed opacity-50' : 'hover:ring-1 hover:ring-indigo-300/60'}`}
    >
      {isSplitView && !isEmpty && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-0 flex h-1.5"
        >
          <div
            className="bg-cyan-300/80"
            style={{ width: `${idbShare * 100}%` }}
          />
          <div
            className="bg-indigo-400/80"
            style={{ width: `${custyShare * 100}%` }}
          />
        </div>
      )}
      {isEmpty ? (
        <span className="text-slate-600">—</span>
      ) : isSplitView ? (
        <>
          <span className="tabular-nums">{fmtCompact(cell.current, metric)}</span>
          <span className="text-[9.5px] tabular-nums text-slate-300">
            <span className="text-cyan-200">{idbPct}</span>
            <span className="px-0.5 text-slate-500">/</span>
            <span className="text-indigo-200">{custyPct}</span>
          </span>
        </>
      ) : (
        <>
          <span className="tabular-nums">{fmtCompact(cell.current, metric)}</span>
          <span className="text-[9.5px] text-slate-400">
            {colorMode === 'grid'
              ? `G${Math.round(colorPercentile ?? 0)}`
              : cell.percentile == null
                ? 'P-'
                : `P${Math.round(cell.percentile)}`}
          </span>
        </>
      )}
    </button>
  )
})
