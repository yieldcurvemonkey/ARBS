'use client'
// ABOUTME: Fly Curve view — renders butterfly structures (2s5s10s, 5s10s30s,
// etc.) via the shared StructureGridView. Offers a Standard/All toggle to
// control which fly definitions are included.

import type { JSX } from 'react'
import { useState } from 'react'
import { StructureGridView } from './StructureGridView'
import { STANDARD_FLIES, ALL_FLIES } from '@/lib/usd-swaps-tape-v2/structureDefs'
import type { ViewProps } from '../../../types/volume-grid-views.types'

export function FlyCurveView(props: ViewProps): JSX.Element {
  const [showAll, setShowAll] = useState(false)

  return (
    <>
      <div className="flex items-center gap-2 px-3 pb-1">
        <Toggle
          options={[
            { id: 'standard', label: 'Standard' },
            { id: 'all', label: 'All' },
          ]}
          value={showAll ? 'all' : 'standard'}
          onChange={(v) => setShowAll(v === 'all')}
        />
      </div>
      <StructureGridView
        structureType="fly"
        structures={showAll ? ALL_FLIES : STANDARD_FLIES}
        metric={props.metric}
        period={props.period}
        lookbackDays={props.lookbackDays}
        textFilter={props.textFilter}
        onCellClick={props.onCellClick}
      />
    </>
  )
}

// ─── Local helper ───────────────────────────────────────────────────────────

function Toggle<T extends string>({
  options,
  value,
  onChange,
}: {
  options: ReadonlyArray<{ id: T; label: string }>
  value: T
  onChange: (v: T) => void
}): JSX.Element {
  return (
    <div className="flex items-center rounded border border-slate-700 p-[1px]">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          onClick={() => onChange(o.id)}
          className={`px-2 py-[1px] font-mono text-[10.5px] ${value === o.id ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
