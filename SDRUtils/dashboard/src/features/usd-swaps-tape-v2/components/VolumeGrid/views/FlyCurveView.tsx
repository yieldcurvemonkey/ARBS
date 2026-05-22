'use client'
import type { JSX } from 'react'
import { useState } from 'react'
import { StructureGridView } from './StructureGridView'
import { ALL_FLIES, BENCHMARK_FLIES, MICRO_FLIES } from '@/lib/usd-swaps-tape-v2/structureDefs'
import type { ViewProps } from '../../../types/volume-grid-views.types'
import type { StructureDef } from '../../../types/structure-grid.types'

type FlyFilter = 'all' | 'benchmark' | 'micro'
const FILTERS: { id: FlyFilter; label: string; defs: readonly StructureDef[] }[] = [
  { id: 'all',       label: 'All',       defs: ALL_FLIES },
  { id: 'benchmark', label: 'Benchmark', defs: BENCHMARK_FLIES },
  { id: 'micro',     label: 'Micro',     defs: MICRO_FLIES },
]

export function FlyCurveView(props: ViewProps): JSX.Element {
  const [filter, setFilter] = useState<FlyFilter>('all')
  const structures = FILTERS.find(f => f.id === filter)!.defs

  return (
    <>
      <div className="flex items-center gap-2 px-3 pb-1">
        <div className="flex items-center rounded border border-slate-700 p-[1px]">
          {FILTERS.map(f => (
            <button key={f.id} type="button" onClick={() => setFilter(f.id)}
              className={`px-2 py-[1px] font-mono text-[10.5px] ${filter === f.id ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
            >{f.label}</button>
          ))}
        </div>
        <span className="font-mono text-[9px] text-slate-500">{structures.length} structures</span>
      </div>
      <StructureGridView
        structureType="fly"
        structures={structures}
        metric={props.metric}
        period={props.period}
        lookbackDays={props.lookbackDays}
        textFilter={props.textFilter}
        onCellClick={props.onCellClick}
      />
    </>
  )
}
