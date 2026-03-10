'use client'

import type { ListedVolDisplayMode, ListedVolGridCell as ListedVolGridCellType } from '../types'
import {
  formatPercentile,
  formatSigned,
  formatVol,
  getDisplayLabel,
  getZScoreTone,
  interpolateHeatmap
} from '../utils'

type ListedVolGridCellProps = {
  cell: ListedVolGridCellType
  mode: ListedVolDisplayMode
  onClick: () => void
}

export function ListedVolGridCell({
  cell,
  mode,
  onClick
}: ListedVolGridCellProps) {
  const displayValue =
    mode === 'dchg'
      ? formatSigned(cell.dailyChange)
      : mode === 'zscore'
        ? formatVol(cell.zScore, 2)
        : formatVol(cell.atmNvolBps)
  const secondaryValue =
    mode === 'vol'
      ? `dChg ${formatSigned(cell.dailyChange)}`
      : `Pct ${formatPercentile(cell.percentile)}`
  const background =
    mode === 'vol'
      ? interpolateHeatmap(cell.zScore, 2.5)
      : interpolateHeatmap(mode === 'dchg' ? cell.dailyChange : cell.zScore, 2.5)

  return (
    <button
      type="button"
      onClick={onClick}
      title={`${cell.product} ${cell.expiryLabel} ${getDisplayLabel(mode)} ${displayValue}`}
      className="flex min-h-[84px] w-full flex-col justify-between border border-slate-800 px-3 py-2 text-left transition hover:border-slate-600"
      style={{ background }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-300">
          {cell.product}
        </div>
        <div className="text-[11px] text-slate-400">{cell.expiryLabel}</div>
      </div>
      <div>
        <div className={`text-xl font-semibold tabular-nums ${getZScoreTone(mode === 'vol' ? cell.zScore : cell.dailyChange)}`}>
          {displayValue}
        </div>
        <div className="mt-1 text-xs text-slate-300">{secondaryValue}</div>
      </div>
    </button>
  )
}
