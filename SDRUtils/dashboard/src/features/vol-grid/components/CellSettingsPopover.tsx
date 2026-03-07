'use client'

import type { CellDisplayConfig, CellDisplayField } from '../types'

type CellSettingsPopoverProps = {
  config: CellDisplayConfig
  onToggle: (field: CellDisplayField) => void
  onReset: () => void
}

const FIELD_OPTIONS: Array<{ field: CellDisplayField; label: string; required?: boolean }> = [
  { field: 'vol', label: 'Vol (bpvol)', required: true },
  { field: 'premium', label: 'Premium (bps)' },
  { field: 'change', label: '1d Change' },
  { field: 'lastTradedTime', label: 'Last Traded Time (SDR)' },
  { field: 'lastTradedLevel', label: 'Last Traded Level (SDR)' }
]

export function CellSettingsPopover({ config, onToggle, onReset }: CellSettingsPopoverProps) {
  return (
    <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 p-4">
      <h2 className="text-sm font-semibold text-slate-200">Cell Display Fields</h2>
      <div className="mt-3 flex flex-wrap gap-3 text-sm">
        {FIELD_OPTIONS.map(({ field, label, required }) => {
          const checked = config.visibleFields.includes(field)
          return (
            <label key={field} className="flex items-center gap-2 text-slate-300">
              <input
                type="checkbox"
                checked={checked}
                disabled={required && checked}
                onChange={() => onToggle(field)}
                className="accent-amber-400"
              />
              {label}
            </label>
          )
        })}
      </div>
      <div className="mt-3">
        <button
          onClick={onReset}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:border-slate-500"
        >
          Reset to Defaults
        </button>
      </div>
    </div>
  )
}
