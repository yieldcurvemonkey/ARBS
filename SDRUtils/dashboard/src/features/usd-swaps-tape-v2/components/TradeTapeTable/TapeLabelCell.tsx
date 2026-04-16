'use client'
// ABOUTME: Trade-label cell that renders the raw tape label from the display view.
import type { JSX } from 'react'
import type { UsdSwapTapeRow } from '../../types'
import { displayTapeLabel } from './TapeLabelCell.helpers'

export { displayTapeLabel } from './TapeLabelCell.helpers'

export function TapeLabelCell({ row }: { row: UsdSwapTapeRow }): JSX.Element {
  return (
    <span
      className="font-mono text-[13px] text-gray-200"
      data-testid="tape-label-cell"
    >
      {displayTapeLabel(row)}
    </span>
  )
}
