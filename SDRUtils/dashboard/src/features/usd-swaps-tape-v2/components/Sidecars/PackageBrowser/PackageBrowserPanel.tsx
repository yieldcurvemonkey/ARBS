'use client'
// ABOUTME: Sorted list of multi-leg packages; click filters main table by package_id.
import type { JSX } from 'react'
import { useState } from 'react'
import { usePackageBrowser } from '../../../hooks/usePackageBrowser'
import { formatDv01, formatNotional } from '../../../utils/format'

const SORT_OPTIONS = [
  { key: 'risk', label: 'DV01' },
  { key: 'notional', label: 'Notional' },
  { key: 'time', label: 'Time' },
  { key: 'legs', label: 'Legs' },
] as const

export interface PackageBrowserPanelProps {
  date: string
  onSelect?: (packageId: string) => void
}

export function PackageBrowserPanel(props: PackageBrowserPanelProps): JSX.Element {
  const [sortBy, setSortBy] = useState<(typeof SORT_OPTIONS)[number]['key']>('risk')
  const { data, isLoading, error } = usePackageBrowser({ date: props.date, sortBy })
  const packages = data?.packages ?? []
  return (
    <div className="flex flex-col gap-2 p-3">
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase text-slate-400">Sort by</span>
        {SORT_OPTIONS.map((o) => (
          <button
            key={o.key}
            type="button"
            aria-pressed={sortBy === o.key}
            onClick={() => setSortBy(o.key)}
            className={`px-2 py-0.5 rounded text-[11px] ${
              sortBy === o.key
                ? 'bg-sky-900/50 text-sky-100'
                : 'bg-slate-800/60 text-slate-400 hover:text-slate-200'
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
      {error ? <p className="text-red-300 text-sm">{error.message}</p> : null}
      {isLoading ? <p className="text-slate-400 text-sm">Loading…</p> : null}
      <ul className="flex flex-col gap-1">
        {packages.map((p) => (
          <li key={p.package_id}>
            <button
              type="button"
              onClick={() => props.onSelect?.(p.package_id)}
              className="w-full text-left rounded bg-slate-900 hover:bg-slate-800 px-2 py-1.5 border border-slate-800"
            >
              <div className="text-xs font-mono text-slate-200">
                {p.tape_label ?? p.package_structure ?? p.package_id}
              </div>
              <div className="flex items-center justify-between text-[11px] text-slate-400 mt-0.5">
                <span>{p.n_package_legs ?? p.legs_count} legs</span>
                <span>
                  {formatDv01(p.total_risk ?? 0, { signed: true })} ·{' '}
                  {formatNotional(p.total_notional ?? 0, { compact: true })}
                </span>
              </div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
