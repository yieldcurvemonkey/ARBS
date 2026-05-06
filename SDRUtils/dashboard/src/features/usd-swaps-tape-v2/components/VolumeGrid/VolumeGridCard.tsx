'use client'
// ABOUTME: Collapsible top-of-page card hosting the volume-grid heatmap.
// Owns metric/period/schema/packageType state with localStorage
// persistence; opens the cell drill-down modal on click.

import type { JSX } from 'react'
import { useCallback, useEffect, useState } from 'react'
import { VolumeGrid } from './VolumeGrid'
import { VolumeGridCellModal } from './VolumeGridCellModal'
import { useVolumeGrid } from '../../hooks/useVolumeGrid'
import type {
  VolumeGridColorMode,
  VolumeGridViewMode,
  VolumeMetric, VolumePeriod,
  VolumeGridCell as Cell,
} from '../../types/volume-grid.types'
import {
  FORWARD_SCHEMA_IDS,
  PACKAGE_TYPE_GROUP_IDS,
  PACKAGE_TYPE_GROUP_LABELS,
  TENOR_SCHEMA_IDS,
  type ForwardSchemaId,
  type PackageTypeGroupId,
  type TenorSchemaId,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

const KEY_COLLAPSED = 'usd-tape-v2:volume-grid:collapsed'
const KEY_METRIC    = 'usd-tape-v2:volume-grid:metric'
const KEY_PERIOD    = 'usd-tape-v2:volume-grid:period'
const KEY_LOOKBACK  = 'usd-tape-v2:volume-grid:lookback'
const KEY_FWD_SCHEMA  = 'usd-tape-v2:volume-grid:forward-schema'
const KEY_TENOR_SCHEMA = 'usd-tape-v2:volume-grid:tenor-schema'
const KEY_PACKAGE_TYPE = 'usd-tape-v2:volume-grid:package-type'
const KEY_VIEW_MODE = 'usd-tape-v2:volume-grid:view-mode'
const KEY_COLOR_MODE = 'usd-tape-v2:volume-grid:color-mode'
const KEY_DEFAULTS_VERSION = 'usd-tape-v2:volume-grid:defaults-version'
const DEFAULTS_VERSION = 'open-dv01-1w-v1'
const DEFAULT_COLLAPSED = false
const DEFAULT_METRIC: VolumeMetric = 'dv01'
const DEFAULT_PERIOD: VolumePeriod = '1w'

// Lookback (baseline-history length) controls how many prior days /
// rolling windows the percentile rank is drawn from. Decoupled from
// Period (the current measurement window) so the trader can ask
// "today's run-rate vs the last week / month / quarter" independently
// of which period unit the cells display.
type LookbackId = '1w' | '2w' | '3w' | '1m' | '3m' | '6m' | '1y' | '2y'
const LOOKBACK_IDS: ReadonlyArray<LookbackId> = ['1w', '2w', '3w', '1m', '3m', '6m', '1y', '2y']
const LOOKBACK_DAYS: Record<LookbackId, number> = {
  '1w': 7,
  '2w': 14,
  '3w': 21,
  '1m': 30,
  '3m': 90,
  '6m': 180,
  '1y': 365,
  '2y': 730,
}
// Lowercase to match the Window toggle (today / 1h / 24h / 1w / ...)
// — both rows now read as the same family of compact units.
const LOOKBACK_LABELS: Record<LookbackId, string> = {
  '1w': '1w',
  '2w': '2w',
  '3w': '3w',
  '1m': '1m',
  '3m': '3m',
  '6m': '6m',
  '1y': '1y',
  '2y': '2y',
}
const DEFAULT_LOOKBACK: LookbackId = '3m'

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

const FORWARD_SCHEMA_LABELS: Record<ForwardSchemaId, string> = {
  default: 'Default',
  legacy: 'Legacy',
  imm16: 'IMM 16',
  fomc: 'FOMC',
}
const TENOR_SCHEMA_LABELS: Record<TenorSchemaId, string> = {
  default: 'Default',
  legacy: 'Legacy',
  venue: 'Venue',
}

function readBool(key: string, fallback: boolean): boolean {
  if (typeof window === 'undefined') return fallback
  const v = window.localStorage.getItem(key)
  return v == null ? fallback : v === 'true'
}
function readEnum<T extends string>(key: string, allowed: ReadonlyArray<T>, fallback: T): T {
  if (typeof window === 'undefined') return fallback
  const v = window.localStorage.getItem(key)
  return (allowed as ReadonlyArray<string>).includes(v ?? '') ? (v as T) : fallback
}
function shouldApplyCurrentDefaults(): boolean {
  if (typeof window === 'undefined') return true
  return window.localStorage.getItem(KEY_DEFAULTS_VERSION) !== DEFAULTS_VERSION
}

export interface VolumeGridCardProps {
  onSelectPackage: (packageId: string) => void
}

export function VolumeGridCard({ onSelectPackage }: VolumeGridCardProps): JSX.Element {
  const [collapsed, setCollapsed] = useState<boolean>(() =>
    shouldApplyCurrentDefaults() ? DEFAULT_COLLAPSED : readBool(KEY_COLLAPSED, DEFAULT_COLLAPSED),
  )
  const [metric, setMetric] = useState<VolumeMetric>(() =>
    shouldApplyCurrentDefaults()
      ? DEFAULT_METRIC
      : readEnum<VolumeMetric>(KEY_METRIC, ['notional', 'dv01'], DEFAULT_METRIC),
  )
  const [period, setPeriod] = useState<VolumePeriod>(() =>
    shouldApplyCurrentDefaults()
      ? DEFAULT_PERIOD
      : readEnum<VolumePeriod>(
          KEY_PERIOD,
          ['today', '1h', '24h', '1w', '2w', '3w', '1m', '3m'],
          DEFAULT_PERIOD,
        ),
  )
  const [lookback, setLookback] = useState<LookbackId>(() =>
    readEnum<LookbackId>(KEY_LOOKBACK, LOOKBACK_IDS, DEFAULT_LOOKBACK),
  )
  const [forwardSchema, setForwardSchema] = useState<ForwardSchemaId>(() =>
    readEnum<ForwardSchemaId>(KEY_FWD_SCHEMA, FORWARD_SCHEMA_IDS, 'default'),
  )
  const [tenorSchema, setTenorSchema] = useState<TenorSchemaId>(() =>
    readEnum<TenorSchemaId>(KEY_TENOR_SCHEMA, TENOR_SCHEMA_IDS, 'default'),
  )
  const [packageType, setPackageType] = useState<PackageTypeGroupId>(() =>
    readEnum<PackageTypeGroupId>(KEY_PACKAGE_TYPE, PACKAGE_TYPE_GROUP_IDS, 'outright'),
  )
  const [viewMode, setViewMode] = useState<VolumeGridViewMode>(() =>
    readEnum<VolumeGridViewMode>(KEY_VIEW_MODE, VIEW_MODE_IDS, 'volume'),
  )
  const [colorMode, setColorMode] = useState<VolumeGridColorMode>(() =>
    readEnum<VolumeGridColorMode>(KEY_COLOR_MODE, COLOR_MODE_IDS, 'activity'),
  )
  const [selectedCell, setSelectedCell] = useState<{ fwd: string; tenor: string } | null>(null)

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(KEY_COLLAPSED, String(collapsed))
  }, [collapsed])
  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(KEY_DEFAULTS_VERSION, DEFAULTS_VERSION)
  }, [])
  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(KEY_METRIC, metric)
  }, [metric])
  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(KEY_PERIOD, period)
  }, [period])
  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(KEY_LOOKBACK, lookback)
  }, [lookback])
  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(KEY_FWD_SCHEMA, forwardSchema)
  }, [forwardSchema])
  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(KEY_TENOR_SCHEMA, tenorSchema)
  }, [tenorSchema])
  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(KEY_PACKAGE_TYPE, packageType)
  }, [packageType])
  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(KEY_VIEW_MODE, viewMode)
  }, [viewMode])
  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(KEY_COLOR_MODE, colorMode)
  }, [colorMode])

  const grid = useVolumeGrid({
    metric, period, collapsed,
    lookbackDays: LOOKBACK_DAYS[lookback],
    forwardSchema, tenorSchema, packageType, viewMode,
  })

  const onCellClick = useCallback((id: { fwd: string; tenor: string }) => {
    setSelectedCell(id)
  }, [])

  const asOf = grid.data?.asOf
    ? new Date(grid.data.asOf).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', timeZone: 'America/New_York' })
    : null

  return (
    <section
      data-testid="volume-grid-card"
      className="border-b border-slate-800 bg-slate-900/40 ring-1 ring-slate-800"
    >
      <header className="flex flex-wrap items-center gap-2 px-3 py-1.5 text-slate-300">
        <button
          type="button"
          aria-label="Toggle volume grid"
          onClick={() => setCollapsed((v) => !v)}
          className="rounded border border-slate-700 px-2 py-[2px] font-mono text-[10.5px] hover:bg-slate-800"
        >
          {collapsed ? '▲ Volume Grid' : '▼ Volume Grid'}
        </button>
        <Toggle
          options={[{ id: 'notional', label: 'Notional' }, { id: 'dv01', label: 'DV01' }]}
          value={metric}
          onChange={setMetric}
        />
        <span className="font-mono text-[9.5px] uppercase tracking-wider text-slate-500" title="Window the cell value is summed over (current measurement window).">
          window
        </span>
        <Toggle
          options={[
            { id: 'today', label: 'Today' },
            { id: '1h', label: '1h' },
            { id: '24h', label: '24h' },
            { id: '1w', label: '1w' },
            { id: '2w', label: '2w' },
            { id: '3w', label: '3w' },
            { id: '1m', label: '1m' },
            { id: '3m', label: '3m' },
          ]}
          value={period}
          onChange={setPeriod}
        />
        <span className="font-mono text-[9.5px] uppercase tracking-wider text-slate-500" title="Length of the prior history the percentile (heatmap colour) is drawn from.">
          baseline
        </span>
        <Toggle
          options={LOOKBACK_IDS.map((id) => ({ id, label: LOOKBACK_LABELS[id] }))}
          value={lookback}
          onChange={setLookback}
        />
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
        {asOf && (
          <span className="ml-1 rounded bg-slate-800/60 px-1.5 py-[1px] font-mono text-[9.5px] text-slate-400">
            as-of {asOf} ET
          </span>
        )}
        <button
          type="button"
          onClick={() => grid.refresh()}
          aria-label="Refresh"
          className="ml-auto rounded border border-slate-700 px-2 py-[2px] font-mono text-[10.5px] hover:bg-slate-800"
          disabled={grid.isLoading}
        >
          ⟳
        </button>
        {grid.error && (
          <span className="rounded bg-rose-500/15 px-1.5 py-[1px] font-mono text-[9.5px] text-rose-200 ring-1 ring-rose-500/30">
            {grid.error.message}
          </span>
        )}
      </header>
      {!collapsed && (
        <div
          data-testid="volume-grid-tagline"
          className="px-3 pb-1.5 font-mono text-[10px] text-slate-500"
          title={taglineTitle(period, lookback)}
        >
          {taglineText(period, lookback)}
        </div>
      )}
      {!collapsed && (
        <div className="px-3 pb-3" data-testid="volume-grid">
          {grid.data ? (
            <VolumeGrid
              data={grid.data}
              metric={metric}
              period={period}
              viewMode={viewMode}
              colorMode={colorMode}
              onCellClick={onCellClick}
            />
          ) : (
            <SkeletonGrid />
          )}
        </div>
      )}
      <VolumeGridCellModal
        cell={selectedCell}
        metric={metric}
        forwardSchema={forwardSchema}
        tenorSchema={tenorSchema}
        packageType={packageType}
        forwardAxis={grid.data?.axes.forward}
        tenorAxis={grid.data?.axes.tenor}
        onClose={() => setSelectedCell(null)}
        onSelectPackage={onSelectPackage}
      />
    </section>
  )
}

