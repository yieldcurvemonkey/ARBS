'use client'

import { memo } from 'react'
import type { CellDisplayField, VolGridCell } from '../types'
import {
  STALENESS_COLORS,
  formatChange,
  formatNumber,
  formatPremiumBps,
  formatTime,
  formatConfidence,
  getUnifiedCellBackground
} from '../utils'

type UnifiedGridCellProps = {
  cell: VolGridCell
  isSelected: boolean
  visibleFields: CellDisplayField[]
  volMin: number
  volMax: number
  onClick: () => void
}

export const UnifiedGridCell = memo(function UnifiedGridCell({
  cell,
  isSelected,
  visibleFields,
  volMin,
  volMax,
  onClick
}: UnifiedGridCellProps) {
  const dotColor = STALENESS_COLORS[cell.stalenessCategory] ?? STALENESS_COLORS.no_data
  const isFresh =
    cell.atmfVolSource === 'direct_observation' &&
    cell.staleness !== null &&
    cell.staleness <= 5
  const isStaleOrWorse =
    cell.stalenessCategory === 'stale' || cell.stalenessCategory === 'very_stale'

  const tooltip = [
    `${cell.expiry}x${cell.tenor}`,
    `Vol: ${formatNumber(cell.atmfVol)} bpvol`,
    `Premium: ${formatPremiumBps(cell.atmfPremiumBps)}`,
    `Change: ${formatChange(cell.atmfVolChange)}`,
    `Confidence: ${formatConfidence(cell.atmfVolConfidence)}`,
    `Source: ${cell.atmfVolSource}`,
    `Regime: ${cell.regimeLabel ?? '--'}`,
    cell.lastObservation
      ? `Last SDR: ${formatTime(cell.lastObservation.executionTimestamp)} @ ${formatNumber(cell.lastObservation.bpvolYr, 1)}`
      : 'Last SDR: --'
  ].join('\n')

  return (
    <button
      title={tooltip}
      onClick={onClick}
      className={`relative flex min-h-[110px] flex-col p-2 text-left text-xs text-white transition ${
        isSelected ? 'ring-2 ring-sky-300' : ''
      } ${isFresh ? 'animate-pulse' : ''} ${
        isStaleOrWorse ? 'border-l-2' : ''
      }`}
      style={{
        backgroundColor: getUnifiedCellBackground(cell.atmfVol, volMin, volMax),
        borderLeftColor: isStaleOrWorse ? dotColor : undefined
      }}
    >
      {/* Staleness dot */}
      <span
        className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full"
        style={{ backgroundColor: dotColor }}
      />

      {/* Vol — primary */}
      {visibleFields.includes('vol') && (
        <div className="text-sm font-bold leading-tight text-white">
          {formatNumber(cell.atmfVol, 1)}
        </div>
      )}

      {/* Premium */}
      {visibleFields.includes('premium') && (
        <div className="text-[10px] text-slate-200/80">
          {formatPremiumBps(cell.atmfPremiumBps)}
        </div>
      )}

      {/* Change — color-coded */}
      {visibleFields.includes('change') && (
        <div
          className={`text-[10px] font-mono ${
            (cell.atmfVolChange ?? 0) > 0
              ? 'text-red-300'
              : (cell.atmfVolChange ?? 0) < 0
                ? 'text-emerald-300'
                : 'text-slate-300'
          }`}
        >
          {formatChange(cell.atmfVolChange)}
        </div>
      )}

      {/* Last traded time (SDR) */}
      {visibleFields.includes('lastTradedTime') && (
        <div className="mt-auto text-[9px] text-slate-300/60">
          {cell.lastObservation
            ? formatTime(cell.lastObservation.executionTimestamp)
            : '--'}
        </div>
      )}

      {/* Last traded level (SDR) */}
      {visibleFields.includes('lastTradedLevel') && (
        <div className="text-[9px] text-slate-300/60">
          {cell.lastObservation
            ? `${formatNumber(cell.lastObservation.bpvolYr, 1)} bpvol`
            : '--'}
        </div>
      )}

      {/* Confidence bar */}
      <div className="absolute bottom-0 left-0 right-0 h-[3px] bg-slate-800/40">
        <div
          className="h-full bg-sky-400/60"
          style={{ width: `${Math.round(cell.atmfVolConfidence * 100)}%` }}
        />
      </div>
    </button>
  )
})
