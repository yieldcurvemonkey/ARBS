'use client'
// ABOUTME: MMS (matched-maturity swap / UST asset-swap) Analytics tab.
// Placeholder for Task 6 — Task 7 fills in the 4-panel layout (summary
// strip, daily volume chart, maturity distribution, top CUSIPs table)
// per design doc 2026-07-09-mms-extension-design.md §3d.
import type { Dispatch, JSX, SetStateAction } from 'react'
import type { UsdSwapTapeRow } from '../../types'
import type { MmsState } from './analytics-types'

export interface MmsTabProps {
  rows: readonly UsdSwapTapeRow[]
  state: MmsState
  setState: Dispatch<SetStateAction<MmsState>>
}

export function MmsTab({ rows }: MmsTabProps): JSX.Element {
  return (
    <div className="p-3 text-sm text-slate-400">
      MMS tab — {rows.length} rows loaded
    </div>
  )
}
