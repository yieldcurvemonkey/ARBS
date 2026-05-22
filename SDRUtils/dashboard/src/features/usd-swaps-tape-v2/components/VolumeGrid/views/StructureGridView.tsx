'use client'
// ABOUTME: Shared component for Curve Strip and Fly Curve views. Fetches
// from /volume-grid/structure and renders the existing VolumeGrid with
// forward-start rows x structure columns.

import type { JSX } from 'react'
import { useCallback, useMemo, useRef, useState } from 'react'
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
import type { CellId, CellContext } from '../../../types/volume-grid-views.types'

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
  onCellClick: (cell: CellId, context?: CellContext) => void
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
  const [viewMode, setViewMode] = useState<VolumeGridViewMode>('volume')
  const [colorMode, setColorMode] = useState<VolumeGridColorMode>('activity')
  const [hiddenColumns, setHiddenColumns] = useState<Set<string>>(new Set())
  const [colPickerOpen, setColPickerOpen] = useState(false)

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
        <ColumnPicker
          columns={gridData?.axes.tenor.buckets ?? []}
          hidden={hiddenColumns}
          onChange={setHiddenColumns}
          open={colPickerOpen}
          onToggle={() => setColPickerOpen(v => !v)}
        />
        {hiddenColumns.size > 0 && (
          <button type="button" onClick={() => setHiddenColumns(new Set())}
            className="font-mono text-[9px] text-slate-500 hover:text-slate-300">
            show all ({hiddenColumns.size} hidden)
          </button>
        )}
      </div>
      {gridData ? (
        <VolumeGrid
          data={gridData}
          metric={metric}
          period={period}
          viewMode={viewMode}
          colorMode={colorMode}
          uppercaseLabels={false}
          hiddenColumns={hiddenColumns}
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

function ColumnPicker({ columns, hidden, onChange, open, onToggle }: {
  columns: ReadonlyArray<{ id: string; label: string }>
  hidden: Set<string>
  onChange: (h: Set<string>) => void
  open: boolean
  onToggle: () => void
}): JSX.Element {
  const ref = useRef<HTMLDivElement>(null)
  const toggle = (id: string) => {
    const next = new Set(hidden)
    if (next.has(id)) next.delete(id); else next.add(id)
    onChange(next)
  }
  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={onToggle}
        className="rounded border border-slate-700 px-2 py-[1px] font-mono text-[10.5px] text-slate-400 hover:bg-slate-800 hover:text-slate-200">
        Columns
      </button>
      {open && (
        <div className="absolute left-0 top-full z-30 mt-1 max-h-64 w-48 overflow-y-auto rounded border border-slate-700 bg-slate-900 p-1.5 shadow-xl">
          <div className="mb-1 flex items-center justify-between">
            <span className="font-mono text-[9px] uppercase tracking-wider text-slate-500">Show/Hide</span>
            <button type="button" onClick={() => onChange(new Set())}
              className="font-mono text-[9px] text-slate-500 hover:text-slate-300">Reset</button>
          </div>
          {columns.map(c => (
            <label key={c.id} className="flex cursor-pointer items-center gap-1.5 rounded px-1 py-[1px] hover:bg-slate-800">
              <input type="checkbox" checked={!hidden.has(c.id)} onChange={() => toggle(c.id)}
                className="h-3 w-3 rounded border-slate-600 bg-slate-800 accent-indigo-500" />
              <span className="font-mono text-[10px] text-slate-300">{c.label}</span>
            </label>
          ))}
        </div>
      )}
    </div>
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
