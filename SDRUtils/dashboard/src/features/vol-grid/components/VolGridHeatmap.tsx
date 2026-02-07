// ABOUTME: Heatmap grid component rendering the 12×10 expiry×tenor ATMF vol matrix.
// Supports VOL, PREMIUM, CHANGE, STALENESS view modes with appropriate color encoding.
'use client'

import { useState, useCallback, useMemo } from 'react'
import {
  VolGridCell,
  VolGridState,
  ViewMode,
  StalenessCategory,
  EXPIRY_LABELS,
  TENOR_LABELS,
} from '../types'
import { VolGridTooltip } from './VolGridTooltip'

// ---------------------------------------------------------------------------
// Color scales
// ---------------------------------------------------------------------------

function volToColor(vol: number | null): string {
  if (vol === null) return 'bg-slate-800/50'
  // Scale: 40-150 bpvol mapped to blue→amber→red
  const normalized = Math.max(0, Math.min(1, (vol - 40) / 110))
  if (normalized < 0.33) {
    const t = normalized / 0.33
    return interpolateClass(
      'bg-blue-900/60', 'bg-blue-700/60', 'bg-cyan-700/60',
      t,
    )
  }
  if (normalized < 0.66) {
    const t = (normalized - 0.33) / 0.33
    return interpolateClass(
      'bg-cyan-700/60', 'bg-amber-800/60', 'bg-amber-700/60',
      t,
    )
  }
  const t = (normalized - 0.66) / 0.34
  return interpolateClass(
    'bg-amber-700/60', 'bg-red-800/60', 'bg-red-700/60',
    t,
  )
}

function changeToColor(change: number | null): string {
  if (change === null) return 'bg-slate-800/50'
  if (Math.abs(change) < 0.3) return 'bg-slate-800/60'
  if (change > 0) {
    const intensity = Math.min(1, Math.abs(change) / 5)
    if (intensity < 0.5) return 'bg-red-900/40'
    return 'bg-red-800/60'
  }
  const intensity = Math.min(1, Math.abs(change) / 5)
  if (intensity < 0.5) return 'bg-green-900/40'
  return 'bg-green-800/60'
}

function stalenessToColor(category: StalenessCategory): string {
  switch (category) {
    case 'live': return 'bg-green-800/60'
    case 'recent': return 'bg-emerald-900/50'
    case 'stale': return 'bg-amber-900/40'
    case 'very_stale': return 'bg-red-900/30'
    case 'no_data': return 'bg-slate-800/30'
  }
}

function premiumToColor(premium: number | null): string {
  if (premium === null) return 'bg-slate-800/50'
  // Scale by bps: 0-500bps
  const bps = premium
  const normalized = Math.max(0, Math.min(1, bps / 500))
  if (normalized < 0.33) return 'bg-blue-900/60'
  if (normalized < 0.66) return 'bg-purple-900/50'
  return 'bg-amber-800/60'
}

function interpolateClass(low: string, mid: string, high: string, t: number): string {
  if (t < 0.5) return t < 0.25 ? low : mid
  return t < 0.75 ? mid : high
}

function stalenessDotColor(category: StalenessCategory): string {
  switch (category) {
    case 'live': return 'text-green-400'
    case 'recent': return 'text-emerald-500'
    case 'stale': return 'text-amber-500'
    case 'very_stale': return 'text-red-500'
    case 'no_data': return 'text-slate-600'
  }
}

function changeArrow(change: number | null): string {
  if (change === null) return ''
  if (change > 0.2) return '\u25B2' // ▲
  if (change < -0.2) return '\u25BC' // ▼
  return ''
}

function changeColor(change: number | null): string {
  if (change === null) return 'text-slate-500'
  if (change > 0.2) return 'text-red-400'
  if (change < -0.2) return 'text-green-400'
  return 'text-slate-500'
}

// ---------------------------------------------------------------------------
// Cell display value
// ---------------------------------------------------------------------------

function cellDisplayValue(cell: VolGridCell, mode: ViewMode): string {
  switch (mode) {
    case 'vol':
      return cell.atmfVol !== null ? cell.atmfVol.toFixed(1) : '—'
    case 'premium':
      return cell.atmfPremiumBps !== null ? cell.atmfPremiumBps.toFixed(1) : '—'
    case 'change':
      if (cell.atmfVolChange === null) return '—'
      const sign = cell.atmfVolChange >= 0 ? '+' : ''
      return `${sign}${cell.atmfVolChange.toFixed(1)}`
    case 'staleness':
      if (cell.staleness < 0) return '—'
      if (cell.staleness < 60) return `${Math.round(cell.staleness)}m`
      return `${(cell.staleness / 60).toFixed(1)}h`
  }
}

