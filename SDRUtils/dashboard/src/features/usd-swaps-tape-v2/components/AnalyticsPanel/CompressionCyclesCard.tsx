'use client'
import type { JSX } from 'react'
import { useCallback, useEffect, useState } from 'react'

type Cycle = {
  cluster_id: number
  window_start: string
  window_end: string
  trade_count: number
  total_notional: number
  total_dv01: number
  duration_seconds: number
}

function formatDv01(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)}K`
  return v.toFixed(0)
}

function formatNotional(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`
  if (v >= 1e6) return `${(v / 1e6).toFixed(0)}M`
  return formatDv01(v)
}

function fmtTime(ts: string): string {
  return new Date(ts).toLocaleTimeString('en-US', {
    hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/New_York',
  })
}

export function CompressionCyclesCard(): JSX.Element {
  const [cycles, setCycles] = useState<Cycle[]>([])
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/usd-swaps-tape-v2/compression-cycles')
      if (!res.ok) return
      const json = await res.json()
      setCycles(json.cycles ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const latestCycle = cycles.length > 0 ? cycles[cycles.length - 1] : null
  const isActive = latestCycle
    ? (Date.now() - new Date(latestCycle.window_end).getTime()) < 15 * 60 * 1000
    : false

  return (
    <div className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">
          Compression cycles
        </span>
        {isActive && (
          <span className="flex items-center gap-1 rounded bg-rose-500/20 px-1.5 py-0.5 text-[9.5px] text-rose-200 ring-1 ring-rose-500/30">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-rose-400" />
            ACTIVE
          </span>
        )}
      </div>
      <div className="flex items-baseline gap-3">
        <span className="text-[20px] font-semibold tracking-tight text-rose-200">
          {loading ? '…' : cycles.length}
        </span>
        <span className="text-[10px] text-slate-500">cycles detected today</span>
      </div>
      {!loading && cycles.length > 0 ? (
        <div className="flex flex-col gap-1 max-h-[200px] overflow-y-auto">
          {cycles.map(c => (
            <div key={c.cluster_id} className="flex items-center justify-between rounded border border-slate-800 bg-slate-900/40 px-2 py-1">
              <div className="flex flex-col">
                <span className="text-[10px] text-slate-200">
                  {fmtTime(c.window_start)} – {fmtTime(c.window_end)} ET
                </span>
                <span className="text-[9.5px] text-slate-500">
                  {c.trade_count ?? 0} trades · {Math.round((c.duration_seconds ?? 0) / 60)}min
                </span>
              </div>
              <div className="flex flex-col items-end">
                <span className="text-[10.5px] tabular-nums text-slate-200">{formatDv01(c.total_dv01)}</span>
                <span className="text-[9.5px] text-slate-500">{formatNotional(c.total_notional)} notl</span>
              </div>
            </div>
          ))}
        </div>
      ) : !loading ? (
        <div className="py-2 text-center text-[10px] text-slate-500">No compression bursts detected today.</div>
      ) : null}
    </div>
  )
}
