'use client'
import type { JSX } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'

type HeatRow = { hour_et: number; tenor_label: string; block_dv01?: number; avg_block_dv01?: number; trade_count?: number }

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
  const [today, setToday] = useState<HeatRow[]>([])
  const [hist, setHist] = useState<HeatRow[]>([])
  const [loading, setLoading] = useState(true)
  const [showHist, setShowHist] = useState(false)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/usd-swaps-tape-v2/block-heatmap')
      if (!res.ok) return
      const json = await res.json()
      setToday(json.today ?? [])
      setHist(json.historical ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const { grid, maxVal, hours } = useMemo(() => {
    const source = showHist ? hist : today
    const g: Record<string, Record<string, number>> = {}
    let max = 0
    const hourSet = new Set<number>()
    for (const r of source) {
      const h = r.hour_et
      hourSet.add(h)
      if (!g[h]) g[h] = {}
      const val = showHist ? (r.avg_block_dv01 ?? 0) : (r.block_dv01 ?? 0)
      g[h][r.tenor_label] = val
      if (val > max) max = val
    }
    const hrs = [...hourSet].sort((a, b) => a - b)
    if (hrs.length === 0) for (let i = 6; i <= 18; i++) hrs.push(i)
    return { grid: g, maxVal: max, hours: hrs }
  }, [today, hist, showHist])

  return (
    <div className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">Block trade heatmap</span>
        <button
          type="button"
          onClick={() => setShowHist(v => !v)}
          className={`rounded border px-1.5 py-0.5 text-[10px] ${
            showHist ? 'border-sky-400 bg-sky-500/20 text-sky-200' : 'border-slate-700 text-slate-400'
          }`}
        >
          {showHist ? '20d Avg' : 'Today'}
        </button>
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
                        title={`${t} @ ${h}:00 ET — ${formatDv01(val)}`}
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
