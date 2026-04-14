'use client'
// ABOUTME: Global filter bar — search input, AND/OR operator, reset.
import type { JSX } from 'react'
import { useEffect, useState } from 'react'

export interface TradeTapeFiltersProps {
  search: string
  onSearch: (v: string) => void
  operator: 'and' | 'or'
  onOperatorChange: (op: 'and' | 'or') => void
  onReset: () => void
}

const DEBOUNCE_MS = 250

export function TradeTapeFilters(props: TradeTapeFiltersProps): JSX.Element {
  const [local, setLocal] = useState(props.search)

  useEffect(() => setLocal(props.search), [props.search])

  useEffect(() => {
    if (local === props.search) return
    const handle = setTimeout(() => props.onSearch(local), DEBOUNCE_MS)
    return () => clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [local])

  return (
    <div
      className="flex items-center gap-2 px-3 py-2 bg-slate-900/50 border-b border-slate-800"
      data-testid="trade-tape-filters"
    >
      <input
        type="search"
        placeholder="Filter tape…"
        aria-label="global tape filter"
        value={local}
        onChange={(e) => setLocal(e.target.value)}
        className="flex-1 bg-slate-950/60 border border-slate-800 rounded px-2 py-1 text-sm text-slate-100 focus:outline-none focus:border-slate-600"
      />
      <div className="flex items-center gap-1 text-xs text-slate-400">
        <button
          type="button"
          aria-pressed={props.operator === 'and'}
          onClick={() => props.onOperatorChange('and')}
          className={`px-2 py-0.5 rounded ${
            props.operator === 'and'
              ? 'bg-slate-700 text-slate-100'
              : 'bg-slate-800/60'
          }`}
        >
          AND
        </button>
        <button
          type="button"
          aria-pressed={props.operator === 'or'}
          onClick={() => props.onOperatorChange('or')}
          className={`px-2 py-0.5 rounded ${
            props.operator === 'or'
              ? 'bg-slate-700 text-slate-100'
              : 'bg-slate-800/60'
          }`}
        >
          OR
        </button>
      </div>
      <button
        type="button"
        onClick={props.onReset}
        className="text-xs px-2 py-1 rounded bg-slate-800/60 text-slate-300 hover:bg-slate-700/60"
      >
        Reset
      </button>
    </div>
  )
}

export const __internal = { DEBOUNCE_MS }
