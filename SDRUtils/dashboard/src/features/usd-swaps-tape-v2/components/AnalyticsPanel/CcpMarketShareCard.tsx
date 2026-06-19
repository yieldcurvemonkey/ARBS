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

type ShareRow = { ccp: string; tenor_label: string; dv01: number; trade_count: number }
type SwitchRow = { as_of_date: string; switch_from: string; switch_to: string; switch_count: number; switch_dv01: number }
type DailyRow = { day: string; ccp: string; dv01: number }

const CCP_COLORS: Record<string, string> = {
  LCH: '#38bdf8',
  CME: '#f59e0b',
  UNKNOWN: '#64748b',
}

function formatDv01(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)}K`
  return v.toFixed(0)
}

export function CcpMarketShareCard(): JSX.Element {
  const [share, setShare] = useState<ShareRow[]>([])
  const [switches, setSwitches] = useState<SwitchRow[]>([])
  const [daily, setDaily] = useState<DailyRow[]>([])
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/usd-swaps-tape-v2/ccp-market-share')
      if (!res.ok) return
      const json = await res.json()
      setShare(json.share ?? [])
      setSwitches(json.switches ?? [])
      setDaily(json.daily ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const ccpTotals = useMemo(() => {
    const m: Record<string, number> = {}
    for (const r of share) m[r.ccp] = (m[r.ccp] ?? 0) + (r.dv01 ?? 0)
    return m
  }, [share])

  const totalDv01 = Object.values(ccpTotals).reduce((s, v) => s + v, 0)

  const dailyChart = useMemo(() => {
    const dayMap = new Map<string, Record<string, string | number>>()
    for (const r of daily) {
      const d = r.day.slice(0, 10)
      const existing = dayMap.get(d) ?? { day: d }
      existing[r.ccp] = r.dv01 ?? 0
      dayMap.set(d, existing)
    }
    return [...dayMap.values()].sort((a, b) => String(a.day).localeCompare(String(b.day)))
  }, [daily])

  const ccps = Object.keys(ccpTotals).sort()

  const todaySwitches = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10)
    return switches.filter(s => s.as_of_date.slice(0, 10) === today)
  }, [switches])

  return (
    <div className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">CCP market share</span>
      </div>
      <div className="flex gap-4">
        {ccps.map(ccp => (
          <div key={ccp} className="flex items-baseline gap-1">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: CCP_COLORS[ccp] ?? '#64748b' }} />
            <span className="text-[10.5px] text-slate-200">{ccp}</span>
            <span className="tabular-nums text-slate-300">{formatDv01(ccpTotals[ccp] ?? 0)}</span>
            <span className="text-[9.5px] text-slate-500">
              {totalDv01 > 0 ? `${(((ccpTotals[ccp] ?? 0) / totalDv01) * 100).toFixed(0)}%` : ''}
            </span>
          </div>
        ))}
      </div>

      {todaySwitches.length > 0 && (
        <div className="text-[10px] text-purple-200">
          {todaySwitches.reduce((s, r) => s + (r.switch_count ?? 0), 0)} CCP switches today
          ({formatDv01(todaySwitches.reduce((s, r) => s + (r.switch_dv01 ?? 0), 0))} DV01)
        </div>
      )}

      {!loading && dailyChart.length > 0 && (
        <ResponsiveContainer width="100%" height={120}>
          <BarChart data={dailyChart} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={ANALYTICS_COLORS.slate800} />
            <XAxis
              dataKey="day"
              tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }}
              tickFormatter={v => v.slice(5)}
            />
            <YAxis tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} tickFormatter={v => formatDv01(v)} />
            <Tooltip
              contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', fontSize: 10, fontFamily: 'monospace' }}
              formatter={(v: number) => formatDv01(v)}
              labelFormatter={l => l}
            />
            {ccps.map(ccp => (
              <Bar key={ccp} dataKey={ccp} stackId="ccp" fill={CCP_COLORS[ccp] ?? '#64748b'} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
