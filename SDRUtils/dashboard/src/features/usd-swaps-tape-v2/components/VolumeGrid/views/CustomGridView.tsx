'use client'
// ABOUTME: Custom schema view for the volume grid. Lets users define their own
// forward and tenor bucket axes via the CustomSchemaBuilderModal, persists
// schemas + active index in localStorage, and renders the grid via useVolumeGrid
// with forwardSchema='custom' / tenorSchema='custom' plus custom bucket arrays.

import type { JSX } from 'react'
import { useCallback, useMemo, useState } from 'react'
import { VolumeGrid } from '../VolumeGrid'
import { useVolumeGrid } from '../../../hooks/useVolumeGrid'
import { useVolumeGridCellPrefetch } from '../../../hooks/useVolumeGridCellPrefetch'
import { CustomSchemaBuilderModal } from '../CustomSchemaBuilderModal'
import type { CustomSchema } from '../CustomSchemaBuilderModal'
import type {
  VolumeGridColorMode,
  VolumeGridViewMode,
  VolumeMetric,
  VolumePeriod,
} from '../../../types/volume-grid.types'
import type { CellId } from '../../../types/volume-grid-views.types'

// ---- localStorage helpers ---------------------------------------------------

const LS_SCHEMAS = 'usd-tape-v2:volume-grid:custom-schemas'
const LS_ACTIVE = 'usd-tape-v2:volume-grid:custom-active'

function loadSchemas(): CustomSchema[] {
  try { return JSON.parse(window.localStorage.getItem(LS_SCHEMAS) ?? '[]') }
  catch { return [] }
}

function loadActiveIndex(): number | null {
  const raw = window.localStorage.getItem(LS_ACTIVE)
  return raw != null ? Number(raw) : null
}

function saveSchemas(schemas: CustomSchema[]) {
  window.localStorage.setItem(LS_SCHEMAS, JSON.stringify(schemas))
}

function saveActiveIndex(idx: number | null) {
  if (idx == null) window.localStorage.removeItem(LS_ACTIVE)
  else window.localStorage.setItem(LS_ACTIVE, String(idx))
}

// ---- Labels -----------------------------------------------------------------

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

// ---- Props ------------------------------------------------------------------

export interface CustomGridViewProps {
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  textFilter: string
  onCellClick: (cell: CellId) => void
}

// ---- Component --------------------------------------------------------------

