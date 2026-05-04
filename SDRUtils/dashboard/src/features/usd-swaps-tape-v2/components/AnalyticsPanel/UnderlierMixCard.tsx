'use client'
// ABOUTME: Small AnalyticsPanel card showing per-canonical-bucket
// volume mix for the loaded tape rows. Switches between trade count /
// Σ|risk| / Σnotional / package-adjusted DV01 and time windows
// (today / 7d / 30d / 90d / YTD). Pure-frontend aggregation off the
// rows already in memory — see utils/underlierMix.ts.
import type { JSX } from 'react'
import { useMemo, useState } from 'react'
import type { UsdSwapTapeRow } from '../../types'
import {
  canonicalDisplayLabel,
  canonicalLongLabel,
} from '../../utils/canonicalDisplay'
import {
  computeUnderlierMix,
  filterRowsToWindow,
  type UnderlierMixMetric,
  type UnderlierMixWindow,
} from '../../utils/underlierMix'

const METRIC_OPTIONS: Array<{ key: UnderlierMixMetric; label: string }> = [
  { key: 'count', label: 'Trades' },
  { key: 'risk', label: 'DV01' },
  { key: 'pa_dv01', label: 'PA-DV01' },
  { key: 'notional', label: 'Notional' },
]

const WINDOW_OPTIONS: Array<{ key: UnderlierMixWindow; label: string }> = [
  { key: 'today', label: 'Today' },
  { key: '7d', label: '7d' },
  { key: '30d', label: '30d' },
  { key: '90d', label: '90d' },
  { key: 'YTD', label: 'YTD' },
]

function formatMetricValue(value: number, metric: UnderlierMixMetric): string {
  if (metric === 'count') return value.toFixed(0)
  if (metric === 'notional') {
    if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`
    if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`
    if (value >= 1e3) return `${(value / 1e3).toFixed(1)}K`
    return value.toFixed(0)
  }
  // risk + pa_dv01 — dollars per bp
  if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`
  if (value >= 1e3) return `${(value / 1e3).toFixed(0)}K`
  return value.toFixed(0)
}

export interface UnderlierMixCardProps {
  rows: readonly UsdSwapTapeRow[]
  /** Override "now" for tests / deterministic snapshots. */
  nowMs?: number
}

export function UnderlierMixCard(props: UnderlierMixCardProps): JSX.Element {
  const [metric, setMetric] = useState<UnderlierMixMetric>('risk')
  const [window, setWindow] = useState<UnderlierMixWindow>('30d')

  const slices = useMemo(() => {
    const filtered = filterRowsToWindow(props.rows, window, props.nowMs)
    return computeUnderlierMix(filtered, metric)
  }, [props.rows, props.nowMs, window, metric])

  const totalRows = useMemo(
    () => filterRowsToWindow(props.rows, window, props.nowMs).length,
    [props.rows, props.nowMs, window],
  )

  return (
    <div
      data-testid="underlier-mix-card"
      className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">
          Underlier mix
        </span>
        <span className="text-[10px] text-slate-500">{totalRows} rows</span>
      </div>

      <div className="flex flex-wrap gap-1">
        {METRIC_OPTIONS.map((opt) => (
          <button
            key={opt.key}
            type="button"
            onClick={() => setMetric(opt.key)}
            className={`rounded border px-1.5 py-0.5 text-[10px] ${
              metric === opt.key
                ? 'border-indigo-400 bg-indigo-500/20 text-indigo-200'
                : 'border-slate-700 bg-transparent text-slate-400 hover:border-slate-500'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-1">
        {WINDOW_OPTIONS.map((opt) => (
          <button
            key={opt.key}
            type="button"
            onClick={() => setWindow(opt.key)}
            className={`rounded border px-1.5 py-0.5 text-[10px] ${
              window === opt.key
                ? 'border-sky-400 bg-sky-500/20 text-sky-200'
                : 'border-slate-700 bg-transparent text-slate-400 hover:border-slate-500'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-1">
        {slices.length === 0 ? (
          <div className="py-2 text-center text-[10px] text-slate-500">
            No rows in this window.
          </div>
        ) : (
          slices.map((slice) => {
            const widthPct = Number.isFinite(slice.share) ? slice.share * 100 : 0
            return (
              <div
                key={slice.key}
                title={canonicalLongLabel(slice.key)}
                className="flex items-center gap-2"
              >
                <span className="w-20 truncate text-[10.5px] text-slate-200">
                  {canonicalDisplayLabel(slice.key)}
                </span>
                <div className="relative h-1.5 flex-1 rounded bg-slate-800">
                  <div
                    className="absolute inset-y-0 left-0 rounded bg-indigo-500/60"
                    style={{ width: `${widthPct.toFixed(2)}%` }}
                  />
                </div>
                <span className="w-12 text-right tabular-nums text-slate-300">
                  {formatMetricValue(slice.value, metric)}
                </span>
                <span className="w-9 text-right tabular-nums text-slate-500">
                  {Number.isFinite(slice.share)
                    ? `${(slice.share * 100).toFixed(0)}%`
                    : '—'}
                </span>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
