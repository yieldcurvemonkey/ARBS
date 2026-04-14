'use client'
// ABOUTME: Clean-tape preset toggle — flips lifecycle set + clean param.
import type { JSX } from 'react'

export interface CleanTapeToggleProps {
  clean: boolean
  onApply: () => void
  onReset: () => void
}

export function CleanTapeToggle(props: CleanTapeToggleProps): JSX.Element {
  const label = props.clean ? 'Clean tape ✓' : 'Clean tape'
  return (
    <button
      type="button"
      aria-pressed={props.clean}
      onClick={() => (props.clean ? props.onReset() : props.onApply())}
      className={`text-xs px-2 py-1 rounded ${
        props.clean
          ? 'bg-emerald-900/60 text-emerald-100 border border-emerald-600/60'
          : 'bg-slate-800/70 text-slate-200 border border-slate-700/70 hover:bg-slate-700/70'
      }`}
    >
      {label}
    </button>
  )
}
