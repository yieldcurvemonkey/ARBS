'use client'
// ABOUTME: Extracted grid-rendering view from VolumeGridCard. Manages its
// own view-specific state (forwardSchema, tenorSchema, packageType, viewMode,
// colorMode, bucket overrides) and delegates shared state (metric, period,
// lookbackDays, textFilter) from props. Renders controls + the VolumeGrid.

import type { JSX } from 'react'
import { useCallback, useMemo, useState } from 'react'
import { VolumeGrid } from '../VolumeGrid'
import { BucketOverridesPopover } from '../BucketOverridesPopover'
import { useVolumeGrid } from '../../../hooks/useVolumeGrid'
import { useVolumeGridCellPrefetch } from '../../../hooks/useVolumeGridCellPrefetch'
import type {
  VolumeGridColorMode,
  VolumeGridViewMode,
  VolumeMetric,
  VolumePeriod,
} from '../../../types/volume-grid.types'
import type { BucketOverrides, CellId, CellContext } from '../../../types/volume-grid-views.types'
import {
  FORWARD_SCHEMA_IDS,
  PACKAGE_TYPE_GROUP_IDS,
  PACKAGE_TYPE_GROUP_LABELS,
  TENOR_SCHEMA_IDS,
  type ForwardSchemaId,
  type PackageTypeGroupId,
  type TenorSchemaId,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

// ─── Labels ──────────────────────────────────────────────────────────────────

const FORWARD_SCHEMA_LABELS: Record<ForwardSchemaId, string> = {
  default: 'Default',
  legacy: 'Legacy',
  imm16: 'IMM 16',
  fomc: 'FOMC',
  custom: 'Custom',
}
const TENOR_SCHEMA_LABELS: Record<TenorSchemaId, string> = {
  default: 'Default',
  legacy: 'Legacy',
  venue: 'Venue',
  custom: 'Custom',
}

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

// ─── Props ───────────────────────────────────────────────────────────────────

export interface DefaultGridViewProps {
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  textFilter: string
  onCellClick: (cell: CellId, context?: CellContext) => void
}

// ─── Component ───────────────────────────────────────────────────────────────

export function DefaultGridView({
  metric,
  period,
  lookbackDays,
  textFilter,
  onCellClick,
}: DefaultGridViewProps): JSX.Element {
  // View-specific state
  const [forwardSchema, setForwardSchema] = useState<ForwardSchemaId>('default')
  const [tenorSchema, setTenorSchema] = useState<TenorSchemaId>('default')
  const [packageType, setPackageType] = useState<PackageTypeGroupId>('all')
  const [viewMode, setViewMode] = useState<VolumeGridViewMode>('volume')
  const [colorMode, setColorMode] = useState<VolumeGridColorMode>('activity')
  const [overrides, setOverrides] = useState<BucketOverrides>({ hidden: [], merged: [] })

  // Data fetching
  const grid = useVolumeGrid({
    metric,
    period,
    lookbackDays,
    forwardSchema,
    tenorSchema,
    packageType,
    viewMode,
    textFilter,
    collapsed: false,
  })

  const cellPrefetch = useVolumeGridCellPrefetch({
    metric,
    forwardSchema,
    tenorSchema,
    packageType,
  })

  // Apply bucket overrides — filter hidden buckets from data before rendering
  const filteredData = useMemo(() => {
    if (!grid.data || overrides.hidden.length === 0) return grid.data
    return {
      ...grid.data,
      axes: {
        forward: {
          ...grid.data.axes.forward,
          buckets: grid.data.axes.forward.buckets.filter((b) => !overrides.hidden.includes(b.id)),
        },
        tenor: {
          ...grid.data.axes.tenor,
          buckets: grid.data.axes.tenor.buckets.filter((b) => !overrides.hidden.includes(b.id)),
        },
      },
      cells: grid.data.cells.filter(
        (c) => !overrides.hidden.includes(c.fwd) && !overrides.hidden.includes(c.tenor),
      ),
    }
  }, [grid.data, overrides.hidden])

  // Convert cell clicks to CellId format with view context
  const handleCellClick = useCallback(
    (id: { fwd: string; tenor: string }) => {
      onCellClick({ kind: 'matrix', fwd: id.fwd, tenor: id.tenor }, {
        packageType,
        forwardSchema,
        tenorSchema,
      })
    },
    [onCellClick, packageType, forwardSchema, tenorSchema],
  )

  // Collect all buckets for the overrides popover
  const allBuckets = useMemo(() => {
    if (!grid.data) return []
    return [
      ...grid.data.axes.forward.buckets,
      ...grid.data.axes.tenor.buckets,
    ]
  }, [grid.data])

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
          aria-label="Package type"
          value={packageType}
          onChange={(v) => setPackageType(v as PackageTypeGroupId)}
          options={PACKAGE_TYPE_GROUP_IDS.map((id) => ({
            id,
            label: PACKAGE_TYPE_GROUP_LABELS[id],
          }))}
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
        <Select
          aria-label="Forward schema"
          value={forwardSchema}
          onChange={(v) => setForwardSchema(v as ForwardSchemaId)}
          options={FORWARD_SCHEMA_IDS.map((id) => ({
            id,
            label: `Fwd: ${FORWARD_SCHEMA_LABELS[id]}`,
          }))}
        />
        <Select
          aria-label="Tenor schema"
          value={tenorSchema}
          onChange={(v) => setTenorSchema(v as TenorSchemaId)}
          options={TENOR_SCHEMA_IDS.map((id) => ({
            id,
            label: `Tenor: ${TENOR_SCHEMA_LABELS[id]}`,
          }))}
        />
        <BucketOverridesPopover
          buckets={allBuckets}
          overrides={overrides}
          onChange={setOverrides}
        />
      </div>
      {filteredData ? (
        <VolumeGrid
          data={filteredData}
          metric={metric}
          period={period}
          viewMode={viewMode}
          colorMode={colorMode}
          packageType={packageType}
          onCellClick={handleCellClick}
          onCellHover={cellPrefetch.onCellHover}
          onCellLeave={cellPrefetch.onCellLeave}
        />
      ) : (
        <SkeletonGrid />
      )}
    </div>
  )
}

// ─── Local helper components ─────────────────────────────────────────────────

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
