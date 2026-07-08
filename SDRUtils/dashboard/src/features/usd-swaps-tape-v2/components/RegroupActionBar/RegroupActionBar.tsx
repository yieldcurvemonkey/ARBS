'use client'
// ABOUTME: Contextual action bar for the tape toolbar `actionSlot`. Shows
// the selection count and Group/Split/Detach/Note actions, each enabled per
// the derived SelectionContext.
import type { JSX } from 'react'
import type { SelectionContext } from '../../hooks/useSelectionContext'

export type RegroupAction = 'GROUP' | 'SPLIT' | 'DETACH' | 'NOTE'

export interface RegroupActionBarProps {
  selectedTradeIds: Set<string>
  context: SelectionContext
  onAction: (action: RegroupAction) => void
  onClear: () => void
}

interface ActionDef {
  key: RegroupAction
  label: string
  enabled: boolean
}

export function RegroupActionBar({
  selectedTradeIds,
  context,
  onAction,
  onClear,
}: RegroupActionBarProps): JSX.Element {
  const count = selectedTradeIds.size
  const actions: ActionDef[] = [
    { key: 'GROUP', label: 'Group', enabled: context.canGroup },
    { key: 'SPLIT', label: 'Split', enabled: context.canSplit },
    { key: 'DETACH', label: 'Detach', enabled: context.canDetach },
    { key: 'NOTE', label: 'Note', enabled: context.canNote },
  ]
  return (
    <div className="flex items-center gap-2" role="toolbar" aria-label="Regroup actions">
      <span className="whitespace-nowrap font-mono text-[10.5px] text-slate-300">
        {count} selected
      </span>
      {actions.map((a) => (
        <button
          key={a.key}
          type="button"
          disabled={!a.enabled}
          onClick={() => onAction(a.key)}
          className={`rounded border px-2.5 py-1 font-mono text-[10.5px] ring-1 ring-transparent transition-colors ${
            a.enabled
              ? 'border-slate-700 text-slate-200 hover:bg-slate-800'
              : 'cursor-not-allowed border-slate-800 text-slate-600 opacity-60'
          }`}
        >
          {a.label}
        </button>
      ))}
      <button
        type="button"
        aria-label="Clear selection"
        onClick={onClear}
        className="rounded border border-slate-700 px-2 py-1 font-mono text-[10.5px] text-slate-400 hover:bg-slate-800 hover:text-slate-200"
      >
        ✕
      </button>
    </div>
  )
}