function cellBgColor(cell: VolGridCell, mode: ViewMode): string {
  switch (mode) {
    case 'vol': return volToColor(cell.atmfVol)
    case 'premium': return premiumToColor(cell.atmfPremiumBps)
    case 'change': return changeToColor(cell.atmfVolChange)
    case 'staleness': return stalenessToColor(cell.stalenessCategory)
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type Props = {
  gridState: VolGridState
  viewMode: ViewMode
  onCellClick?: (cell: VolGridCell) => void
}

export function VolGridHeatmap({ gridState, viewMode, onCellClick }: Props) {
  const [hoveredCell, setHoveredCell] = useState<{ i: number; j: number } | null>(null)
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null)

  const handleMouseEnter = useCallback((i: number, j: number, e: React.MouseEvent) => {
    setHoveredCell({ i, j })
    const rect = (e.target as HTMLElement).getBoundingClientRect()
    setTooltipPos({ x: rect.right + 8, y: rect.top })
  }, [])

  const handleMouseLeave = useCallback(() => {
    setHoveredCell(null)
    setTooltipPos(null)
  }, [])

  const hoveredCellData = useMemo(() => {
    if (!hoveredCell) return null
    return gridState.cells[hoveredCell.i]?.[hoveredCell.j] ?? null
  }, [hoveredCell, gridState.cells])

  return (
    <div className="relative">
      <div className="overflow-x-auto">
        <table className="border-collapse text-xs font-mono">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-slate-900 px-2 py-1.5 text-right text-slate-400 font-normal border-b border-slate-700">
                Exp \ Tnr
              </th>
              {TENOR_LABELS.map(tenor => (
                <th
                  key={tenor}
                  className="px-1.5 py-1.5 text-center text-slate-400 font-normal border-b border-slate-700 min-w-[60px]"
                >
                  {tenor}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {EXPIRY_LABELS.map((expiry, i) => (
              <tr key={expiry} className="hover:bg-slate-800/30">
                <td className="sticky left-0 z-10 bg-slate-900 px-2 py-0.5 text-right text-slate-400 font-normal border-r border-slate-700/50 whitespace-nowrap">
                  {expiry}
                </td>
                {TENOR_LABELS.map((tenor, j) => {
                  const cell = gridState.cells[i]?.[j]
                  if (!cell) return <td key={tenor} className="px-1.5 py-0.5" />

                  const isHovered = hoveredCell?.i === i && hoveredCell?.j === j
                  const bg = cellBgColor(cell, viewMode)
                  const value = cellDisplayValue(cell, viewMode)

                  return (
                    <td
                      key={tenor}
                      className={`relative px-1 py-0.5 text-center cursor-pointer border border-slate-800/40 transition-all duration-100 select-none ${bg} ${isHovered ? 'ring-1 ring-blue-400/60' : ''}`}
                      onMouseEnter={(e) => handleMouseEnter(i, j, e)}
                      onMouseLeave={handleMouseLeave}
                      onClick={() => onCellClick?.(cell)}
                    >
                      <div className="flex flex-col items-center gap-0 leading-tight">
                        <span className={`text-[11px] font-medium ${cell.atmfVol === null ? 'text-slate-600' : cell.atmfVolSource === 'interpolated' ? 'text-slate-300' : 'text-slate-100'}`}>
                          {value}
                        </span>
                        {viewMode !== 'change' && viewMode !== 'staleness' && cell.atmfVolChange !== null && (
                          <span className={`text-[9px] leading-none ${changeColor(cell.atmfVolChange)}`}>
                            {changeArrow(cell.atmfVolChange)}{' '}
                            {cell.atmfVolChange >= 0 ? '+' : ''}{cell.atmfVolChange.toFixed(1)}
                          </span>
                        )}
                        <span className={`text-[7px] leading-none ${stalenessDotColor(cell.stalenessCategory)}`}>
                          {'\u25CF'}
                        </span>
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Tooltip */}
      {hoveredCellData && tooltipPos && (
        <VolGridTooltip cell={hoveredCellData} position={tooltipPos} />
      )}
    </div>
  )
}
