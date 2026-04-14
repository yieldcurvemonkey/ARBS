'use client'
// ABOUTME: Quadrant flow-history grid modal for the USD swap tape v2.
import type { JSX } from 'react'
import { useEffect, useState } from 'react'
import { Dialog } from 'primereact/dialog'
import { TAPE_V2_API_BASE } from '../../constants'
import { formatDv01, formatNotional } from '../../utils/format'

type Stats = {
  tradeCount: number
  grossNotional: number
  grossRisk: number
  avgFixedRate: number | null
  idbTradeCount: number
  custyTradeCount: number
}
type Day = {
  date: string
  quadrants: {
    frontShort: Stats
    frontLong: Stats
    forwardShort: Stats
    forwardLong: Stats
  }
  boundary: Stats
  unknown: Stats
  gridTotal: Stats
}

export interface FlowHistoryGridProps {
  open: boolean
  onClose: () => void
  start: string
  end: string
  forwardBoundary?: number
  tenorBoundary?: number
  tolerance?: number
}

export function FlowHistoryGrid(props: FlowHistoryGridProps): JSX.Element {
  const [days, setDays] = useState<Day[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!props.open) return
    const controller = new AbortController()
    async function fetchData() {
      setLoading(true)
      setError(null)
      try {
        const q = new URLSearchParams({
          start: props.start,
          end: props.end,
          forwardBoundary: String(props.forwardBoundary ?? 2),
          tenorBoundary: String(props.tenorBoundary ?? 5),
          tolerance: String(props.tolerance ?? 0.25),
          platform: 'combined',
        })
        const res = await fetch(`${TAPE_V2_API_BASE}/flow-history?${q}`, {
          signal: controller.signal,
        })
        if (!res.ok) throw new Error(`flow-history failed: ${res.statusText}`)
        const data = await res.json()
        setDays(data.days ?? [])
      } catch (e) {
        if ((e as any)?.name === 'AbortError') return
        setError(e instanceof Error ? e.message : 'failed')
      } finally {
        setLoading(false)
      }
    }
    fetchData()
    return () => controller.abort()
  }, [
    props.open,
    props.start,
    props.end,
    props.forwardBoundary,
    props.tenorBoundary,
    props.tolerance,
  ])

  return (
    <Dialog
      header="Flow history"
      visible={props.open}
      onHide={props.onClose}
      style={{ width: '80vw', maxWidth: 1200 }}
      modal
    >
      {loading ? <p className="text-slate-400 text-sm">Loading…</p> : null}
      {error ? <p className="text-red-300 text-sm">{error}</p> : null}
      {!loading && !error && days.length === 0 ? (
        <p className="text-slate-500 text-sm">No flow data in the selected window.</p>
      ) : null}
      <div className="flex flex-col gap-2">
        {days.map((d) => (
          <div key={d.date} className="rounded border border-slate-800 p-2">
            <div className="flex items-center justify-between">
              <span className="font-mono text-slate-200">{d.date}</span>
              <span className="text-xs text-slate-400">
                {d.gridTotal.tradeCount} trades · {formatDv01(d.gridTotal.grossRisk)}
              </span>
            </div>
            <div className="grid grid-cols-4 gap-2 mt-2 text-xs">
              {(['frontShort', 'frontLong', 'forwardShort', 'forwardLong'] as const).map(
                (q) => (
                  <div
                    key={q}
                    className="rounded bg-slate-900 border border-slate-800 p-2"
                  >
                    <div className="text-[10px] uppercase text-slate-400">{q}</div>
                    <div>{d.quadrants[q].tradeCount} trades</div>
                    <div>{formatDv01(d.quadrants[q].grossRisk)}</div>
                    <div>{formatNotional(d.quadrants[q].grossNotional, { compact: true })}</div>
                  </div>
                ),
              )}
            </div>
          </div>
        ))}
      </div>
    </Dialog>
  )
}
