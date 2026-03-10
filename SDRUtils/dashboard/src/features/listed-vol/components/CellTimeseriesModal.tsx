'use client'

import { useEffect, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts'
import { Dialog } from '@/components/ui/Dialog/Dialog'
import { LISTED_VOL_RANGE_OPTIONS } from '../constants'
import { useListedVolTimeseries } from '../hooks/useListedVolTimeseries'
import type { ListedVolGridCell, ListedVolRange } from '../types'
import { formatPercentile, formatRatio, formatVol } from '../utils'

type CellTimeseriesModalProps = {
  date?: string
  cell: ListedVolGridCell | null
  open: boolean
  onClose: () => void
}

export function CellTimeseriesModal({
  date,
  cell,
  open,
  onClose
}: CellTimeseriesModalProps) {
  const [range, setRange] = useState<ListedVolRange>('3M')
  const [includeSwaption, setIncludeSwaption] = useState(true)
  const [includeRealized, setIncludeRealized] = useState(true)

  useEffect(() => {
    if (!open) return
    setRange('3M')
  }, [open, cell?.product, cell?.expiryLabel])

  const { data, loading, error } = useListedVolTimeseries({
    date,
    product: cell?.product ?? null,
    expiry: cell?.expiryLabel ?? null,
    range,
    includeSwaption,
    includeRealized,
    enabled: open && cell !== null
  })

  return (
    <Dialog
      isOpen={open}
      onClose={onClose}
      title={cell ? `${cell.product} ${cell.expiryLabel} History` : 'History'}
      size="5xl"
      className="border border-slate-800 bg-slate-950"
    >
      {!cell ? null : (
        <div className="space-y-5 text-slate-100">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-2">
              {LISTED_VOL_RANGE_OPTIONS.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setRange(option)}
                  className={`rounded-full border px-3 py-1.5 text-sm font-semibold transition ${
                    range === option
                      ? 'border-sky-400 bg-sky-500/15 text-sky-100'
                      : 'border-slate-700 bg-slate-900/70 text-slate-300 hover:text-white'
                  }`}
                >
                  {option}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap gap-3 text-sm text-slate-300">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={includeSwaption}
                  onChange={(event) => setIncludeSwaption(event.target.checked)}
                />
                Swaption
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={includeRealized}
                  onChange={(event) => setIncludeRealized(event.target.checked)}
                />
                Realized
              </label>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-4">
            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
              <div className="text-xs uppercase tracking-[0.18em] text-slate-400">Listed</div>
              <div className="mt-2 text-2xl font-semibold tabular-nums">
                {formatVol(data?.stats.listed.latest ?? null)}
              </div>
              <div className="mt-1 text-sm text-slate-400">
                z {formatVol(data?.stats.listed.zScore ?? null, 2)}
              </div>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
              <div className="text-xs uppercase tracking-[0.18em] text-slate-400">Swaption</div>
              <div className="mt-2 text-2xl font-semibold tabular-nums">
                {formatVol(data?.stats.swaption?.latest ?? null)}
              </div>
              <div className="mt-1 text-sm text-slate-400">
                z {formatVol(data?.stats.swaption?.zScore ?? null, 2)}
              </div>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
              <div className="text-xs uppercase tracking-[0.18em] text-slate-400">Ratio</div>
              <div className="mt-2 text-2xl font-semibold tabular-nums">
                {formatRatio(data?.stats.ratio?.latest ?? null)}
              </div>
              <div className="mt-1 text-sm text-slate-400">
                pct {formatPercentile(data?.stats.ratio?.percentile ?? null)}
              </div>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
              <div className="text-xs uppercase tracking-[0.18em] text-slate-400">Realized</div>
              <div className="mt-2 text-2xl font-semibold tabular-nums">
                {formatVol(data?.stats.realized?.latest ?? null)}
              </div>
              <div className="mt-1 text-sm text-slate-400">
                z {formatVol(data?.stats.realized?.zScore ?? null, 2)}
              </div>
            </div>
          </div>

          <div className="h-[420px] rounded-2xl border border-slate-800 bg-slate-900/50 p-3">
            {loading ? (
              <div className="flex h-full items-center justify-center text-sm text-slate-400">
                Loading history...
              </div>
            ) : error ? (
              <div className="flex h-full items-center justify-center text-sm text-rose-300">
                {error}
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data?.points ?? []} margin={{ top: 12, right: 16, left: 0, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" />
                  <XAxis dataKey="date" stroke="#94a3b8" tick={{ fill: '#94a3b8', fontSize: 12 }} />
                  <YAxis stroke="#94a3b8" tick={{ fill: '#94a3b8', fontSize: 12 }} />
                  <Tooltip
                    contentStyle={{
                      background: '#020617',
                      border: '1px solid rgba(51,65,85,0.9)',
                      borderRadius: '14px'
                    }}
                  />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="listedNvolBps"
                    name="Listed"
                    stroke="#38bdf8"
                    strokeWidth={2.5}
                    dot={false}
                  />
                  {includeSwaption ? (
                    <Line
                      type="monotone"
                      dataKey="swaptionNvolBps"
                      name="Swaption"
                      stroke="#fb7185"
                      strokeWidth={2}
                      dot={false}
                    />
                  ) : null}
                  {includeRealized ? (
                    <Line
                      type="monotone"
                      dataKey="realizedNvolBps"
                      name="Realized"
                      stroke="#f59e0b"
                      strokeWidth={2}
                      dot={false}
                    />
                  ) : null}
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      )}
    </Dialog>
  )
}
