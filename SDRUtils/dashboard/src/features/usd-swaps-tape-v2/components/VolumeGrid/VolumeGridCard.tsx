'use client'
// ABOUTME: Thin shell card managing collapse, active-view selection,
// shared metric/period/lookback/textFilter state, and cell modal.
// Delegates grid rendering to the active view via VolumeGridViewSwitcher.

import type { JSX } from 'react'
import { useCallback, useEffect, useState } from 'react'
import { VolumeGridViewSwitcher } from './VolumeGridViewSwitcher'
import { VolumeGridCellModal } from './VolumeGridCellModal'
import { TextFilterInput } from './TextFilterInput'
import { useIsMobile } from '@/lib/hooks/useIsMobile'
import type { CellId } from '../../types/volume-grid-views.types'
import type { VolumeMetric, VolumePeriod } from '../../types/volume-grid.types'

const KEY_COLLAPSED = 'usd-tape-v2:volume-grid:collapsed'
const KEY_METRIC = 'usd-tape-v2:volume-grid:metric'
const KEY_PERIOD = 'usd-tape-v2:volume-grid:period'
const KEY_LOOKBACK = 'usd-tape-v2:volume-grid:lookback'
const KEY_VIEW = 'usd-tape-v2:volume-grid:active-view'
const KEY_DEFAULTS_VERSION = 'usd-tape-v2:volume-grid:defaults-version'
const DEFAULTS_VERSION = 'all-today-1m-v3'  // bump version to reset to new defaults

type LookbackId = '1w' | '2w' | '3w' | '1m' | '3m' | '6m' | '1y' | '2y'
const LOOKBACK_IDS: ReadonlyArray<LookbackId> = ['1w', '2w', '3w', '1m', '3m', '6m', '1y', '2y']
const LOOKBACK_DAYS: Record<LookbackId, number> = {
  '1w': 7, '2w': 14, '3w': 21, '1m': 30, '3m': 90, '6m': 180, '1y': 365, '2y': 730,
}

export interface VolumeGridCardProps {
  onSelectPackage: (packageId: string) => void
}

