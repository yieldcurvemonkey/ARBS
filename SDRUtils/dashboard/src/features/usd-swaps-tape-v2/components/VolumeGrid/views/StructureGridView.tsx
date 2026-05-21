'use client'
// ABOUTME: Shared component for Curve Strip and Fly Curve views. Fetches
// from /volume-grid/structure and renders the existing VolumeGrid with
// forward-start rows x structure columns.

import type { JSX } from 'react'
import { useCallback, useMemo, useState } from 'react'
import { VolumeGrid } from '../VolumeGrid'
import { useStructureGrid } from '../../../hooks/useStructureGrid'
import type {
  VolumeGridColorMode,
  VolumeGridViewMode,
  VolumeMetric,
  VolumePeriod,
  VolumeGridResponse,
} from '../../../types/volume-grid.types'
import type { StructureDef, StructureType } from '../../../types/structure-grid.types'
import type { CellId } from '../../../types/volume-grid-views.types'

// ─── Constants ──────────────────────────────────────────────────────────────

const VIEW_MODE_IDS: ReadonlyArray<VolumeGridViewMode> = ['volume', 'idb_custy']
const VIEW_MODE_LABELS: Record<VolumeGridViewMode, string> = {
  volume: 'Volume',
  idb_custy: 'IDB / CUSTY',
}
const COLOR_MODE_IDS: ReadonlyArray<VolumeGridColorMode> = ['activity', 'grid']
const COLOR_MODE_LABELS: Record<VolumeGridColorMode, string> = {
  activity: 'Activity',
  grid: 'Grid',
}

// ─── Props ──────────────────────────────────────────────────────────────────

export interface StructureGridViewProps {
  structureType: StructureType
  structures: readonly StructureDef[]
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  textFilter: string
  onCellClick: (cell: CellId) => void
}

// ─── Component ──────────────────────────────────────────────────────────────

export function StructureGridView({
  structureType,
  structures,
  metric,
  period,
  lookbackDays,
  textFilter,
  onCellClick,
}: StructureGridViewProps): JSX.Element {
  // View-specific state
  const [viewMode, setViewMode] = useState<VolumeGridViewMode>('volume')
  const [colorMode, setColorMode] = useState<VolumeGridColorMode>('activity')

  // Data fetching
  const grid = useStructureGrid({
    structureType,
    structures,
    metric,
    period,
    lookbackDays,
    textFilter,
    collapsed: false,
  })

  // Adapt StructureGridResponse -> VolumeGridResponse so VolumeGrid can render it
  const gridData: VolumeGridResponse | undefined = useMemo(() => {
    if (!grid.data) return undefined
    return {
      asOf: grid.data.asOf,
      metric: grid.data.metric as VolumeMetric,
      period: grid.data.period as VolumePeriod,
      lookbackDays: grid.data.lookbackDays,
      forwardSchema: 'default' as const,
      tenorSchema: 'default' as const,
      packageType: 'all' as const,
      viewMode: 'volume' as const,
      axes: {
        forward: grid.data.axes.forward,
        tenor: grid.data.axes.structure, // map structure axis -> tenor axis
      },
      cells: grid.data.cells,
      totals: grid.data.totals,
    }
  }, [grid.data])

  // Map cell clicks to structure CellId
  const handleCellClick = useCallback(
    (id: { fwd: string; tenor: string }) => {
      onCellClick({
        kind: 'structure',
        fwd: id.fwd,
        structure: id.tenor,
        structureType,
      }, {
        viewLabel: structureType === 'curve' ? 'Curves' : 'Flies',
      })
    },
    [onCellClick, structureType],
  )

  return (
    <div className="px-3 pb-3">
      <div className="flex flex-wrap items-center gap-2 pb-2">
        <Toggle
          options={COLOR_MODE_IDS.map((id) => ({
            id,
            label: COLOR_MODE_LABELS[id],
          }))}
          value={colorMode}
          onChange={setColorMode}
        />
        <Select
          aria-label="View mode"
          value={viewMode}
          onChange={(v) => setViewMode(v as VolumeGridViewMode)}
          options={VIEW_MODE_IDS.map((id) => ({
            id,
            label: `View: ${VIEW_MODE_LABELS[id]}`,
          }))}
        />
      </div>
      {gridData ? (
        <VolumeGrid
          data={gridData}
          metric={metric}
          period={period}
          viewMode={viewMode}
          colorMode={colorMode}
          uppercaseLabels={false}
          onCellClick={handleCellClick}
        />
      ) : (
        <SkeletonGrid />
      )}
    </div>
  )
}

// ─── Local helper components ────────────────────────────────────────────────

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

interface SelectOption {
  id: string
  label: string
}

function Select(props: {
  'aria-label': string
  value: string
  onChange: (v: string) => void
  options: ReadonlyArray<SelectOption>
}): JSX.Element {
  return (
    <select
      aria-label={props['aria-label']}
      value={props.value}
      onChange={(e) => props.onChange(e.target.value)}
      className="rounded border border-slate-700 bg-slate-900 px-2 py-[2px] font-mono text-[10.5px] text-slate-200 hover:bg-slate-800"
    >
      {props.options.map((o) => (
        <option key={o.id} value={o.id}>
          {o.label}
        </option>
      ))}
    </select>
  )
}

function SkeletonGrid(): JSX.Element {
  return (
    <div className="grid h-32 animate-pulse grid-cols-12 gap-px">
      {Array.from({ length: 12 * 8 }).map((_, i) => (
        <div key={i} className="rounded-sm bg-slate-800/40" />
      ))}
    </div>
  )
}
