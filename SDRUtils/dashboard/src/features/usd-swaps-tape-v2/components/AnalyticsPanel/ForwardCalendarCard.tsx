'use client'
import type { JSX } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'

type CalendarRow = {
  effective_date: string
  month: string
  is_fomc_dated: boolean
  fomc_meeting_label: string | null
  tenor_label: string | null
  total_dv01: number
  trade_count: number
  total_notional: number
}

function formatDv01(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)}K`
  return v.toFixed(0)
}

function fmtDate(d: string): string {
  return new Date(d).toLocaleDateString('en-US', {
    month: 'short', day: '2-digit', timeZone: 'UTC',
  })
}

function fmtMonth(d: string): string {
  return new Date(d).toLocaleDateString('en-US', {
    year: 'numeric', month: 'short', timeZone: 'UTC',
  })
}

export function ForwardCalendarCard(): JSX.Element {
  const [rows, setRows] = useState<CalendarRow[]>([])
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/usd-swaps-tape-v2/forward-calendar')
      if (!res.ok) return
      const json = await res.json()
      setRows(json.rows ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const grouped = useMemo(() => {
    const dateMap = new Map<string, {
      effective_date: string
      is_fomc: boolean
      fomc_label: string | null
      total_dv01: number
      trade_count: number
      total_notional: number
    }>()
    for (const r of rows) {
      const d = r.effective_date.slice(0, 10)
      const existing = dateMap.get(d)
      if (existing) {
        existing.total_dv01 += (r.total_dv01 ?? 0)
        existing.trade_count += (r.trade_count ?? 0)
        existing.total_notional += (r.total_notional ?? 0)
        if (r.is_fomc_dated) existing.is_fomc = true
        if (r.fomc_meeting_label) existing.fomc_label = r.fomc_meeting_label
      } else {
        dateMap.set(d, {
          effective_date: d,
          is_fomc: r.is_fomc_dated ?? false,
          fomc_label: r.fomc_meeting_label,
          total_dv01: r.total_dv01 ?? 0,
          trade_count: r.trade_count ?? 0,
          total_notional: r.total_notional ?? 0,
        })
      }
    }
    return [...dateMap.values()].sort((a, b) => a.effective_date.localeCompare(b.effective_date))
  }, [rows])

  const fomcCount = grouped.filter(g => g.is_fomc).length

  return (
    <div className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">Forward-start calendar</span>
        {fomcCount > 0 && (
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[9.5px] text-amber-200 ring-1 ring-amber-500/30">
            {fomcCount} FOMC-dated
          </span>
        )}
      </div>
      {loading ? (
        <div className="py-4 text-center text-[10px] text-slate-500">Loading…</div>
      ) : grouped.length > 0 ? (
        <div className="flex flex-col gap-0.5 max-h-[220px] overflow-y-auto">
          {grouped.map(g => (
            <div
              key={g.effective_date}
              className={`flex items-center justify-between rounded px-2 py-1 ${
                g.is_fomc ? 'border border-amber-500/30 bg-amber-500/10' : 'bg-slate-900/40'
              }`}
            >
              <div className="flex flex-col">
                <span className="text-[10.5px] text-slate-200">
                  {fmtDate(g.effective_date)}
                  {g.is_fomc && <span className="ml-1 text-amber-300">FOMC</span>}
                </span>
                {g.fomc_label && (
                  <span className="text-[9px] text-amber-400">{g.fomc_label}</span>
                )}
                <span className="text-[9.5px] text-slate-500">{g.trade_count} trades</span>
              </div>
              <div className="flex flex-col items-end">
                <span className="tabular-nums text-slate-200">{formatDv01(g.total_dv01)}</span>
                <span className="text-[9.5px] text-slate-500">DV01</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="py-2 text-center text-[10px] text-slate-500">No forward-starts in window.</div>
      )}
    </div>
  )
}
