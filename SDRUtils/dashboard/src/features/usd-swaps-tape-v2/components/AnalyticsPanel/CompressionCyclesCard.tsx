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

type Row = { day: string; compression_count: number; total_dv01: number; total_notional: number }

function formatDv01(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)}K`
  return v.toFixed(0)
}

export function CompressionCyclesCard(): JSX.Element {
  const [rows, setRows] = useState<Row[]>([])
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/usd-swaps-tape-v2/compression-cycles?days=30')
      if (!res.ok) return
      const json = await res.json()
      setRows(json.rows ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const chartData = useMemo(() =>
    rows.map(r => ({
      day: r.day.slice(0, 10),
      count: Number(r.compression_count) || 0,
      dv01: Number(r.total_dv01) || 0,
    })),
  [rows])

  const totalCount = rows.reduce((s, r) => s + (Number(r.compression_count) || 0), 0)
  const avgDaily = rows.length > 0 ? totalCount / rows.length : 0

  return (
    <div className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">
          Compression activity (30d)
        </span>
        <span className="text-[10px] text-slate-500">{rows.length} days</span>
      </div>
      <div className="flex items-baseline gap-3">
        <span className="text-[20px] font-semibold tracking-tight text-rose-200">
          {loading ? '…' : Math.round(avgDaily)}
        </span>
        <span className="text-[10px] text-slate-500">avg daily legs</span>
      </div>
      {!loading && chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={140}>
          <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={ANALYTICS_COLORS.slate800} />
            <XAxis dataKey="day" tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} tickFormatter={v => v.slice(5)} />
            <YAxis tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} />
            <Tooltip
              contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', fontSize: 10, fontFamily: 'monospace' }}
              formatter={(v: number, name: string) => [name === 'dv01' ? formatDv01(v) : v, name === 'dv01' ? 'DV01' : 'Legs']}
            />
            <Bar dataKey="count" fill="#f43f5e" fillOpacity={0.6} name="Legs" />
          </BarChart>
        </ResponsiveContainer>
      )}
      {!loading && chartData.length === 0 && (
        <div className="py-2 text-center text-[10px] text-slate-500">No compression data in window.</div>
      )}
    </div>
  )
}
