'use client'
// ABOUTME: Trade-label cell that renders the raw tape label from the display view,
// with the tenor (expiry tail) / FOMC anchor bolded for faster trader scannability.
import type { JSX } from 'react'
import type { UsdSwapTapeRow } from '../../types'
import { displayTapeLabel, parseTapeLabelSegments } from './TapeLabelCell.helpers'

export { displayTapeLabel } from './TapeLabelCell.helpers'

export function TapeLabelCell({ row }: { row: UsdSwapTapeRow }): JSX.Element {
  const label = displayTapeLabel(row)
  const segments = parseTapeLabelSegments(label)
  return (
    <span
      className="font-mono text-[13px] text-gray-200"
      data-testid="tape-label-cell"
    >
      {segments.map((seg, i) =>
        seg.isTenor ? (
          <strong
            key={i}
            className="font-bold text-sky-300"
            data-testid="tape-label-tenor"
          >
            {seg.text}
          </strong>
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      )}
    </span>
  )
}
