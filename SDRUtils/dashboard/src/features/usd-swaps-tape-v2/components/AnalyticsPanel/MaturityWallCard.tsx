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

type WallRow = { month: string; tenor_label: string; total_notional: number; total_dv01: number; trade_count: number }

const TENOR_COLORS: Record<string, string> = {
  '2Y': '#38bdf8',
  '3Y': '#22d3ee',
  '5Y': '#34d399',
  '7Y': '#a3e635',
  '10Y': '#f59e0b',
  '15Y': '#f97316',
  '20Y': '#ef4444',
  '30Y': '#e879f9',
}

function formatNotional(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (v >= 1e12) return `${(v / 1e12).toFixed(1)}T`
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`
  if (v >= 1e6) return `${(v / 1e6).toFixed(0)}M`
  return v.toFixed(0)
}

export function MaturityWallCard(): JSX.Element {
  const [rows, setRows] = useState<WallRow[]>([])
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/usd-swaps-tape-v2/maturity-wall')
      if (!res.ok) return
      const json = await res.json()
      setRows(json.rows ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const { chartData, tenors } = useMemo(() => {
    const monthMap = new Map<string, Record<string, string | number>>()
    const tenorSet = new Set<string>()
    for (const r of rows) {
      tenorSet.add(r.tenor_label)
      const m = new Date(r.month).toLocaleDateString('en-US', {
        year: '2-digit', month: 'short', timeZone: 'UTC',
      })
      const existing = monthMap.get(m) ?? { month: m }
      existing[r.tenor_label] = (Number(existing[r.tenor_label]) || 0) + (r.total_notional ?? 0)
      monthMap.set(m, existing)
    }
    return {
      chartData: [...monthMap.values()],
      tenors: [...tenorSet].sort(),
    }
  }, [rows])

  const totalNotional = rows.reduce((s, r) => s + (r.total_notional ?? 0), 0)

  return (
    <div className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">Maturity wall (5yr)</span>
        <span className="text-[10px] text-slate-500">{formatNotional(totalNotional)} total</span>
      </div>

      {!loading && chartData.length > 0 ? (
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={ANALYTICS_COLORS.slate800} />
            <XAxis
              dataKey="month"
              tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 8 }}
              interval={Math.max(0, Math.floor(chartData.length / 12))}
            />
            <YAxis tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} tickFormatter={v => formatNotional(v)} />
            <Tooltip
              contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', fontSize: 10, fontFamily: 'monospace' }}
              formatter={(v: number) => formatNotional(v)}
            />
            {tenors.map(t => (
              <Bar key={t} dataKey={t} stackId="wall" fill={TENOR_COLORS[t] ?? '#64748b'} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      ) : loading ? (
        <div className="py-4 text-center text-[10px] text-slate-500">Loading…</div>
      ) : (
        <div className="py-4 text-center text-[10px] text-slate-500">No maturity data available.</div>
      )}
    </div>
  )
}
