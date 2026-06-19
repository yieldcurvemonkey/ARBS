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

type MixRow = { package_type: string; total_dv01: number; trade_count: number }
type HourlyRow = { hour: string; package_type: string; dv01: number }

const PKG_COLORS: Record<string, string> = {
  OUTRIGHT: '#38bdf8',
  CURVE: '#f59e0b',
  FLY: '#e879f9',
  SPREADOVER: '#34d399',
  INVOICE: '#f97316',
  MATCHED_MATURITY: '#22d3ee',
  BASIS: '#a78bfa',
  MAC: '#fb7185',
}

function formatDv01(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)}K`
  return v.toFixed(0)
}

export function PackageMixCard(): JSX.Element {
  const [mix, setMix] = useState<MixRow[]>([])
  const [hourly, setHourly] = useState<HourlyRow[]>([])
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/usd-swaps-tape-v2/package-mix')
      if (!res.ok) return
      const json = await res.json()
      setMix(json.mix ?? [])
      setHourly(json.hourly ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const totalDv01 = useMemo(() => mix.reduce((s, r) => s + (r.total_dv01 ?? 0), 0), [mix])

  const { chartData, pkgTypes } = useMemo(() => {
    const hourMap = new Map<string, Record<string, string | number>>()
    const types = new Set<string>()
    for (const r of hourly) {
      types.add(r.package_type)
      const h = new Date(r.hour).toLocaleTimeString('en-US', {
        hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/New_York',
      })
      const existing = hourMap.get(h) ?? { hour: h }
      existing[r.package_type] = r.dv01 ?? 0
      hourMap.set(h, existing)
    }
    return {
      chartData: [...hourMap.values()].sort((a, b) => String(a.hour).localeCompare(String(b.hour))),
      pkgTypes: [...types].sort(),
    }
  }, [hourly])

  return (
    <div className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">Package structure mix</span>
        <span className="text-[10px] text-slate-500">{mix.length} types</span>
      </div>

      {!loading && mix.length > 0 && (
        <div className="flex flex-col gap-1">
          {mix.map(r => {
            const pct = totalDv01 > 0 ? ((r.total_dv01 ?? 0) / totalDv01) * 100 : 0
            return (
              <div key={r.package_type} className="flex items-center gap-2">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: PKG_COLORS[r.package_type] ?? '#64748b' }}
                />
                <span className="w-24 truncate text-[10.5px] text-slate-200">{r.package_type}</span>
                <div className="relative h-1.5 flex-1 rounded bg-slate-800">
                  <div
                    className="absolute inset-y-0 left-0 rounded"
                    style={{
                      width: `${pct.toFixed(1)}%`,
                      backgroundColor: PKG_COLORS[r.package_type] ?? '#64748b',
                      opacity: 0.6,
                    }}
                  />
                </div>
                <span className="w-12 text-right tabular-nums text-slate-300">{formatDv01(r.total_dv01)}</span>
                <span className="w-9 text-right tabular-nums text-slate-500">{pct.toFixed(0)}%</span>
              </div>
            )
          })}
        </div>
      )}

      {!loading && chartData.length > 0 && (
        <div className="mt-1">
          <div className="text-[9.5px] uppercase tracking-wider text-slate-500 mb-1">Intraday trend</div>
          <ResponsiveContainer width="100%" height={120}>
            <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={ANALYTICS_COLORS.slate800} />
              <XAxis dataKey="hour" tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} />
              <YAxis tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} tickFormatter={v => formatDv01(v)} />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', fontSize: 10, fontFamily: 'monospace' }}
                formatter={(v: number) => formatDv01(v)}
              />
              {pkgTypes.map(t => (
                <Bar key={t} dataKey={t} stackId="pkg" fill={PKG_COLORS[t] ?? '#64748b'} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {!loading && mix.length === 0 && (
        <div className="py-2 text-center text-[10px] text-slate-500">No package data for today.</div>
      )}
    </div>
  )
}
