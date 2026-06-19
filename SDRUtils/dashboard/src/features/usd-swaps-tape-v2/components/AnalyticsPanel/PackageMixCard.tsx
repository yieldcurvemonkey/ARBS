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

type Row = { day: string; package_type: string; dv01: number; trade_count: number }

const PKG_COLORS: Record<string, string> = {
  OUTRIGHT: '#38bdf8', CURVE: '#f59e0b', FLY: '#e879f9', SPREADOVER: '#34d399',
  INVOICE: '#f97316', MATCHED_MATURITY: '#22d3ee', BASIS: '#a78bfa', MAC: '#fb7185',
}

function formatDv01(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)}K`
  return v.toFixed(0)
}

export function PackageMixCard(): JSX.Element {
  const [data, setData] = useState<Row[]>([])
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/usd-swaps-tape-v2/package-mix?days=30')
      if (!res.ok) return
      const json = await res.json()
      setData(json.rows ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const { chartData, pkgTypes } = useMemo(() => {
    const dayMap = new Map<string, Record<string, string | number>>()
    const types = new Set<string>()
    for (const r of data) {
      types.add(r.package_type)
      const d = r.day.slice(0, 10)
      const existing = dayMap.get(d) ?? { day: d }
      existing[r.package_type] = (Number(existing[r.package_type]) || 0) + (r.dv01 ?? 0)
      dayMap.set(d, existing)
    }
    return {
      chartData: [...dayMap.values()].sort((a, b) => String(a.day).localeCompare(String(b.day))),
      pkgTypes: [...types].sort((a, b) => {
        const totA = data.filter(r => r.package_type === a).reduce((s, r) => s + r.dv01, 0)
        const totB = data.filter(r => r.package_type === b).reduce((s, r) => s + r.dv01, 0)
        return totB - totA
      }),
    }
  }, [data])

  const totalsByType = useMemo(() => {
    const m: Record<string, number> = {}
    for (const r of data) m[r.package_type] = (m[r.package_type] ?? 0) + (r.dv01 ?? 0)
    return m
  }, [data])

  const grandTotal = Object.values(totalsByType).reduce((s, v) => s + v, 0)

  return (
    <div className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">Package mix trend (30d)</span>
      </div>

      {!loading && pkgTypes.length > 0 && (
        <div className="flex flex-col gap-1">
          {pkgTypes.slice(0, 6).map(t => {
            const pct = grandTotal > 0 ? ((totalsByType[t] ?? 0) / grandTotal) * 100 : 0
            return (
              <div key={t} className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: PKG_COLORS[t] ?? '#64748b' }} />
                <span className="w-24 truncate text-[10.5px] text-slate-200">{t}</span>
                <div className="relative h-1.5 flex-1 rounded bg-slate-800">
                  <div className="absolute inset-y-0 left-0 rounded" style={{ width: `${pct.toFixed(1)}%`, backgroundColor: PKG_COLORS[t] ?? '#64748b', opacity: 0.6 }} />
                </div>
                <span className="w-12 text-right tabular-nums text-slate-300">{formatDv01(totalsByType[t])}</span>
                <span className="w-9 text-right tabular-nums text-slate-500">{pct.toFixed(0)}%</span>
              </div>
            )
          })}
        </div>
      )}

      {!loading && chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={140}>
          <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={ANALYTICS_COLORS.slate800} />
            <XAxis dataKey="day" tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} tickFormatter={v => v.slice(5)} />
            <YAxis tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} tickFormatter={v => formatDv01(v)} />
            <Tooltip contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', fontSize: 10, fontFamily: 'monospace' }} formatter={(v: number) => formatDv01(v)} />
            {pkgTypes.map(t => (
              <Bar key={t} dataKey={t} stackId="pkg" fill={PKG_COLORS[t] ?? '#64748b'} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )}

      {!loading && data.length === 0 && (
        <div className="py-2 text-center text-[10px] text-slate-500">No package data in window.</div>
      )}
    </div>
  )
}
