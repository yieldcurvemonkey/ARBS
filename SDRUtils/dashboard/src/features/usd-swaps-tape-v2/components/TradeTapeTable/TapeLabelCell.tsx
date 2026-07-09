'use client'
// ABOUTME: Trade-label cell that renders the raw tape label from the display view,
// with the tenor (expiry tail) / FOMC anchor bolded for faster trader scannability.
import type { JSX } from 'react'
import { useCallback, useState } from 'react'
import { createPortal } from 'react-dom'
import type { UsdSwapTapeLeg, UsdSwapTapeRow } from '../../types'
import { displayTapeLabel, parseTapeLabelSegments } from './TapeLabelCell.helpers'
import { stripExecutionTags } from './TapeLabelCell.helpers'

export { displayTapeLabel } from './TapeLabelCell.helpers'

function pkgLegsLines(row: UsdSwapTapeRow): string[] | null {
  const kind = String(row.package_type ?? '').toUpperCase()
  const isMultiLeg =
    kind.startsWith('PKG-') ||
    kind === 'CURVE' || kind === 'FLY' ||
    kind.startsWith('MATCHED_MATURITY') ||
    kind.endsWith('_CURVE') || kind.endsWith('_FLY')
  if (!isMultiLeg) return null
  const legs: UsdSwapTapeLeg[] = row.legs_json ?? []
  if (legs.length < 2) return null
  const sorted = [...legs].sort((a, b) => {
    const at = typeof a?.tenor_years === 'number' ? a.tenor_years : Infinity
    const bt = typeof b?.tenor_years === 'number' ? b.tenor_years : Infinity
    return at - bt
  })
  const lines = sorted
    .map((l) =>
      stripExecutionTags(
        l.leg_tape_label_ust_alias ?? l.leg_tape_label ?? l.tape_label ?? '',
      ).trim(),
    )
    .filter(Boolean)
  return lines.length >= 2 ? lines : null
}

function PkgTooltip({ lines, x, y }: { lines: string[]; x: number; y: number }) {
  return createPortal(
    <div
      className="pointer-events-none fixed z-[9999] whitespace-nowrap rounded border border-slate-600 bg-slate-800/95 px-3 py-2 shadow-xl backdrop-blur-sm"
      style={{ left: x, top: y }}
    >
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
        Package legs
      </div>
      {lines.map((line, i) => (
        <div
          key={i}
          className="font-mono text-[12px] leading-relaxed text-slate-200"
        >
          <span className="mr-2 text-slate-500">{i + 1}</span>
          {line}
        </div>
      ))}
    </div>,
    document.body,
  )
}

export function TapeLabelCell({ row }: { row: UsdSwapTapeRow }): JSX.Element {
  const label = displayTapeLabel(row)
  const segments = parseTapeLabelSegments(label)
  const legLines = pkgLegsLines(row)
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)

  const onEnter = useCallback((e: React.MouseEvent) => {
    const td = (e.currentTarget as HTMLElement).closest('td')
    if (td) {
      const r = td.getBoundingClientRect()
      setPos({ x: r.left, y: r.bottom + 2 })
    }
  }, [])

  return (
    <span
      className="font-mono text-[13px] text-gray-200"
      data-testid="tape-label-cell"
      onMouseEnter={legLines ? onEnter : undefined}
      onMouseLeave={legLines ? () => setPos(null) : undefined}
    >
      {segments.map((seg, i) => {
        const key = `${i}-${seg.isTenor ? 'T' : 'S'}-${seg.text.slice(0, 16)}`
        return seg.isTenor ? (
          <strong
            key={key}
            className="font-bold text-sky-300"
            data-testid="tape-label-tenor"
          >
            {seg.text}
          </strong>
        ) : (
          <span key={key}>{seg.text}</span>
        )
      })}
      {pos && legLines && <PkgTooltip lines={legLines} x={pos.x} y={pos.y} />}
    </span>
  )
}
