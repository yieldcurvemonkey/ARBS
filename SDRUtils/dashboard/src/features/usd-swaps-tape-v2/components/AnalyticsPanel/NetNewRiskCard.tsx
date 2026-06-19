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

type Row = { day: string; tenor_label: string; dv01: number; trade_count: number }

const TENOR_COLORS: Record<string, string> = {
  '2Y': '#38bdf8', '3Y': '#22d3ee', '5Y': '#34d399', '7Y': '#a3e635',
  '10Y': '#f59e0b', '15Y': '#f97316', '20Y': '#ef4444', '30Y': '#e879f9',
}

function formatDv01(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)}K`
  return v.toFixed(0)
}

export function NetNewRiskCard(): JSX.Element {
  const [data, setData] = useState<Row[]>([])
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/usd-swaps-tape-v2/net-new-risk?days=30')
      if (!res.ok) return
      const json = await res.json()
      setData(json.rows ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const { chartData, tenors } = useMemo(() => {
    const dayMap = new Map<string, Record<string, string | number>>()
    const tenorSet = new Set<string>()
    for (const r of data) {
      tenorSet.add(r.tenor_label)
      const d = r.day.slice(0, 10)
      const existing = dayMap.get(d) ?? { day: d }
      existing[r.tenor_label] = (Number(existing[r.tenor_label]) || 0) + (r.dv01 ?? 0)
      dayMap.set(d, existing)
    }
    return {
      chartData: [...dayMap.values()].sort((a, b) => String(a.day).localeCompare(String(b.day))),
      tenors: [...tenorSet].sort(),
    }
  }, [data])

  const totalDv01 = useMemo(() => data.reduce((s, r) => s + (r.dv01 ?? 0), 0), [data])
  const nDays = new Set(data.map(r => r.day.slice(0, 10))).size

  return (
    <div className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">
          Daily new risk DV01 (30d)
        </span>
        <span className="text-[10px] text-slate-500">{nDays} days</span>
      </div>
      <div className="flex items-baseline gap-3">
        <span className="text-[20px] font-semibold tracking-tight text-emerald-200">
          {loading ? '…' : formatDv01(nDays > 0 ? totalDv01 / nDays : 0)}
        </span>
        <span className="text-[10px] text-slate-500">avg daily DV01</span>
      </div>
      {!loading && chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={ANALYTICS_COLORS.slate800} />
            <XAxis dataKey="day" tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} tickFormatter={v => v.slice(5)} />
            <YAxis tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} tickFormatter={v => formatDv01(v)} />
            <Tooltip
              contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', fontSize: 10, fontFamily: 'monospace' }}
              labelStyle={{ color: '#94a3b8' }}
              formatter={(v: number) => formatDv01(v)}
            />
            {tenors.map(t => (
              <Bar key={t} dataKey={t} stackId="risk" fill={TENOR_COLORS[t] ?? '#64748b'} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )}
      {!loading && chartData.length === 0 && (
        <div className="py-4 text-center text-[10px] text-slate-500">No flow data in window.</div>
      )}
    </div>
  )
}