export function VolumeGridCard({ onSelectPackage }: VolumeGridCardProps): JSX.Element {
  const [collapsed, setCollapsed] = useState(false)
  const [metric, setMetric] = useState<VolumeMetric>('dv01')
  const [period, setPeriod] = useState<VolumePeriod>('today')
  const [lookback, setLookback] = useState<LookbackId>('1m')
  const [activeView, setActiveView] = useState('default')
  const [textFilter, setTextFilter] = useState('')
  const [selectedCell, setSelectedCell] = useState<CellId | null>(null)
  const isMobile = useIsMobile()

  // Hydrate from localStorage
  const [hydrated, setHydrated] = useState(false)
  useEffect(() => {
    if (hydrated) return
    setHydrated(true)
    const shouldApplyDefaults = typeof window !== 'undefined'
      && window.localStorage.getItem(KEY_DEFAULTS_VERSION) !== DEFAULTS_VERSION
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(KEY_DEFAULTS_VERSION, DEFAULTS_VERSION)
    }
    if (!shouldApplyDefaults) {
      // Read stored values
      const storedCollapsed = window.localStorage.getItem(KEY_COLLAPSED)
      if (storedCollapsed != null) setCollapsed(storedCollapsed === 'true')
      const storedMetric = window.localStorage.getItem(KEY_METRIC)
      if (storedMetric === 'notional' || storedMetric === 'dv01') setMetric(storedMetric)
      const storedPeriod = window.localStorage.getItem(KEY_PERIOD)
      if (['today','1h','24h','1w','2w','3w','1m','3m'].includes(storedPeriod ?? '')) setPeriod(storedPeriod as VolumePeriod)
      const storedLookback = window.localStorage.getItem(KEY_LOOKBACK)
      if ((LOOKBACK_IDS as ReadonlyArray<string>).includes(storedLookback ?? '')) setLookback(storedLookback as LookbackId)
      const storedView = window.localStorage.getItem(KEY_VIEW)
      if (storedView === 'default' || storedView === 'fomc_strip') setActiveView(storedView)
    }
  }, [hydrated])

  // Persist to localStorage
  useEffect(() => {
    if (!hydrated) return
    window.localStorage.setItem(KEY_COLLAPSED, String(collapsed))
    window.localStorage.setItem(KEY_METRIC, metric)
    window.localStorage.setItem(KEY_PERIOD, period)
    window.localStorage.setItem(KEY_LOOKBACK, lookback)
    window.localStorage.setItem(KEY_VIEW, activeView)
  }, [hydrated, collapsed, metric, period, lookback, activeView])

  useEffect(() => {
    if (isMobile) setCollapsed(true)
  }, [isMobile])

  const onCellClick = useCallback((cell: CellId) => {
    setSelectedCell(cell)
  }, [])

  // Build cell prop for modal from CellId
  const modalCell = selectedCell
    ? selectedCell.kind === 'matrix'
      ? { fwd: selectedCell.fwd, tenor: selectedCell.tenor }
      : { fwd: selectedCell.fwd }
    : null

  const modalForwardSchema = selectedCell?.kind === 'collapsed_tenor' ? 'fomc' as const : 'default' as const

  return (
    <section data-testid="volume-grid-card" className="border-b border-slate-800 bg-slate-900/40 ring-1 ring-slate-800">
      <header className={`flex flex-wrap items-center px-3 text-slate-300 ${isMobile ? 'gap-3 py-3' : 'gap-2 py-1.5'}`}>
        <button type="button" aria-label="Toggle volume grid" onClick={() => setCollapsed((v) => !v)}
          className="rounded border border-slate-700 px-2 py-[2px] font-mono text-[10.5px] hover:bg-slate-800">
          {collapsed ? '▲ Volume Grid' : '▼ Volume Grid'}
        </button>
        <Toggle
          options={[{ id: 'notional' as const, label: 'Notional' }, { id: 'dv01' as const, label: 'DV01' }]}
          value={metric}
          onChange={setMetric}
        />
        <span className="font-mono text-[9.5px] uppercase tracking-wider text-slate-500">window</span>
        <Toggle
          options={[
            { id: 'today' as const, label: 'Today' },
            { id: '1h' as const, label: '1h' },
            { id: '24h' as const, label: '24h' },
            { id: '1w' as const, label: '1w' },
            { id: '2w' as const, label: '2w' },
            { id: '3w' as const, label: '3w' },
            { id: '1m' as const, label: '1m' },
            { id: '3m' as const, label: '3m' },
          ]}
          value={period}
          onChange={setPeriod}
        />
        <span className="font-mono text-[9.5px] uppercase tracking-wider text-slate-500">baseline</span>
        <Toggle
          options={LOOKBACK_IDS.map((id) => ({ id, label: id }))}
          value={lookback}
          onChange={setLookback}
        />
        <TextFilterInput value={textFilter} onChange={setTextFilter} />
        {textFilter && (
          <span className="rounded bg-amber-500/15 px-1.5 py-[1px] font-mono text-[9.5px] text-amber-200 ring-1 ring-amber-500/30">
            filtered
          </span>
        )}
      </header>
      {!collapsed && (
        <VolumeGridViewSwitcher
          activeViewId={activeView}
          onViewChange={setActiveView}
          metric={metric}
          period={period}
          lookbackDays={LOOKBACK_DAYS[lookback]}
          textFilter={textFilter}
          onCellClick={onCellClick}
        />
      )}
      <VolumeGridCellModal
        cell={modalCell}
        metric={metric}
        forwardSchema={modalForwardSchema}
        textFilter={textFilter || undefined}
        onClose={() => setSelectedCell(null)}
        onSelectPackage={onSelectPackage}
      />
    </section>
  )
}

// Keep the Toggle helper (same as before)
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
