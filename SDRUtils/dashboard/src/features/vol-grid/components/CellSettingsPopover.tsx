'use client'

import type {
  CellDisplayConfig,
  CellDisplayField,
  LastTradedLevelField,
  VolGridHeatmapMetric,
  VolGridHeatmapStrategy
} from '../types'

type CellSettingsPopoverProps = {
  config: CellDisplayConfig
  onToggle: (field: CellDisplayField) => void
  onToggleLastTradedLevelField: (field: LastTradedLevelField) => void
  onSetHeatmapStrategy: (strategy: VolGridHeatmapStrategy) => void
  onSetHeatmapMetric: (metric: VolGridHeatmapMetric) => void
  onToggleHeatmapInversion: () => void
  onSetHeatmapCustomTargets: (customTargets: string) => void
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

const HEATMAP_STRATEGY_OPTIONS: Array<{
  value: VolGridHeatmapStrategy
  label: string
}> = [
  { value: 'absolute', label: 'Absolute Level' },
  { value: 'delta', label: '1d Change' },
  { value: 'custom', label: 'Custom Nodes' },
  { value: 'none', label: 'No Highlighting' }
]

const HEATMAP_METRIC_OPTIONS: Array<{
  value: VolGridHeatmapMetric
  label: string
}> = [
  { value: 'vol', label: 'Vol (bpvol)' },
  { value: 'premium', label: 'Premium (bps)' }
]

export function CellSettingsPopover({
  config,
  onToggle,
  onToggleLastTradedLevelField,
  onSetHeatmapStrategy,
  onSetHeatmapMetric,
  onToggleHeatmapInversion,
  onSetHeatmapCustomTargets,
  onReset
}: CellSettingsPopoverProps) {
  const heatmapControlsDisabled =
    config.heatmap.strategy === 'none' || config.heatmap.strategy === 'custom'

  return (
    <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 p-4">
      <h2 className="text-sm font-semibold text-slate-200">Display Settings</h2>
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
      <div className="mt-5 border-t border-slate-800/80 pt-4">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
          Heatmap Coloring
        </div>
        <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">
          <label className="text-xs text-slate-400">
            Strategy
            <select
              value={config.heatmap.strategy}
              onChange={(event) =>
                onSetHeatmapStrategy(event.target.value as VolGridHeatmapStrategy)
              }
              className="mt-2 w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200"
            >
              {HEATMAP_STRATEGY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-slate-400">
            Metric
            <select
              value={config.heatmap.metric}
              disabled={heatmapControlsDisabled}
              onChange={(event) =>
                onSetHeatmapMetric(event.target.value as VolGridHeatmapMetric)
              }
              className="mt-2 w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {HEATMAP_METRIC_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-4 text-sm text-slate-300">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={config.heatmap.inverted}
              disabled={config.heatmap.strategy === 'none'}
              onChange={onToggleHeatmapInversion}
              className="accent-amber-400"
            />
            Inverse coloring
          </label>
          <div className="text-[11px] text-slate-500">
            Absolute and delta modes use grid-wide scaling. Custom mode highlights explicit nodes only.
          </div>
        </div>
        {config.heatmap.strategy === 'custom' && (
          <label className="mt-4 block text-xs text-slate-400">
            Highlighted Expiry/Tenor Pairs
            <textarea
              value={config.heatmap.customTargets}
              onChange={(event) => onSetHeatmapCustomTargets(event.target.value)}
              rows={3}
              placeholder={'10Y x 10Y, 15Y x 10Y\n20Y x 1Y'}
              className="mt-2 w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 font-mono text-xs text-slate-200"
            />
            <div className="mt-2 text-[11px] text-slate-500">
              Accepts comma- or newline-separated pairs like `10Y x 10Y`, `15Y_10Y`, or `20Y 1Y`.
            </div>
          </label>
        )}
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
