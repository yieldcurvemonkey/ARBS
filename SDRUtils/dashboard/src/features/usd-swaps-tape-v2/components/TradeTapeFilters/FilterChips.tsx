'use client'
// ABOUTME: Chip bar of multi-select filters (Trade Type, Venue, CCP, Session, Rate Index).
import type { JSX } from 'react'
import type { FlagFilterState } from '../../types'

type Field = {
  key: keyof FlagFilterState
  label: string
  values: string[]
  onToggle: (v: string) => void
  selected: Set<string>
}

export interface FilterChipsProps {
  fields: Field[]
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`px-2 py-0.5 rounded text-[11px] ${
        active
          ? 'bg-sky-900/50 text-sky-200 border border-sky-700/40'
          : 'bg-slate-800/60 text-slate-400 border border-slate-700/60 hover:text-slate-200'
      }`}
    >
      {children}
    </button>
  )
}

export function FilterChips(props: FilterChipsProps): JSX.Element {
  return (
    <div
      className="flex flex-wrap items-center gap-2 px-3 py-1 border-b border-slate-800"
      data-testid="filter-chips"
    >
      {props.fields.map((f) => (
        <div key={String(f.key)} className="flex items-center gap-1">
          <span className="text-[10px] uppercase text-slate-400 mr-1">{f.label}</span>
          {f.values.map((v) => (
            <Chip
              key={v}
              active={f.selected.has(v) || f.selected.size === 0}
              onClick={() => f.onToggle(v)}
            >
              {v}
            </Chip>
          ))}
        </div>
      ))}
    </div>
  )
}
