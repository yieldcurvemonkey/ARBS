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

type RiskRow = {
  hour: string
  tenor_label: string
  net_risk: number
  gross_risk: number
  trade_count: number
}

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

function formatDv01(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)}K`
  return v.toFixed(0)
}

export function NetNewRiskCard(): JSX.Element {
  const [data, setData] = useState<RiskRow[]>([])
  const [loading, setLoading] = useState(true)
  const [useGross, setUseGross] = useState(false)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/usd-swaps-tape-v2/net-new-risk')
      if (!res.ok) return
      const json = await res.json()
      setData(json.rows ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const { chartData, tenors } = useMemo(() => {
    const hourMap = new Map<string, Record<string, string | number>>()
    const tenorSet = new Set<string>()
    for (const r of data) {
      tenorSet.add(r.tenor_label)
      const h = new Date(r.hour).toLocaleTimeString('en-US', {
        hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/New_York',
      })
      const existing = hourMap.get(h) ?? { hour: h }
      existing[r.tenor_label] = useGross ? (r.gross_risk ?? 0) : (r.net_risk ?? 0)
      hourMap.set(h, existing)
    }
    return {
      chartData: [...hourMap.values()].sort((a, b) => String(a.hour).localeCompare(String(b.hour))),
      tenors: [...tenorSet].sort(),
    }
  }, [data, useGross])

  const totalDv01 = useMemo(
    () => data.reduce((s, r) => s + (useGross ? (r.gross_risk ?? 0) : (r.net_risk ?? 0)), 0),
    [data, useGross],
  )

  return (
    <div className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">
          Net new risk strip
        </span>
        <button
          type="button"
          onClick={() => setUseGross(v => !v)}
          className={`rounded border px-1.5 py-0.5 text-[10px] ${
            useGross
              ? 'border-amber-400 bg-amber-500/20 text-amber-200'
              : 'border-slate-700 text-slate-400'
          }`}
        >
          {useGross ? 'Gross' : 'Net'}
        </button>
      </div>
      <div className="flex items-baseline gap-3">
        <span className="text-[20px] font-semibold tracking-tight text-emerald-200">
          {loading ? '…' : formatDv01(totalDv01)}
        </span>
        <span className="text-[10px] text-slate-500">total {useGross ? 'gross' : 'net'} DV01</span>
      </div>
      {!loading && chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={ANALYTICS_COLORS.slate800} />
            <XAxis dataKey="hour" tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} />
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
        <div className="py-4 text-center text-[10px] text-slate-500">No flow data for today.</div>
      )}
    </div>
  )
}
