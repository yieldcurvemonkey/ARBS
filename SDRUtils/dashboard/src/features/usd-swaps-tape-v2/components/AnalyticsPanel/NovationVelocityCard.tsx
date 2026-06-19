'use client'
import type { JSX } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ANALYTICS_COLORS } from './analytics-format'

type TodayRow = { hour_et: number; novation_count: number; total_dv01: number }
type HistRow = { hour_et: number; avg_count: number; avg_dv01: number }

export function NovationVelocityCard(): JSX.Element {
  const [today, setToday] = useState<TodayRow[]>([])
  const [hist, setHist] = useState<HistRow[]>([])
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/usd-swaps-tape-v2/novation-velocity')
      if (!res.ok) return
      const json = await res.json()
      setToday(json.today ?? [])
      setHist(json.historical ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const { chartData, alerts } = useMemo(() => {
    const histMap = new Map<number, number>()
    for (const r of hist) histMap.set(r.hour_et, r.avg_count)

    const hours = new Set<number>()
    for (const r of today) hours.add(r.hour_et)
    for (const r of hist) hours.add(r.hour_et)

    const sorted = [...hours].sort((a, b) => a - b)
    const alertHours: number[] = []

    const cd = sorted.map(h => {
      const todayRow = today.find(r => r.hour_et === h)
      const avgCount = Number(histMap.get(h)) || 0
      const count = Number(todayRow?.novation_count) || 0
      if (count > avgCount * 2 && count > 0) alertHours.push(h)
      return {
        hour: `${String(h).padStart(2, '0')}:00`,
        count,
        avg: Math.round(avgCount * 10) / 10,
      }
    })

    return { chartData: cd, alerts: alertHours }
  }, [today, hist])

  const totalToday = today.reduce((s, r) => s + (r.novation_count ?? 0), 0)

  return (
    <div className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">Novation velocity</span>
        {alerts.length > 0 && (
          <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[9.5px] text-amber-200 ring-1 ring-amber-500/30">
            {alerts.length}h &gt;2× avg
          </span>
        )}
      </div>
      <div className="flex items-baseline gap-3">
        <span className="text-[20px] font-semibold tracking-tight text-amber-200">
          {loading ? '…' : totalToday}
        </span>
        <span className="text-[10px] text-slate-500">novations today</span>
      </div>

      {!loading && chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={140}>
          <ComposedChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={ANALYTICS_COLORS.slate800} />
            <XAxis dataKey="hour" tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} />
            <YAxis tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} />
            <Tooltip
              contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', fontSize: 10, fontFamily: 'monospace' }}
            />
            <Bar dataKey="count" fill="#f59e0b" fillOpacity={0.6} name="Today" />
            <Line type="monotone" dataKey="avg" stroke="#e879f9" strokeWidth={1.5} dot={false} strokeDasharray="4 2" name="20d Avg" />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      {!loading && chartData.length === 0 && (
        <div className="py-2 text-center text-[10px] text-slate-500">No novation data for today.</div>
      )}
    </div>
  )
}
