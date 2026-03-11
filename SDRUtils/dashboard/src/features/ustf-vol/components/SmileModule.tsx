'use client'

import { useEffect, useMemo, useRef, useState } from 'react'

import {
  SERIES_COLORS,
  SWAPTION_EXPIRIES,
  SWAPTION_TAILS,
  USTF_EXPIRIES,
  USTF_PRODUCTS,
} from '../constants'
import { useUstfSmile } from '../hooks/useUstfSmile'
import type { AssetType, SmileXAxis, UstfProduct, SwaptionTail } from '../types'

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

export function SmileModule() {
  const [assetType, setAssetType] = useState<AssetType>('ustf')
  const [product, setProduct] = useState<UstfProduct>('TY')
  const [tail, setTail] = useState<SwaptionTail>('7Y')
  const [expiry, setExpiry] = useState('1M')
  const [xAxis, setXAxis] = useState<SmileXAxis>('strike_offset_bps')
  const [dates, setDates] = useState<string[]>([today()])
  const [dateInput, setDateInput] = useState('')

  const expiries = assetType === 'ustf' ? USTF_EXPIRIES : SWAPTION_EXPIRIES

  const { data, loading, error } = useUstfSmile({
    assetType,
    product: assetType === 'ustf' ? product : undefined,
    expiry,
    tail: assetType === 'swaption' ? tail : undefined,
    dates,
    xAxis,
  })

  const chartRef = useRef<HTMLDivElement>(null)

  const traces = useMemo(() => {
    if (!data?.dates?.length) return []
    const result: any[] = []

    data.dates.forEach((slice, idx) => {
      const color = SERIES_COLORS[idx % SERIES_COLORS.length]
      result.push({
        type: 'scatter' as const,
        mode: 'lines' as const,
        name: slice.date,
        x: slice.smilePoints.map((p) => p.x),
        y: slice.smilePoints.map((p) => p.vol),
        line: { color, width: 2.5 },
        hovertemplate: `${slice.date}<br>` +
          (xAxis === 'delta' ? 'Delta %{x:.0f}<br>' : 'Offset %{x:.0f} bps<br>') +
          `Vol %{y:.2f} bpvol<extra></extra>`,
      })

      // Market points for USTF
      if (slice.marketPoints?.length) {
        result.push({
          type: 'scatter' as const,
          mode: 'markers' as const,
          name: `${slice.date} (mkt)`,
          x: slice.marketPoints.map((p) => p.x),
          y: slice.marketPoints.map((p) => p.vol),
          marker: {
            size: 8,
            color,
            symbol: 'diamond',
            line: { color: '#fff', width: 1 },
          },
          hovertemplate: `Market<br>%{x:.1f}<br>%{y:.2f} bpvol<extra></extra>`,
        })
      }
    })
    return result
  }, [data, xAxis])

  // SABR annotation text
  const annotations = useMemo(() => {
    if (!data?.dates?.length) return []
    return data.dates.map((slice, idx) => {
      const p = slice.sabrParams
      return {
        x: 1,
        y: 1 - idx * 0.06,
        xref: 'paper' as const,
        yref: 'paper' as const,
        text: `<b>${slice.date}</b> α=${p.alpha.toFixed(4)} ρ=${p.rho.toFixed(3)} ν=${p.nu.toFixed(3)}`,
        showarrow: false,
        font: { color: SERIES_COLORS[idx % SERIES_COLORS.length], size: 10 },
        xanchor: 'right' as const,
      }
    })
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
        hovermode: 'closest' as const,
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
          title: xAxis === 'delta' ? 'Delta' : 'Strike Offset (bps)',
          showline: true,
          linecolor: 'rgba(148, 163, 184, 0.35)',
          tickfont: { color: '#94a3b8', size: 10 },
          titlefont: { color: '#94a3b8', size: 11 },
          gridcolor: 'rgba(148, 163, 184, 0.14)',
          zeroline: true,
          zerolinecolor: 'rgba(148, 163, 184, 0.3)',
        },
        yaxis: {
          title: 'NVOL (bpvol)',
          showline: true,
          linecolor: 'rgba(148, 163, 184, 0.35)',
          tickfont: { color: '#94a3b8', size: 10 },
          titlefont: { color: '#94a3b8', size: 11 },
          gridcolor: 'rgba(148, 163, 184, 0.14)',
        },
        annotations,
        uirevision: 'ustf-smile',
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
  }, [traces, annotations, xAxis])

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
        {/* Asset type */}
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

        {/* Product / Tail */}
        {assetType === 'ustf' ? (
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">Product</span>
            <select
              value={product}
              onChange={(e) => setProduct(e.target.value as UstfProduct)}
              className="rounded-lg border border-slate-700 bg-slate-900/70 px-2 py-1.5 text-xs text-slate-200"
            >
              {USTF_PRODUCTS.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">Tail</span>
            <select
              value={tail}
              onChange={(e) => setTail(e.target.value as SwaptionTail)}
              className="rounded-lg border border-slate-700 bg-slate-900/70 px-2 py-1.5 text-xs text-slate-200"
            >
              {SWAPTION_TAILS.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
        )}

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

        {/* x-axis */}
        <div className="flex overflow-hidden rounded-lg border border-slate-700">
          {(['strike_offset_bps', 'delta'] as SmileXAxis[]).map((x) => (
            <button
              key={x}
              onClick={() => setXAxis(x)}
              className={`px-3 py-1.5 text-xs font-semibold ${
                xAxis === x
                  ? 'bg-slate-100 text-slate-950'
                  : 'bg-slate-900/70 text-slate-300 hover:text-white'
              }`}
            >
              {x === 'delta' ? 'Delta' : 'Strike Offset'}
            </button>
          ))}
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
            <button onClick={() => removeDate(d)} className="ml-0.5 text-slate-500 hover:text-white">
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
