'use client'
import type { JSX } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'

type Row = { hour_et: number; tenor_label: string; avg_block_dv01: number; avg_trade_count: number; n_days: number }

const TENORS = ['2Y', '3Y', '5Y', '7Y', '10Y', '15Y', '20Y', '30Y']

function formatDv01(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)}K`
  return v.toFixed(0)
}

function heatColor(value: number, max: number): string {
  if (max <= 0 || value <= 0) return 'rgba(30, 41, 59, 0.5)'
  const intensity = Math.min(value / max, 1)
  return `rgba(245, 158, 11, ${(0.15 + intensity * 0.75).toFixed(2)})`
}

export function BlockHeatmapCard(): JSX.Element {
  const [rows, setRows] = useState<Row[]>([])
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/usd-swaps-tape-v2/block-heatmap?days=20')
      if (!res.ok) return
      const json = await res.json()
      setRows(json.rows ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const { grid, maxVal, hours, nDays } = useMemo(() => {
    const g: Record<number, Record<string, number>> = {}
    let max = 0
    const hourSet = new Set<number>()
    let days = 0
    for (const r of rows) {
      hourSet.add(r.hour_et)
      if (!g[r.hour_et]) g[r.hour_et] = {}
      const val = Number(r.avg_block_dv01) || 0
      g[r.hour_et][r.tenor_label] = val
      if (val > max) max = val
      if ((Number(r.n_days) || 0) > days) days = Number(r.n_days) || 0
    }
    const hrs = [...hourSet].sort((a, b) => a - b)
    if (hrs.length === 0) for (let i = 6; i <= 18; i++) hrs.push(i)
    return { grid: g, maxVal: max, hours: hrs, nDays: days }
  }, [rows])

  return (
    <div className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">Block trade heatmap (20d avg)</span>
        <span className="text-[10px] text-slate-500">{nDays} days</span>
      </div>
      {loading ? (
        <div className="py-4 text-center text-[10px] text-slate-500">Loading…</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[9.5px]">
            <thead>
              <tr>
                <th className="px-1 py-0.5 text-left text-slate-500">ET</th>
                {TENORS.map(t => <th key={t} className="px-1 py-0.5 text-center text-slate-500">{t}</th>)}
              </tr>
            </thead>
            <tbody>
              {hours.map(h => (
                <tr key={h}>
                  <td className="px-1 py-0.5 text-slate-400">{String(h).padStart(2, '0')}:00</td>
                  {TENORS.map(t => {
                    const val = grid[h]?.[t] ?? 0
                    return (
                      <td
                        key={t}
                        className="px-1 py-0.5 text-center tabular-nums"
                        style={{ backgroundColor: heatColor(val, maxVal) }}
                        title={`${t} @ ${h}:00 ET — avg ${formatDv01(val)}/day`}
                      >
                        {val > 0 ? formatDv01(val) : ''}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
