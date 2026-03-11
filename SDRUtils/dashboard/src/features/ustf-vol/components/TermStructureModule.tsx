'use client'

import { useEffect, useMemo, useRef, useState } from 'react'

import { SERIES_COLORS, SWAPTION_EXPIRIES, USTF_EXPIRIES } from '../constants'
import { useUstfTermStructure } from '../hooks/useUstfTermStructure'
import type { AssetType } from '../types'

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

export function TermStructureModule() {
  const [assetType, setAssetType] = useState<AssetType>('swaption')
  const [expiry, setExpiry] = useState('1M')
  const [strikeOffsetBps, setStrikeOffsetBps] = useState(0)
  const [dates, setDates] = useState<string[]>([today()])
  const [dateInput, setDateInput] = useState('')

  const expiries = assetType === 'ustf' ? USTF_EXPIRIES : SWAPTION_EXPIRIES

  const { data, loading, error } = useUstfTermStructure({
    assetType,
    expiry,
    dates,
    strikeOffsetBps,
  })

  const chartRef = useRef<HTMLDivElement>(null)

  const traces = useMemo(() => {
    if (!data?.dates?.length) return []
    return data.dates.map((slice, idx) => ({
      type: 'scatter' as const,
      mode: 'lines+markers' as const,
      name: slice.date,
      x: slice.points.map((p) => p.label),
      y: slice.points.map((p) => p.vol),
      line: { color: SERIES_COLORS[idx % SERIES_COLORS.length], width: 2.5 },
      marker: { size: 7, color: SERIES_COLORS[idx % SERIES_COLORS.length] },
      hovertemplate: `${slice.date}<br>%{x}<br>%{y:.2f} bpvol<extra></extra>`,
    }))
  }, [data])

  useEffect(() => {
    let disposed = false
    let plotly: any = null
    const container = chartRef.current

    const run = async () => {
      const plotlyModule = await import('plotly.js-dist-min')
      plotly = (plotlyModule as any).default ?? plotlyModule
      if (disposed || !container) return

      const layout = {
        template: 'plotly_dark',
        paper_bgcolor: 'rgba(2, 6, 23, 0)',
        plot_bgcolor: 'rgba(2, 6, 23, 0.65)',
        autosize: true,
        height: 420,
        margin: { t: 40, r: 24, b: 54, l: 72 },
        hovermode: 'x unified' as const,
        hoverlabel: {
          bgcolor: 'rgba(15, 23, 42, 0.94)',
          bordercolor: 'rgba(148, 163, 184, 0.25)',
          font: { color: '#e2e8f0', size: 11 },
        },
        legend: {
          orientation: 'h' as const,
          x: 0,
          y: 1.12,
          bgcolor: 'rgba(15, 23, 42, 0.55)',
          bordercolor: 'rgba(148, 163, 184, 0.15)',
          borderwidth: 1,
          font: { color: '#cbd5e1', size: 11 },
        },
        xaxis: {
          type: 'category' as const,
          showline: true,
          linecolor: 'rgba(148, 163, 184, 0.35)',
          tickfont: { color: '#94a3b8', size: 11 },
          gridcolor: 'rgba(148, 163, 184, 0.14)',
          title: assetType === 'ustf' ? 'Product' : 'Tail',
          titlefont: { color: '#94a3b8', size: 11 },
        },
        yaxis: {
          title: 'NVOL (bpvol)',
          showline: true,
          linecolor: 'rgba(148, 163, 184, 0.35)',
          tickfont: { color: '#94a3b8', size: 10 },
          titlefont: { color: '#94a3b8', size: 11 },
          gridcolor: 'rgba(148, 163, 184, 0.14)',
        },
        uirevision: 'ustf-term-structure',
      }

      await plotly.react(container, traces, layout, { responsive: true, displaylogo: false })
    }

    run().catch(console.error)
    return () => {
      disposed = true
      if (plotly && container) {
        try { plotly.purge(container) } catch { /* no-op */ }
      }
    }
  }, [traces, assetType])

  const addDate = () => {
    const d = dateInput.trim()
    if (d && !dates.includes(d) && dates.length < 5) {
      setDates([...dates, d].sort())
      setDateInput('')
    }
  }

  const removeDate = (d: string) => {
    setDates(dates.filter((x) => x !== d))
  }

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-4">
        {/* Asset type toggle */}
        <div className="flex overflow-hidden rounded-lg border border-slate-700">
          {(['ustf', 'swaption'] as AssetType[]).map((t) => (
            <button
              key={t}
              onClick={() => {
                setAssetType(t)
                setExpiry('1M')
              }}
              className={`px-3 py-1.5 text-xs font-semibold ${
                assetType === t
                  ? 'bg-slate-100 text-slate-950'
                  : 'bg-slate-900/70 text-slate-300 hover:text-white'
              }`}
            >
              {t === 'ustf' ? 'USTF' : 'Swaption'}
            </button>
          ))}
        </div>

        {/* Expiry */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">Expiry</span>
          <select
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-900/70 px-2 py-1.5 text-xs text-slate-200"
          >
            {expiries.map((e) => (
              <option key={e} value={e}>{e}</option>
            ))}
          </select>
        </div>

        {/* Strike offset */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">Strike Offset (bps)</span>
          <input
            type="number"
            value={strikeOffsetBps}
            onChange={(e) => setStrikeOffsetBps(Number(e.target.value) || 0)}
            className="w-20 rounded-lg border border-slate-700 bg-slate-900/70 px-2 py-1.5 text-xs text-slate-200"
          />
        </div>
      </div>

      {/* Date picker */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-slate-400">Dates</span>
        {dates.map((d) => (
          <span
            key={d}
            className="flex items-center gap-1 rounded-full border border-slate-700 bg-slate-900/70 px-2.5 py-1 text-xs text-slate-200"
          >
            {d}
            <button
              onClick={() => removeDate(d)}
              className="ml-0.5 text-slate-500 hover:text-white"
            >
              x
            </button>
          </span>
        ))}
        {dates.length < 5 && (
          <div className="flex items-center gap-1">
            <input
              type="date"
              value={dateInput}
              onChange={(e) => setDateInput(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-900/70 px-2 py-1 text-xs text-slate-200"
            />
            <button
              onClick={addDate}
              className="rounded-lg border border-slate-700 bg-slate-900/70 px-2 py-1 text-xs text-sky-400 hover:text-sky-300"
            >
              Add
            </button>
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-xl border border-rose-800/50 bg-rose-950/30 px-4 py-2 text-sm text-rose-300">
          {error}
        </div>
      )}

      <div className="relative">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-950/50 backdrop-blur-sm">
            <div className="text-sm text-slate-400">Loading...</div>
          </div>
        )}
        <div ref={chartRef} style={{ height: 420 }} className="w-full" />
      </div>
    </div>
  )
}
