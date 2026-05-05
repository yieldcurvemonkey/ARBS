'use client'
// ABOUTME: Collapsible top-of-page card hosting the volume-grid heatmap.
// Owns metric/period state with localStorage persistence; opens the cell
// drill-down modal on click (modal wired in a later task).

import type { JSX } from 'react'
import { useCallback, useEffect, useState } from 'react'
import { VolumeGrid } from './VolumeGrid'
import { VolumeGridCellModal } from './VolumeGridCellModal'
import { useVolumeGrid } from '../../hooks/useVolumeGrid'
import type {
  VolumeMetric, VolumePeriod,
  VolumeGridCell as Cell,
} from '../../types/volume-grid.types'

const KEY_COLLAPSED = 'usd-tape-v2:volume-grid:collapsed'
const KEY_METRIC    = 'usd-tape-v2:volume-grid:metric'
const KEY_PERIOD    = 'usd-tape-v2:volume-grid:period'

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

export interface VolumeGridCardProps {
  onSelectPackage: (packageId: string) => void
}

export function VolumeGridCard({ onSelectPackage }: VolumeGridCardProps): JSX.Element {
  const [collapsed, setCollapsed] = useState<boolean>(() => readBool(KEY_COLLAPSED, true))
  const [metric, setMetric] = useState<VolumeMetric>(() =>
    readEnum<VolumeMetric>(KEY_METRIC, ['notional', 'dv01'], 'notional'),
  )
  const [period, setPeriod] = useState<VolumePeriod>(() =>
    readEnum<VolumePeriod>(KEY_PERIOD, ['today', '1h', '24h', '1w'], 'today'),
  )
  const [selectedCell, setSelectedCell] = useState<{ fwd: Cell['fwd']; tenor: Cell['tenor'] } | null>(null)

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(KEY_COLLAPSED, String(collapsed))
  }, [collapsed])
  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(KEY_METRIC, metric)
  }, [metric])
  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(KEY_PERIOD, period)
  }, [period])

  const grid = useVolumeGrid({ metric, period, collapsed })

  const onCellClick = useCallback((id: { fwd: Cell['fwd']; tenor: Cell['tenor'] }) => {
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
      <header className="flex items-center gap-2 px-3 py-1.5 text-slate-300">
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
        <Toggle
          options={[
            { id: 'today', label: 'Today' },
            { id: '1h', label: '1h' },
            { id: '24h', label: '24h' },
            { id: '1w', label: '1w' },
          ]}
          value={period}
          onChange={setPeriod}
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
        <div className="px-3 pb-3" data-testid="volume-grid">
          {grid.data ? (
            <VolumeGrid
              data={grid.data}
              metric={metric}
              period={period}
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

function SkeletonGrid(): JSX.Element {
  return (
    <div className="grid h-32 animate-pulse grid-cols-12 gap-px">
      {Array.from({ length: 12 * 6 }).map((_, i) => (
        <div key={i} className="rounded-sm bg-slate-800/40" />
      ))}
    </div>
  )
}
