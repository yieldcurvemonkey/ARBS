'use client'

import type { AssetType, SeriesConfig, TimeRange, TimeseriesMode } from '../types'
import {
  USTF_PRODUCTS,
  SWAPTION_TAILS,
  USTF_EXPIRIES,
  SWAPTION_EXPIRIES,
  STANDARD_PAIRS,
} from '../constants'

type Props = {
  series1: SeriesConfig
  series2: SeriesConfig | null
  mode: TimeseriesMode
  range: TimeRange
  onSeries1Change: (s: SeriesConfig) => void
  onSeries2Change: (s: SeriesConfig | null) => void
  onModeChange: (m: TimeseriesMode) => void
  onRangeChange: (r: TimeRange) => void
}

const RANGES: TimeRange[] = ['1M', '3M', '6M', '1Y', 'ALL']

function SeriesRow({
  label,
  config,
  onChange,
  onClear,
}: {
  label: string
  config: SeriesConfig
  onChange: (s: SeriesConfig) => void
  onClear?: () => void
}) {
  const expiries = config.type === 'ustf' ? USTF_EXPIRIES : SWAPTION_EXPIRIES

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="w-16 text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</span>

      {/* Type toggle */}
      <div className="flex overflow-hidden rounded-lg border border-slate-700">
        {(['ustf', 'swaption'] as AssetType[]).map((t) => (
          <button
            key={t}
            onClick={() =>
              onChange({
                type: t,
                product: t === 'ustf' ? 'TY' : undefined,
                expiry: t === 'ustf' ? '1M' : '1M',
                tail: t === 'swaption' ? '7Y' : undefined,
              })
            }
            className={`px-3 py-1.5 text-xs font-semibold ${
              config.type === t
                ? 'bg-slate-100 text-slate-950'
                : 'bg-slate-900/70 text-slate-300 hover:text-white'
            }`}
          >
            {t === 'ustf' ? 'USTF' : 'Swpn'}
          </button>
        ))}
      </div>

      {/* Product / Tail */}
      {config.type === 'ustf' ? (
        <select
          value={config.product ?? 'TY'}
          onChange={(e) => onChange({ ...config, product: e.target.value as any })}
          className="rounded-lg border border-slate-700 bg-slate-900/70 px-2 py-1.5 text-xs text-slate-200"
        >
          {USTF_PRODUCTS.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      ) : (
        <select
          value={config.tail ?? '7Y'}
          onChange={(e) => onChange({ ...config, tail: e.target.value as any })}
          className="rounded-lg border border-slate-700 bg-slate-900/70 px-2 py-1.5 text-xs text-slate-200"
        >
          {SWAPTION_TAILS.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      )}

      {/* Expiry */}
      <select
        value={config.expiry}
        onChange={(e) => onChange({ ...config, expiry: e.target.value })}
        className="rounded-lg border border-slate-700 bg-slate-900/70 px-2 py-1.5 text-xs text-slate-200"
      >
        {expiries.map((e) => (
          <option key={e} value={e}>{e}</option>
        ))}
      </select>

      {onClear && (
        <button
          onClick={onClear}
          className="rounded-lg border border-slate-700 bg-slate-900/70 px-2 py-1.5 text-xs text-slate-400 hover:text-white"
        >
          Clear
        </button>
      )}
    </div>
  )
}

export function TimeseriesPairSelector({
  series1,
  series2,
  mode,
  range,
  onSeries1Change,
  onSeries2Change,
  onModeChange,
  onRangeChange,
}: Props) {
  return (
    <div className="space-y-3">
      {/* Quick picks */}
      <div className="flex flex-wrap gap-1.5">
        {STANDARD_PAIRS.map((pair) => (
          <button
            key={pair.label}
            onClick={() => {
              onSeries1Change(pair.series1)
              onSeries2Change(pair.series2)
            }}
            className="rounded-full border border-slate-700 bg-slate-900/70 px-3 py-1 text-[11px] font-medium text-slate-300 transition hover:border-sky-400/50 hover:text-white"
          >
            {pair.label}
          </button>
        ))}
      </div>

      {/* Series rows */}
      <SeriesRow label="Series 1" config={series1} onChange={onSeries1Change} />
      {series2 ? (
        <SeriesRow
          label="Series 2"
          config={series2}
          onChange={onSeries2Change}
          onClear={() => onSeries2Change(null)}
        />
      ) : (
        <button
          onClick={() =>
            onSeries2Change({ type: 'swaption', expiry: '1M', tail: '7Y' })
          }
          className="text-xs text-sky-400 hover:text-sky-300"
        >
          + Add Series 2
        </button>
      )}

      {/* Mode & Range */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">Mode</span>
          <div className="flex overflow-hidden rounded-lg border border-slate-700">
            {(['overlay', 'spread'] as TimeseriesMode[]).map((m) => (
              <button
                key={m}
                onClick={() => onModeChange(m)}
                className={`px-3 py-1 text-xs font-semibold ${
                  mode === m
                    ? 'bg-slate-100 text-slate-950'
                    : 'bg-slate-900/70 text-slate-300 hover:text-white'
                }`}
              >
                {m === 'overlay' ? 'Overlay' : 'Spread'}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">Range</span>
          <div className="flex overflow-hidden rounded-lg border border-slate-700">
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => onRangeChange(r)}
                className={`px-2.5 py-1 text-xs font-semibold ${
                  range === r
                    ? 'bg-slate-100 text-slate-950'
                    : 'bg-slate-900/70 text-slate-300 hover:text-white'
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
