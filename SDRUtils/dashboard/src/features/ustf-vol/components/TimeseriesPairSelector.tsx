'use client'

import type { AssetType, SeriesConfig, TimeRange, TimeseriesMode } from '../types'
import {
  STANDARD_PAIRS,
  SWAPTION_EXPIRIES,
  SWAPTION_TAILS,
  USTF_EXPIRIES,
  USTF_PRODUCTS,
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

const LABEL_CLASS =
  'text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500'
const SELECT_CLASS =
  'h-8 rounded-md border border-slate-700/80 bg-slate-950/80 px-3 text-[12px] text-slate-100 outline-none transition focus:border-slate-500'

function segmentButtonClass(active: boolean): string {
  return [
    'px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] transition',
    active
      ? 'bg-slate-100 text-slate-950'
      : 'bg-slate-950/70 text-slate-300 hover:bg-slate-900 hover:text-white',
  ].join(' ')
}

function quickPickClass(): string {
  return 'rounded-md border border-slate-700/80 bg-slate-950/80 px-3 py-1.5 text-[11px] font-medium text-slate-300 transition hover:border-slate-500 hover:text-white'
}

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
    <div className="grid gap-3 rounded-lg border border-slate-800/80 bg-slate-950/45 p-3 lg:grid-cols-[96px_minmax(0,1fr)]">
      <div className="flex items-center">
        <span className={LABEL_CLASS}>{label}</span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex overflow-hidden rounded-md border border-slate-700/80">
          {(['ustf', 'swaption'] as AssetType[]).map((assetType) => (
            <button
              key={assetType}
              type="button"
              onClick={() =>
                onChange({
                  type: assetType,
                  product: assetType === 'ustf' ? 'TY' : undefined,
                  expiry: '1M',
                  tail: assetType === 'swaption' ? '7Y' : undefined,
                })
              }
              className={segmentButtonClass(config.type === assetType)}
            >
              {assetType === 'ustf' ? 'USTF' : 'OTC'}
            </button>
          ))}
        </div>

        {config.type === 'ustf' ? (
          <select
            value={config.product ?? 'TY'}
            onChange={(event) => onChange({ ...config, product: event.target.value as any })}
            className={SELECT_CLASS}
          >
            {USTF_PRODUCTS.map((product) => (
              <option key={product} value={product}>
                {product}
              </option>
            ))}
          </select>
        ) : (
          <select
            value={config.tail ?? '7Y'}
            onChange={(event) => onChange({ ...config, tail: event.target.value as any })}
            className={SELECT_CLASS}
          >
            {SWAPTION_TAILS.map((tail) => (
              <option key={tail} value={tail}>
                {tail}
              </option>
            ))}
          </select>
        )}

        <select
          value={config.expiry}
          onChange={(event) => onChange({ ...config, expiry: event.target.value })}
          className={SELECT_CLASS}
        >
          {expiries.map((expiry) => (
            <option key={expiry} value={expiry}>
              {expiry}
            </option>
          ))}
        </select>

        {onClear ? (
          <button
            type="button"
            onClick={onClear}
            className="rounded-md border border-slate-700/80 bg-slate-950/80 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400 transition hover:border-slate-500 hover:text-white"
          >
            Clear
          </button>
        ) : null}
      </div>
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
    <div className="space-y-4">
      <div className="rounded-lg border border-slate-800/80 bg-slate-950/45 p-3">
        <div className={LABEL_CLASS}>Standard comparison map</div>
        <div className="mt-2 flex flex-wrap gap-2">
          {STANDARD_PAIRS.map((pair) => (
            <button
              key={pair.label}
              type="button"
              onClick={() => {
                onSeries1Change(pair.series1)
                onSeries2Change(pair.series2)
              }}
              className={quickPickClass()}
            >
              {pair.label}
            </button>
          ))}
        </div>
      </div>

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
          type="button"
          onClick={() => onSeries2Change({ type: 'swaption', expiry: '1M', tail: '7Y' })}
          className="rounded-md border border-dashed border-slate-700/80 bg-slate-950/45 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400 transition hover:border-slate-500 hover:text-white"
        >
          Add comparison leg
        </button>
      )}

      <div className="grid gap-3 rounded-lg border border-slate-800/80 bg-slate-950/45 p-3 xl:grid-cols-2">
        <div className="flex flex-wrap items-center gap-3">
          <span className={LABEL_CLASS}>Display mode</span>
          <div className="flex overflow-hidden rounded-md border border-slate-700/80">
            {(['overlay', 'spread'] as TimeseriesMode[]).map((viewMode) => (
              <button
                key={viewMode}
                type="button"
                onClick={() => onModeChange(viewMode)}
                className={segmentButtonClass(mode === viewMode)}
              >
                {viewMode}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <span className={LABEL_CLASS}>Lookback</span>
          <div className="flex flex-wrap overflow-hidden rounded-md border border-slate-700/80">
            {RANGES.map((timeRange) => (
              <button
                key={timeRange}
                type="button"
                onClick={() => onRangeChange(timeRange)}
                className={segmentButtonClass(range === timeRange)}
              >
                {timeRange}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
