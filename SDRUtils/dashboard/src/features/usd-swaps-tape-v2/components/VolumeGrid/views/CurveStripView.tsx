'use client'
// ABOUTME: Curve Strip view — renders spread structures (2s10s, 5s30s, etc.)
// via the shared StructureGridView. Offers a Benchmark/All toggle to control
// which curve definitions are included.

import type { JSX } from 'react'
import { useState } from 'react'
import { StructureGridView } from './StructureGridView'
import { BENCHMARK_CURVES, ALL_CURVES } from '@/lib/usd-swaps-tape-v2/structureDefs'
import type { ViewProps } from '../../../types/volume-grid-views.types'

export function CurveStripView(props: ViewProps): JSX.Element {
  const [showAll, setShowAll] = useState(false)

  return (
    <>
      <div className="flex items-center gap-2 px-3 pb-1">
        <Toggle
          options={[
            { id: 'benchmark', label: 'Benchmark' },
            { id: 'all', label: 'All' },
          ]}
          value={showAll ? 'all' : 'benchmark'}
          onChange={(v) => setShowAll(v === 'all')}
        />
      </div>
      <StructureGridView
        structureType="curve"
        structures={showAll ? ALL_CURVES : BENCHMARK_CURVES}
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
