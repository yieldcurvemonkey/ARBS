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

type DailyRow = { day: string; platform: string; dv01: number }

const VENUE_COLORS = [
  '#38bdf8', '#f59e0b', '#34d399', '#e879f9', '#f97316', '#64748b',
]

function formatDv01(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)}K`
  return v.toFixed(0)
}

export function VenueShiftCard(): JSX.Element {
  const [daily, setDaily] = useState<DailyRow[]>([])
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/usd-swaps-tape-v2/venue-shift?days=30')
      if (!res.ok) return
      const json = await res.json()
      setDaily(json.daily ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const platforms = useMemo(() => {
    const m: Record<string, number> = {}
    for (const r of daily) m[r.platform] = (m[r.platform] ?? 0) + (r.dv01 ?? 0)
    return Object.entries(m).sort((a, b) => b[1] - a[1]).map(([p]) => p)
  }, [daily])

  const platformColorMap = useMemo(() => {
    const m: Record<string, string> = {}
    platforms.forEach((p, i) => { m[p] = VENUE_COLORS[i % VENUE_COLORS.length] })
    return m
  }, [platforms])

  const chartData = useMemo(() => {
    const dayMap = new Map<string, Record<string, string | number>>()
    for (const r of daily) {
      const d = r.day.slice(0, 10)
      const existing = dayMap.get(d) ?? { day: d }
      existing[r.platform] = (Number(existing[r.platform]) || 0) + (r.dv01 ?? 0)
      dayMap.set(d, existing)
    }
    return [...dayMap.values()].sort((a, b) => String(a.day).localeCompare(String(b.day)))
  }, [daily])

  return (
    <div className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">Venue market share (30d)</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {platforms.slice(0, 6).map(p => (
          <div key={p} className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: platformColorMap[p] }} />
            <span className="text-[10px] text-slate-300">{p}</span>
          </div>
        ))}
      </div>

      {!loading && chartData.length > 0 ? (
        <ResponsiveContainer width="100%" height={140}>
          <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={ANALYTICS_COLORS.slate800} />
            <XAxis dataKey="day" tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} tickFormatter={v => v.slice(5)} />
            <YAxis tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} tickFormatter={v => formatDv01(v)} />
            <Tooltip contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', fontSize: 10, fontFamily: 'monospace' }} formatter={(v: number) => formatDv01(v)} />
            {platforms.map(p => (
              <Bar key={p} dataKey={p} stackId="venue" fill={platformColorMap[p]} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      ) : !loading ? (
        <div className="py-2 text-center text-[10px] text-slate-500">No venue data in window.</div>
      ) : null}
    </div>
  )
}
