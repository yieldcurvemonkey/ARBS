'use client'
// ABOUTME: Spreadover Strip — shows spot-starting spreadover package
// volumes across benchmark tenors. Uses the standard volume-grid
// endpoint with packageType='spreadover' and collapseAxis='forward'.

import type { JSX } from 'react'
import { useCallback, useMemo, useState } from 'react'
import { VolumeGrid } from '../VolumeGrid'
import { useVolumeGrid } from '../../../hooks/useVolumeGrid'
import type {
  VolumeGridColorMode,
  VolumeGridViewMode,
  VolumeMetric,
  VolumePeriod,
} from '../../../types/volume-grid.types'
import type { CellId, ViewProps } from '../../../types/volume-grid-views.types'
import type { BucketDef } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

const SPREADOVER_TENORS: BucketDef[] = [
  { id: '2y',  label: '2Y',  lo: 1.85,  hi: 2.5 },
  { id: '3y',  label: '3Y',  lo: 2.5,   hi: 3.5 },
  { id: '5y',  label: '5Y',  lo: 4.5,   hi: 5.5 },
  { id: '7y',  label: '7Y',  lo: 6.5,   hi: 7.5 },
  { id: '10y', label: '10Y', lo: 9.5,   hi: 10.5 },
  { id: '20y', label: '20Y', lo: 19.5,  hi: 21.0 },
  { id: '30y', label: '30Y', lo: 29.5,  hi: 31.0 },
]

const SPOT_FORWARD: BucketDef[] = [
  { id: 'spot', label: 'Spot', lo: null, hi: 0.125 },
]

export function SpreadoverStripView(props: ViewProps): JSX.Element {
  const [viewMode, setViewMode] = useState<VolumeGridViewMode>('volume')
  const [colorMode, setColorMode] = useState<VolumeGridColorMode>('activity')

  const grid = useVolumeGrid({
    metric: props.metric,
    period: props.period,
    lookbackDays: props.lookbackDays,
    forwardSchema: 'custom',
    tenorSchema: 'custom',
    packageType: 'spreadover',
    viewMode,
    textFilter: props.textFilter,
    collapsed: false,
    customForwardBuckets: SPOT_FORWARD,
    customTenorBuckets: SPREADOVER_TENORS,
  })

  const handleCellClick = useCallback(
    (id: { fwd: string; tenor: string }) => {
      props.onCellClick({ kind: 'matrix', fwd: id.fwd, tenor: id.tenor })
    },
    [props.onCellClick],
  )

  return (
    <div className="px-3 pb-3">
      <div className="flex flex-wrap items-center gap-2 pb-2">
        <Toggle
          options={[
            { id: 'activity' as const, label: 'Activity' },
            { id: 'grid' as const, label: 'Grid' },
          ]}
          value={colorMode}
          onChange={setColorMode}
        />
        <Toggle
          options={[
            { id: 'volume' as const, label: 'Volume' },
            { id: 'idb_custy' as const, label: 'IDB / CUSTY' },
          ]}
          value={viewMode}
          onChange={setViewMode}
        />
      </div>
      {grid.data ? (
        <VolumeGrid
          data={grid.data}
          metric={props.metric}
          period={props.period}
          viewMode={viewMode}
          colorMode={colorMode}
          packageType="spreadover"
          onCellClick={handleCellClick}
        />
      ) : (
        <div className="grid h-12 animate-pulse grid-cols-7 gap-px">
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="rounded-sm bg-slate-800/40" />
          ))}
        </div>
      )}
    </div>
  )
}

function Toggle<T extends string>({
  options, value, onChange,
}: { options: ReadonlyArray<{ id: T; label: string }>; value: T; onChange: (v: T) => void }): JSX.Element {
  return (
    <div className="flex items-center rounded border border-slate-700 p-[1px]">
      {options.map((o) => (
        <button key={o.id} type="button" onClick={() => onChange(o.id)}
          className={`px-2 py-[1px] font-mono text-[10.5px] ${value === o.id ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
        >{o.label}</button>
      ))}
    </div>
  )
}
