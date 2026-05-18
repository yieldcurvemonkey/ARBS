// ABOUTME: Horizontal strip view showing one wider cell per active FOMC meeting.
// Calls /volume-grid with forwardSchema=fomc and collapseAxis=tenor so each cell
// represents total volume for that FOMC meeting across all tenors.
'use client'
import { useCallback, useMemo, useState, type JSX } from 'react'
import { FomcStripCell } from './FomcStripCell'
import { useVolumeGrid } from '../../../hooks/useVolumeGrid'
import { buildFomcConstantMaturityMap, fomcAliasForLabel } from '@/lib/usd-swaps-tape-v2/fomcConstantMaturity'
import type { CellId, FomcLabelMode } from '../../../types/volume-grid-views.types'
import type { VolumeGridCell as Cell, VolumeMetric, VolumePeriod } from '../../../types/volume-grid.types'

export interface FomcStripViewProps {
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  textFilter: string
  onCellClick: (cell: CellId) => void
}

export function FomcStripView({ metric, period, lookbackDays, textFilter, onCellClick }: FomcStripViewProps): JSX.Element {
  const [labelMode, setLabelMode] = useState<FomcLabelMode>('absolute')

  const grid = useVolumeGrid({
    metric, period, collapsed: false,
    lookbackDays,
    forwardSchema: 'fomc',
    tenorSchema: 'default',
    packageType: 'all',
    viewMode: 'volume',
    textFilter: textFilter || undefined,
    collapseAxis: 'tenor',
  })

  const fomcMap = useMemo(() => buildFomcConstantMaturityMap(), [])

  const cellMap = useMemo(() => {
    if (!grid.data) return new Map<string, Cell>()
    const m = new Map<string, Cell>()
    for (const c of grid.data.cells) m.set(c.fwd, c)
    return m
  }, [grid.data])

  const handleCellClick = useCallback((fwd: string) => {
    onCellClick({ kind: 'collapsed_tenor', fwd })
  }, [onCellClick])

  const buckets = grid.data?.axes.forward.buckets ?? []

  return (
    <div className="px-3 pb-3">
      <div className="mb-2 flex items-center gap-2">
        <div className="flex items-center rounded border border-slate-700 p-[1px]">
          <button
            type="button"
            onClick={() => setLabelMode('absolute')}
            className={`px-2 py-[1px] font-mono text-[10.5px] ${labelMode === 'absolute' ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
          >
            Absolute
          </button>
          <button
            type="button"
            onClick={() => setLabelMode('constant_maturity')}
            className={`px-2 py-[1px] font-mono text-[10.5px] ${labelMode === 'constant_maturity' ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
          >
            FOMC#
          </button>
        </div>
        {grid.isLoading && (
          <span className="rounded bg-sky-500/15 px-1.5 py-[1px] font-mono text-[10px] text-sky-200 ring-1 ring-sky-500/30">
            loading&hellip;
          </span>
        )}
        {grid.error && (
          <span className="rounded bg-rose-500/15 px-1.5 py-[1px] font-mono text-[10px] text-rose-200 ring-1 ring-rose-500/30">
            {grid.error.message}
          </span>
        )}
      </div>
      <div data-testid="fomc-strip" className="flex gap-2 overflow-x-auto">
        {buckets.map((b) => {
          const cell = cellMap.get(b.id) ?? {
            fwd: b.id, tenor: '_all_', current: 0, idbCurrent: 0, custyCurrent: 0,
            tradeCount: 0, baseline: { p25: 0, p50: 0, p75: 0, min: 0, max: 0, n: 0 },
            percentile: null, outrightCurrent: 0, curveCurrent: 0, flyCurrent: 0, otherCurrent: 0,
          }
          const alias = fomcAliasForLabel(b.id, fomcMap)
          const displayLabel = labelMode === 'constant_maturity' && alias ? alias : b.id
          const displayAlias = labelMode === 'constant_maturity' ? b.id : alias
          return (
            <FomcStripCell
              key={b.id}
              cell={cell}
              label={displayLabel}
              aliasLabel={displayAlias}
              metric={metric}
              onClick={() => handleCellClick(b.id)}
            />
          )
        })}
        {buckets.length === 0 && !grid.isLoading && (
          <div className="flex h-20 items-center px-3 font-mono text-[11px] text-slate-500">
            No FOMC-dated trades in current window.
          </div>
        )}
      </div>
    </div>
  )
}
