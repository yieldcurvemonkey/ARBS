'use client'

import type {
  CellDisplayConfig,
  CellDisplayField,
  LastTradedLevelField
} from '../types'

type CellSettingsPopoverProps = {
  config: CellDisplayConfig
  onToggle: (field: CellDisplayField) => void
  onToggleLastTradedLevelField: (field: LastTradedLevelField) => void
  onReset: () => void
}

const FIELD_OPTIONS: Array<{ field: CellDisplayField; label: string; required?: boolean }> = [
  { field: 'vol', label: 'Vol (bpvol)', required: true },
  { field: 'premium', label: 'Premium (bps)' },
  { field: 'change', label: '1d Change' },
  { field: 'lastTradedTime', label: 'Last Traded Time (SDR)' },
  { field: 'lastTradedLevel', label: 'Last Traded Level (SDR)' }
]

const LAST_TRADED_LEVEL_OPTIONS: Array<{
  field: LastTradedLevelField
  label: string
}> = [
  { field: 'bpvol', label: 'BPVol' },
  { field: 'premiumBps', label: 'Prem (bps)' }
]

export function CellSettingsPopover({
  config,
  onToggle,
  onToggleLastTradedLevelField,
  onReset
}: CellSettingsPopoverProps) {
  return (
    <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 p-4">
      <h2 className="text-sm font-semibold text-slate-200">Cell Display Fields</h2>
      <div className="mt-3 flex flex-wrap gap-4 text-sm">
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
      {config.visibleFields.includes('lastTradedLevel') && (
        <div className="mt-4">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            Last Traded Level Fields
          </div>
          <div className="mt-2 flex flex-wrap gap-4 text-sm">
            {LAST_TRADED_LEVEL_OPTIONS.map(({ field, label }) => {
              const checked = config.lastTradedLevelFields.includes(field)
              return (
                <label key={field} className="flex items-center gap-2 text-slate-300">
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={checked && config.lastTradedLevelFields.length <= 1}
                    onChange={() => onToggleLastTradedLevelField(field)}
                    className="accent-amber-400"
                  />
                  {label}
                </label>
              )
            })}
          </div>
        </div>
      )}
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
