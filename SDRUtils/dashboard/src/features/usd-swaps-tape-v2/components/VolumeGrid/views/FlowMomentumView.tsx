'use client'
import type { JSX } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ViewProps } from '../../../types/volume-grid-views.types'

type ActivityCell = {
  fwd: string
  tenor: string
  dv01: number
  trade_count: number
  hist_avg: number
  hist_std: number
  z_score: number
}

type BucketLabel = { id: string; label: string }

type WindowId = '1h' | '4h' | 'today' | '5d'

const WINDOWS: Array<{ id: WindowId; label: string }> = [
  { id: '1h', label: '1H' },
  { id: '4h', label: '4H' },
  { id: 'today', label: 'Today' },
  { id: '5d', label: '5D' },
]

const CORE_TENORS = new Set([
  '2y', '3y', '5y', '10y', '15y_20y', '20y_25y', '30y_plus',
  '1y_18m', '18m_2y', '4y', '6y_7y', '8y_9y', '10y_12y', '12y_15y',
])

function formatDv01(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return ''
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)}K`
  if (Math.abs(v) < 1) return ''
  return v.toFixed(0)
}

function zScoreColor(z: number): string {
  if (z > 2) return 'rgba(56, 189, 248, 0.50)'
  if (z > 1) return 'rgba(56, 189, 248, 0.30)'
  if (z > 0.5) return 'rgba(56, 189, 248, 0.15)'
  if (z < -2) return 'rgba(100, 116, 139, 0.40)'
  if (z < -1) return 'rgba(100, 116, 139, 0.25)'
  if (z < -0.5) return 'rgba(100, 116, 139, 0.12)'
  return 'rgba(30, 41, 59, 0.5)'
}

function rawIntensityColor(dv01: number, maxDv01: number): string {
  if (maxDv01 <= 0 || dv01 <= 0) return 'rgba(30, 41, 59, 0.3)'
  const intensity = Math.min(dv01 / maxDv01, 1)
  return `rgba(56, 189, 248, ${(0.08 + intensity * 0.50).toFixed(2)})`
}

function zBadge(z: number): { text: string; cls: string } {
  if (Math.abs(z) < 0.3) return { text: '', cls: '' }
  const sign = z > 0 ? '+' : ''
  const text = `${sign}${z.toFixed(1)}σ`
  if (z > 1.5) return { text, cls: 'text-sky-300 font-semibold' }
  if (z > 0.5) return { text, cls: 'text-sky-400' }
  if (z < -1.5) return { text, cls: 'text-slate-400' }
  if (z < -0.5) return { text, cls: 'text-slate-500' }
  return { text, cls: 'text-slate-500' }
}

export function FlowMomentumView(_props: ViewProps): JSX.Element {
  const [cells, setCells] = useState<ActivityCell[]>([])
  const [fwdBuckets, setFwdBuckets] = useState<BucketLabel[]>([])
  const [tenorBuckets, setTenorBuckets] = useState<BucketLabel[]>([])
  const [loading, setLoading] = useState(true)
  const [window, setWindow] = useState<WindowId>('today')
  const [colorMode, setColorMode] = useState<'zscore' | 'raw'>('zscore')

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`/api/usd-swaps-tape-v2/flow-momentum?window=${window}`)
      if (!res.ok) return
      const json = await res.json()
      setCells(json.cells ?? [])
      setFwdBuckets(json.fwdBuckets ?? [])
      setTenorBuckets(json.tenorBuckets ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [window])

  useEffect(() => { fetchData() }, [fetchData])

  const cellMap = useMemo(() => {
    const m = new Map<string, ActivityCell>()
    for (const c of cells) m.set(`${c.fwd}|${c.tenor}`, c)
    return m
  }, [cells])

  const maxDv01 = useMemo(() => Math.max(...cells.map(c => c.dv01), 0), [cells])

  const visibleTenors = useMemo(() => {
    const withData = new Set(cells.map(c => c.tenor))
    return tenorBuckets.filter(t => withData.has(t.id) || CORE_TENORS.has(t.id))
  }, [tenorBuckets, cells])

  const visibleFwds = useMemo(() => {
    const withData = new Set(cells.map(c => c.fwd))
    return fwdBuckets.filter(f => withData.has(f.id))
  }, [fwdBuckets, cells])

  const fwdTotals = useMemo(() => {
    const m: Record<string, number> = {}
    for (const c of cells) m[c.fwd] = (m[c.fwd] ?? 0) + c.dv01
    return m
  }, [cells])

  const tenorTotals = useMemo(() => {
    const m: Record<string, number> = {}
    for (const c of cells) m[c.tenor] = (m[c.tenor] ?? 0) + c.dv01
    return m
  }, [cells])

  const grandTotal = cells.reduce((s, c) => s + c.dv01, 0)
  const totalTrades = cells.reduce((s, c) => s + c.trade_count, 0)

  function cellBg(cell: ActivityCell | undefined): string {
    if (!cell) return 'rgba(30, 41, 59, 0.3)'
    if (colorMode === 'zscore') return zScoreColor(cell.z_score)
    return rawIntensityColor(cell.dv01, maxDv01)
  }

  return (
    <div className="p-3 font-mono text-[11px]">
      <div className="mb-2 flex items-center gap-3">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">Flow Activity</span>
        <div className="flex items-center rounded border border-slate-700 p-[1px]">
          {WINDOWS.map(w => (
            <button
              key={w.id}
              type="button"
              onClick={() => setWindow(w.id)}
              className={`px-2 py-[1px] text-[10.5px] ${window === w.id ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
            >
              {w.label}
            </button>
          ))}
        </div>
        <div className="flex items-center rounded border border-slate-700 p-[1px]">
          <button
            type="button"
            onClick={() => setColorMode('zscore')}
            className={`px-2 py-[1px] text-[10.5px] ${colorMode === 'zscore' ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
          >
            Z-Score
          </button>
          <button
            type="button"
            onClick={() => setColorMode('raw')}
            className={`px-2 py-[1px] text-[10.5px] ${colorMode === 'raw' ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
          >
            Raw
          </button>
        </div>
        <span className="text-[12px] tabular-nums text-sky-300">
          {formatDv01(grandTotal)} DV01
        </span>
        <span className="text-[10px] text-slate-500">{totalTrades} trades</span>
        {loading && <span className="text-[10px] text-sky-300">loading…</span>}
      </div>

      {visibleFwds.length > 0 && visibleTenors.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="sticky left-0 z-10 bg-slate-950 px-2 py-1 text-left text-[9.5px] uppercase tracking-wider text-slate-500">
                  Fwd \ Tenor
                </th>
                {visibleTenors.map(t => (
                  <th key={t.id} className="px-1.5 py-1 text-center text-[9.5px] uppercase tracking-wider text-slate-500">
                    {t.label}
                  </th>
                ))}
                <th className="px-1.5 py-1 text-center text-[9.5px] uppercase tracking-wider text-amber-500/80">
                  Total
                </th>
              </tr>
            </thead>
            <tbody>
              {visibleFwds.map(f => (
                <tr key={f.id} className="border-t border-slate-800/50">
                  <td className="sticky left-0 z-10 bg-slate-950 px-2 py-1 text-[10px] text-slate-300 whitespace-nowrap">
                    {f.label}
                  </td>
                  {visibleTenors.map(t => {
                    const cell = cellMap.get(`${f.id}|${t.id}`)
                    const badge = cell ? zBadge(cell.z_score) : { text: '', cls: '' }
                    return (
                      <td
                        key={t.id}
                        className="px-1 py-1 text-center"
                        style={{ backgroundColor: cellBg(cell) }}
                        title={cell
                          ? `${f.label} × ${t.label}\nDV01: ${formatDv01(cell.dv01)} (${cell.trade_count} trades)\nZ: ${cell.z_score.toFixed(2)}σ vs 20d avg\nHist avg: ${formatDv01(cell.hist_avg)}`
                          : `${f.label} × ${t.label}: no activity`
                        }
                      >
                        {cell ? (
                          <div className="flex flex-col items-center gap-0">
                            <span className="tabular-nums text-[10px] text-slate-200">
                              {formatDv01(cell.dv01)}
                            </span>
                            {badge.text && (
                              <span className={`text-[8.5px] tabular-nums ${badge.cls}`}>{badge.text}</span>
                            )}
                          </div>
                        ) : null}
                      </td>
                    )
                  })}
                  <td className="px-1 py-1 text-center border-l border-slate-700/50">
                    <span className="tabular-nums text-[10px] text-sky-300">
                      {formatDv01(fwdTotals[f.id])}
                    </span>
                  </td>
                </tr>
              ))}
              <tr className="border-t border-slate-700">
                <td className="sticky left-0 z-10 bg-slate-950 px-2 py-1 text-[9.5px] uppercase tracking-wider text-amber-500/80">
                  Total
                </td>
                {visibleTenors.map(t => (
                  <td key={t.id} className="px-1 py-1 text-center border-t border-slate-700/50">
                    <span className="tabular-nums text-[10px] text-sky-300">
                      {formatDv01(tenorTotals[t.id])}
                    </span>
                  </td>
                ))}
                <td className="px-1 py-1 text-center border-l border-t border-slate-700/50">
                  <span className="tabular-nums text-[10px] font-semibold text-sky-200">
                    {formatDv01(grandTotal)}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      ) : !loading ? (
        <div className="py-8 text-center text-[10px] text-slate-500">No flow data for this window.</div>
      ) : null}

      <div className="mt-2 flex items-center gap-4 text-[9px] text-slate-500">
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-4 rounded" style={{ backgroundColor: 'rgba(56, 189, 248, 0.50)' }} />&gt;2σ above avg</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-4 rounded" style={{ backgroundColor: 'rgba(56, 189, 248, 0.30)' }} />1-2σ above</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-4 rounded" style={{ backgroundColor: 'rgba(30, 41, 59, 0.5)' }} />typical</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-4 rounded" style={{ backgroundColor: 'rgba(100, 116, 139, 0.25)' }} />1-2σ below</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-4 rounded" style={{ backgroundColor: 'rgba(100, 116, 139, 0.40)' }} />&gt;2σ below</span>
        <span className="ml-auto">gross DV01 vs 20d avg · {colorMode === 'zscore' ? 'z-score coloring' : 'intensity coloring'} · no directional info (P43 unsigned)</span>
      </div>
    </div>
  )
}
