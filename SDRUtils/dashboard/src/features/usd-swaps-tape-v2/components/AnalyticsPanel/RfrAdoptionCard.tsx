'use client'
// ABOUTME: RFR Adoption indicator card (design-doc §4.2 / §5.4 + Clarus
// "Recreating the RFR Adoption Indicator" 2025-04-29). Renders the
// headline single-number ratio for the loaded tape rows plus a tiny
// SVG sparkline of the monthly series so traders can see the
// trajectory at a glance.
import type { JSX } from 'react'
import type { UsdSwapTapeRow } from '../../types'
import {
  computeRfrAdoptionMonthly,
  computeRfrAdoptionRatio,
} from '../../utils/rfrAdoption'

export interface RfrAdoptionCardProps {
  rows: readonly UsdSwapTapeRow[]
  width?: number
  height?: number
}

function pct(ratio: number): string {
  if (!Number.isFinite(ratio)) return '—'
  return `${(ratio * 100).toFixed(1)}%`
}

export function RfrAdoptionCard(props: RfrAdoptionCardProps): JSX.Element {
  const width = props.width ?? 220
  const height = props.height ?? 36
  const headline = computeRfrAdoptionRatio(props.rows)
  const monthly = computeRfrAdoptionMonthly(props.rows)
  // Cap to last 24 months as suggested in the design doc
  const series = monthly.slice(-24)
  const xs = series.map((_, i) => i)
  const ys = series.map((p) => (Number.isFinite(p.ratio) ? p.ratio : 0))

  const minY = 0
  const maxY = 1
  // Pad the chart 2px so the line isn't flush with the border
  const padX = 2
  const padY = 2
  const innerW = width - padX * 2
  const innerH = height - padY * 2
  const xScale = (i: number): number =>
    series.length <= 1 ? padX + innerW / 2 : padX + (i / (series.length - 1)) * innerW
  const yScale = (v: number): number =>
    padY + innerH - ((v - minY) / (maxY - minY)) * innerH

  const pathD = xs
    .map((i, idx) => `${idx === 0 ? 'M' : 'L'} ${xScale(i).toFixed(2)} ${yScale(ys[i]).toFixed(2)}`)
    .join(' ')

  return (
    <div
      data-testid="rfr-adoption-card"
      className="flex flex-col gap-1 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300"
    >
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">
          USD RFR adoption
        </span>
        <span className="text-[10px] text-slate-500">
          {series.length}m series
        </span>
      </div>
      <div className="flex items-end gap-2">
        <span className="text-[20px] font-semibold tracking-tight text-indigo-200">
          {pct(headline.ratio)}
        </span>
        <span className="pb-1 text-[10px] text-slate-500">
          ΣDV01 RFR / (RFR + LIBOR + BSBY)
        </span>
      </div>
      {series.length > 0 ? (
        <svg
          role="img"
          aria-label="RFR adoption monthly trajectory"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          className="rounded bg-slate-900"
        >
          <line
            x1={padX}
            x2={width - padX}
            y1={yScale(0.5)}
            y2={yScale(0.5)}
            stroke="#475569"
            strokeDasharray="2,3"
          />
          <path d={pathD} fill="none" stroke="#818cf8" strokeWidth={1.4} />
        </svg>
      ) : (
        <div className="py-2 text-center text-[10px] text-slate-500">
          No in-scope rows.
        </div>
      )}
      <div className="grid grid-cols-2 gap-x-3 text-[10px] text-slate-500">
        <span>
          Numerator{' '}
          <span className="text-slate-300">
            {(headline.numerator / 1e3).toFixed(0)}K
          </span>
        </span>
        <span>
          Denominator{' '}
          <span className="text-slate-300">
            {(headline.denominator / 1e3).toFixed(0)}K
          </span>
        </span>
      </div>
    </div>
  )
}
