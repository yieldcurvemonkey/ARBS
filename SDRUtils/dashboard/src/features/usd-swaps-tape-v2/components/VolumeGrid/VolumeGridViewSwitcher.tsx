'use client'
import type { JSX } from 'react'
import { VOLUME_GRID_VIEWS } from './views/volumeGridViews'
import type { CellId, CellContext } from '../../types/volume-grid-views.types'
import type { VolumeMetric, VolumePeriod } from '../../types/volume-grid.types'

export interface VolumeGridViewSwitcherProps {
  activeViewId: string
  onViewChange: (id: string) => void
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  textFilter: string
  onCellClick: (cell: CellId, context?: CellContext) => void
}

export function VolumeGridViewSwitcher({
  activeViewId, onViewChange,
  metric, period, lookbackDays, textFilter, onCellClick,
}: VolumeGridViewSwitcherProps): JSX.Element {
  const view = VOLUME_GRID_VIEWS.find((v) => v.id === activeViewId) ?? VOLUME_GRID_VIEWS[0]
  const Component = view.component

  return (
    <>
      <ViewTabs activeId={activeViewId} onChange={onViewChange} />
      <Component
        metric={metric}
        period={period}
        lookbackDays={lookbackDays}
        textFilter={textFilter}
        onCellClick={onCellClick}
      />
    </>
  )
}

function ViewTabs({ activeId, onChange }: { activeId: string; onChange: (id: string) => void }): JSX.Element {
  return (
    <div className="flex items-center rounded border border-slate-700 p-[1px]">
      {VOLUME_GRID_VIEWS.map((v) => (
        <button
          key={v.id}
          type="button"
          onClick={() => onChange(v.id)}
          className={`px-2 py-[1px] font-mono text-[10.5px] ${activeId === v.id ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
        >
          {v.label}
        </button>
      ))}
    </div>
  )
}
