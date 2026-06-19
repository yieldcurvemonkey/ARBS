'use client'
import type { JSX } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ANALYTICS_COLORS } from './analytics-format'

type WallRow = { period: string; tenor_bucket: string; value: number; trade_count: number }
type YearRow = { yr: number; value: number; trade_count: number }

type MetricId = 'notional' | 'dv01'
type BinId = 'quarter' | 'month'

const BUCKET_COLORS: Record<string, string> = {
  '1-2Y': '#38bdf8',
  '3-4Y': '#22d3ee',
  '5-7Y': '#34d399',
  '8-12Y': '#f59e0b',
  '13-22Y': '#f97316',
  '23Y+': '#e879f9',
}

const BUCKET_ORDER = ['1-2Y', '3-4Y', '5-7Y', '8-12Y', '13-22Y', '23Y+']

function fmt(v: number | null | undefined, metric: MetricId): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (metric === 'dv01') {
    if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`
    if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`
    if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`
    return v.toFixed(0)
  }
  if (v >= 1e12) return `${(v / 1e12).toFixed(1)}T`
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`
  if (v >= 1e6) return `${(v / 1e6).toFixed(0)}M`
  return v.toFixed(0)
}

function fmtPeriod(iso: string, bin: BinId): string {
  const d = new Date(iso)
  if (bin === 'quarter') {
    const q = Math.floor(d.getUTCMonth() / 3) + 1
    return `Q${q}'${String(d.getUTCFullYear()).slice(2)}`
  }
  return d.toLocaleDateString('en-US', { year: '2-digit', month: 'short', timeZone: 'UTC' })
}

export function MaturityWallCard(): JSX.Element {
  const [rows, setRows] = useState<WallRow[]>([])
  const [byYear, setByYear] = useState<YearRow[]>([])
  const [loading, setLoading] = useState(true)
  const [metric, setMetric] = useState<MetricId>('notional')
  const [bin, setBin] = useState<BinId>('quarter')

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`/api/usd-swaps-tape-v2/maturity-wall?metric=${metric}&bin=${bin}`)
      if (!res.ok) return
      const json = await res.json()
      setRows(json.rows ?? [])
      setByYear(json.byYear ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [metric, bin])

  useEffect(() => { fetchData() }, [fetchData])

  const { chartData, buckets } = useMemo(() => {
    const periodMap = new Map<string, Record<string, string | number>>()
    const bucketSet = new Set<string>()
    for (const r of rows) {
      const b = r.tenor_bucket
      bucketSet.add(b)
      const p = fmtPeriod(r.period, bin)
      const existing = periodMap.get(p) ?? { period: p, _sort: r.period }
      existing[b] = (Number(existing[b]) || 0) + (r.value ?? 0)
      periodMap.set(p, existing)
    }
    const sorted = [...periodMap.values()].sort((a, b) => String(a._sort).localeCompare(String(b._sort)))
    return {
      chartData: sorted,
      buckets: BUCKET_ORDER.filter(b => bucketSet.has(b)),
    }
  }, [rows, bin])

  const total = byYear.reduce((s, r) => s + (Number(r.value) || 0), 0)

  return (
    <div className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">Maturity wall (5yr)</span>
        <div className="flex gap-1">
          <div className="flex items-center rounded border border-slate-700 p-[1px]">
            <button type="button" onClick={() => setMetric('notional')}
              className={`px-1.5 py-[1px] text-[10px] ${metric === 'notional' ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-400 hover:bg-slate-800'}`}>
              Notional
            </button>
            <button type="button" onClick={() => setMetric('dv01')}
              className={`px-1.5 py-[1px] text-[10px] ${metric === 'dv01' ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-400 hover:bg-slate-800'}`}>
              DV01
            </button>
          </div>
          <div className="flex items-center rounded border border-slate-700 p-[1px]">
            <button type="button" onClick={() => setBin('quarter')}
              className={`px-1.5 py-[1px] text-[10px] ${bin === 'quarter' ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-400 hover:bg-slate-800'}`}>
              Qtr
            </button>
            <button type="button" onClick={() => setBin('month')}
              className={`px-1.5 py-[1px] text-[10px] ${bin === 'month' ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-400 hover:bg-slate-800'}`}>
              Month
            </button>
          </div>
        </div>
      </div>

      {!loading && byYear.length > 0 && (
        <div className="flex gap-3 text-[10px]">
          {byYear.map(y => (
            <div key={y.yr} className="flex flex-col items-center">
              <span className="text-slate-500">{y.yr}</span>
              <span className="tabular-nums text-slate-200">{fmt(Number(y.value) || 0, metric)}</span>
            </div>
          ))}
          <div className="flex flex-col items-center border-l border-slate-700 pl-3">
            <span className="text-amber-500/80">Total</span>
            <span className="tabular-nums font-semibold text-slate-100">{fmt(total, metric)}</span>
          </div>
        </div>
      )}

      {!loading && chartData.length > 0 ? (
        <>
          <div className="flex flex-wrap gap-2 text-[9px]">
            {buckets.map(b => (
              <span key={b} className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: BUCKET_COLORS[b] ?? '#64748b' }} />
                {b}
              </span>
            ))}
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={ANALYTICS_COLORS.slate800} />
              <XAxis
                dataKey="period"
                tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 8 }}
                interval={bin === 'month' ? Math.max(0, Math.floor(chartData.length / 12)) : 0}
              />
              <YAxis tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} tickFormatter={v => fmt(v, metric)} />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', fontSize: 10, fontFamily: 'monospace' }}
                formatter={(v: number) => fmt(v, metric)}
              />
              {buckets.map(b => (
                <Bar key={b} dataKey={b} stackId="wall" fill={BUCKET_COLORS[b] ?? '#64748b'} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </>
      ) : loading ? (
        <div className="py-4 text-center text-[10px] text-slate-500">Loading…</div>
      ) : (
        <div className="py-4 text-center text-[10px] text-slate-500">No maturity data available.</div>
      )}
    </div>
  )
}