function Toggle<T extends string>({
  options, value, onChange,
}: { options: ReadonlyArray<{ id: T; label: string }>; value: T; onChange: (v: T) => void }): JSX.Element {
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
        <option key={o.id} value={o.id}>{o.label}</option>
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

// Period framing — the cell value is summed over the "current
// window"; the percentile (heatmap colour) ranks that value against
// a "baseline" drawn from the configured lookback. Periods split
// into two semantic families:
//   - time_of_day (today / 1h): cell = today's open→now (or last
//     hour) cumulative; baseline = same time-of-day on each prior
//     trading day in the lookback.
//   - rolling (24h / 1w / 2w / 3w / 1m / 3m): cell = trailing N-day
//     sum; baseline = prior non-overlapping N-day windows shifted
//     backward across the lookback.
function periodFamily(period: VolumePeriod): 'time_of_day' | 'rolling' {
  return period === 'today' || period === '1h' ? 'time_of_day' : 'rolling'
}

function currentWindowLabel(period: VolumePeriod): string {
  switch (period) {
    case 'today': return "today's intraday (open → as-of)"
    case '1h':    return 'last 1 hour'
    case '24h':   return 'trailing 24h'
    case '1w':    return 'trailing 1-week'
    case '2w':    return 'trailing 2-week'
    case '3w':    return 'trailing 3-week'
    case '1m':    return 'trailing 1-month'
    case '3m':    return 'trailing 3-month'
  }
}

function baselineWindowLabel(period: VolumePeriod, lookback: LookbackId): string {
  if (periodFamily(period) === 'time_of_day') {
    return `same time-of-day on prior ${LOOKBACK_LABELS[lookback]} of trading days`
  }
  return `prior non-overlapping ${currentWindowLabel(period).replace(/^trailing /, '')} windows over last ${LOOKBACK_LABELS[lookback]}`
}

function taglineText(period: VolumePeriod, lookback: LookbackId): string {
  return `intraday volume seasonality heatmap · cell = ${currentWindowLabel(period)}; colour = percentile vs ${baselineWindowLabel(period, lookback)}`
}

function taglineTitle(period: VolumePeriod, lookback: LookbackId): string {
  const fam = periodFamily(period)
  const cur = currentWindowLabel(period)
  const base = baselineWindowLabel(period, lookback)
  if (fam === 'time_of_day') {
    return `Each cell sums ${cur} for that (forward × tenor) bucket. The colour ranks that cumulative volume against the same point in the trading session on prior ${LOOKBACK_LABELS[lookback]} of days, so red = busier than usual at this time of day, blue = quieter.`
  }
  return `Each cell sums ${cur} for that (forward × tenor) bucket. The colour ranks that against ${base}, so red = busier than the typical trailing ${currentWindowLabel(period).replace(/^trailing /, '')} window, blue = quieter.`
}