export function CustomGridView({
  metric,
  period,
  lookbackDays,
  textFilter,
  onCellClick,
}: CustomGridViewProps): JSX.Element {
  const [schemas, setSchemas] = useState<CustomSchema[]>(() => loadSchemas())
  const [activeIdx, setActiveIdx] = useState<number | null>(() => loadActiveIndex())
  const [modalOpen, setModalOpen] = useState(false)
  const [editIdx, setEditIdx] = useState<number | null>(null)
  const [viewMode, setViewMode] = useState<VolumeGridViewMode>('volume')
  const [colorMode, setColorMode] = useState<VolumeGridColorMode>('activity')

  const activeSchema = activeIdx != null && activeIdx < schemas.length
    ? schemas[activeIdx]
    : null

  // Data fetching — only when we have an active schema
  const grid = useVolumeGrid({
    metric,
    period,
    lookbackDays,
    forwardSchema: 'custom',
    tenorSchema: 'custom',
    packageType: activeSchema?.packageType ?? 'all',
    viewMode,
    textFilter,
    collapsed: activeSchema == null,
    customForwardBuckets: activeSchema?.forwardBuckets,
    customTenorBuckets: activeSchema?.tenorBuckets,
  })

  const cellPrefetch = useVolumeGridCellPrefetch({
    metric,
    forwardSchema: 'custom',
    tenorSchema: 'custom',
    packageType: activeSchema?.packageType ?? 'all',
  })

  // Cell click handler
  const handleCellClick = useCallback(
    (id: { fwd: string; tenor: string }) => {
      onCellClick({ kind: 'matrix', fwd: id.fwd, tenor: id.tenor })
    },
    [onCellClick],
  )

  // Modal callbacks
  const handleOpenNew = useCallback(() => {
    setEditIdx(null)
    setModalOpen(true)
  }, [])

  const handleOpenEdit = useCallback((idx: number) => {
    setEditIdx(idx)
    setModalOpen(true)
  }, [])

  const handleApply = useCallback((schema: CustomSchema) => {
    let next: CustomSchema[]
    let newActiveIdx: number
    if (editIdx != null && editIdx < schemas.length) {
      // Editing existing schema
      next = schemas.map((s, i) => (i === editIdx ? schema : s))
      newActiveIdx = editIdx
    } else {
      // Adding new schema
      next = [...schemas, schema]
      newActiveIdx = next.length - 1
    }
    setSchemas(next)
    setActiveIdx(newActiveIdx)
    saveSchemas(next)
    saveActiveIndex(newActiveIdx)
    setModalOpen(false)
  }, [schemas, editIdx])

  const handleDelete = useCallback((idx: number) => {
    const next = schemas.filter((_, i) => i !== idx)
    setSchemas(next)
    saveSchemas(next)
    // Fix active index
    if (activeIdx === idx) {
      const newIdx = next.length > 0 ? Math.min(idx, next.length - 1) : null
      setActiveIdx(newIdx)
      saveActiveIndex(newIdx)
    } else if (activeIdx != null && activeIdx > idx) {
      setActiveIdx(activeIdx - 1)
      saveActiveIndex(activeIdx - 1)
    }
  }, [schemas, activeIdx])

  const handleSelectSchema = useCallback((idx: number) => {
    setActiveIdx(idx)
    saveActiveIndex(idx)
  }, [])

  // Initial schema for the modal editor
  const modalInitialSchema = useMemo<CustomSchema | undefined>(() => {
    if (editIdx != null && editIdx < schemas.length) return schemas[editIdx]
    return undefined
  }, [editIdx, schemas])

  // ---- Render ---------------------------------------------------------------

  // Empty state: no active schema
  if (activeSchema == null) {
    return (
      <div className="px-3 pb-3">
        {/* Schema list (if any exist but none active) */}
        {schemas.length > 0 && (
          <SchemaList
            schemas={schemas}
            activeIdx={activeIdx}
            onSelect={handleSelectSchema}
            onEdit={handleOpenEdit}
            onDelete={handleDelete}
          />
        )}
        <div className="flex h-48 flex-col items-center justify-center gap-3 rounded border border-dashed border-slate-700 text-slate-400">
          <div className="font-mono text-[11px]">
            {schemas.length > 0
              ? 'Select a schema above or create a new one.'
              : 'No custom schemas configured.'}
          </div>
          <button
            type="button"
            onClick={handleOpenNew}
            className="rounded border border-indigo-500/40 bg-indigo-500/25 px-3 py-[3px] font-mono text-[10.5px] text-indigo-100 hover:bg-indigo-500/35"
          >
            Configure Custom Schema
          </button>
        </div>
        <CustomSchemaBuilderModal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          onApply={handleApply}
          initialSchema={modalInitialSchema}
        />
      </div>
    )
  }

  // Active schema: show controls + grid
  return (
    <div className="px-3 pb-3">
      {/* Schema selector row */}
      <SchemaList
        schemas={schemas}
        activeIdx={activeIdx}
        onSelect={handleSelectSchema}
        onEdit={handleOpenEdit}
        onDelete={handleDelete}
      />

      {/* Controls row */}
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
        <button
          type="button"
          onClick={() => handleOpenEdit(activeIdx!)}
          className="rounded border border-slate-700 px-2 py-[1px] font-mono text-[10.5px] text-slate-400 hover:bg-slate-800 hover:text-slate-200"
          title="Edit schema"
        >
          gear
        </button>
        <button
          type="button"
          onClick={handleOpenNew}
          className="rounded border border-slate-700 px-2 py-[1px] font-mono text-[10.5px] text-slate-400 hover:bg-slate-800 hover:text-slate-200"
        >
          + New
        </button>
      </div>

      {/* Grid */}
      {grid.data ? (
        <VolumeGrid
          data={grid.data}
          metric={metric}
          period={period}
          viewMode={viewMode}
          colorMode={colorMode}
          packageType={activeSchema.packageType}
          onCellClick={handleCellClick}
          onCellHover={cellPrefetch.onCellHover}
          onCellLeave={cellPrefetch.onCellLeave}
        />
      ) : (
        <SkeletonGrid />
      )}

      <CustomSchemaBuilderModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onApply={handleApply}
        initialSchema={modalInitialSchema}
      />
    </div>
  )
}

// ---- SchemaList sub-component -----------------------------------------------

function SchemaList({
  schemas,
  activeIdx,
  onSelect,
  onEdit,
  onDelete,
}: {
  schemas: CustomSchema[]
  activeIdx: number | null
  onSelect: (idx: number) => void
  onEdit: (idx: number) => void
  onDelete: (idx: number) => void
}): JSX.Element {
  return (
    <div className="mb-2 flex flex-wrap items-center gap-1">
      {schemas.map((s, i) => (
        <div key={i} className="flex items-center gap-0.5">
          <button
            type="button"
            onClick={() => onSelect(i)}
            className={`rounded-l border border-slate-700 px-2 py-[1px] font-mono text-[10.5px] ${
              i === activeIdx
                ? 'bg-indigo-500/25 text-indigo-100'
                : 'text-slate-300 hover:bg-slate-800'
            }`}
          >
            {s.name || `Schema ${i + 1}`}
          </button>
          <button
            type="button"
            onClick={() => onEdit(i)}
            className="border-y border-slate-700 px-1 py-[1px] font-mono text-[9px] text-slate-500 hover:text-slate-200"
            title="Edit"
          >
            e
          </button>
          <button
            type="button"
            onClick={() => onDelete(i)}
            className="rounded-r border border-slate-700 px-1 py-[1px] font-mono text-[9px] text-rose-500 hover:text-rose-300"
            title="Delete"
          >
            x
          </button>
        </div>
      ))}
    </div>
  )
}

// ---- Local helper components (same pattern as DefaultGridView) --------------

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
