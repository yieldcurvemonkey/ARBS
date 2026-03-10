'use client'

import type { ListedVolDisplayMode } from '../types'

type DisplayModeSelectorProps = {
  value: ListedVolDisplayMode
  onChange: (value: ListedVolDisplayMode) => void
}

const OPTIONS: Array<{ value: ListedVolDisplayMode; label: string }> = [
  { value: 'vol', label: 'Vol' },
  { value: 'dchg', label: 'dChg' },
  { value: 'zscore', label: 'Z-Score' }
]

export function DisplayModeSelector({
  value,
  onChange
}: DisplayModeSelectorProps) {
  return (
    <div className="inline-flex rounded-full border border-slate-700 bg-slate-950/70 p-1">
      {OPTIONS.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={`rounded-full px-3 py-1.5 text-sm font-semibold transition ${
              active
                ? 'bg-slate-100 text-slate-950'
                : 'text-slate-300 hover:text-white'
            }`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
