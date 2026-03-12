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
import type { AssetType, SmileXAxis, SwaptionTail, UstfProduct } from '../types'

const LABEL_CLASS =
  'text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500'
const INPUT_CLASS =
  'h-8 rounded-md border border-slate-700/80 bg-slate-950/80 px-3 text-[12px] text-slate-100 outline-none transition focus:border-slate-500'

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function segmentButtonClass(active: boolean): string {
  return [
    'px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] transition',
    active
      ? 'bg-slate-100 text-slate-950'
      : 'bg-slate-950/70 text-slate-300 hover:bg-slate-900 hover:text-white',
  ].join(' ')
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

    data.dates.forEach((slice, index) => {
      const color = SERIES_COLORS[index % SERIES_COLORS.length]
      result.push({
        type: 'scatter' as const,
        mode: 'lines' as const,
        name: slice.date,
        x: slice.smilePoints.map((point) => point.x),
        y: slice.smilePoints.map((point) => point.vol),
        line: { color, width: 2.5 },
        hovertemplate:
          `${slice.date}<br>` +
          (xAxis === 'delta' ? 'Delta %{x:.0f}<br>' : 'Offset %{x:.0f} bps<br>') +
          'Vol %{y:.2f} bpvol<extra></extra>',
      })

      if (slice.marketPoints?.length) {
        result.push({
          type: 'scatter' as const,
          mode: 'markers' as const,
          name: `${slice.date} mkt`,
          x: slice.marketPoints.map((point) => point.x),
          y: slice.marketPoints.map((point) => point.vol),
          marker: {
            size: 8,
            color,
            symbol: 'diamond',
            line: { color: '#fff', width: 1 },
          },
          hovertemplate: 'Market<br>%{x:.1f}<br>%{y:.2f} bpvol<extra></extra>',
        })
      }
    })

    return result
  }, [data, xAxis])

  const annotations = useMemo(() => {
    if (!data?.dates?.length) return []
    return data.dates.map((slice, index) => {
      const params = slice.sabrParams
      return {
        x: 1,
        y: 1 - index * 0.06,
        xref: 'paper' as const,
        yref: 'paper' as const,
        text: `<b>${slice.date}</b> alpha=${params.alpha.toFixed(4)} rho=${params.rho.toFixed(3)} nu=${params.nu.toFixed(3)}`,
        showarrow: false,
        font: { color: SERIES_COLORS[index % SERIES_COLORS.length], size: 10 },
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
        plot_bgcolor: 'rgba(2, 6, 23, 0.72)',
        autosize: true,
        height: 420,
        margin: { t: 32, r: 20, b: 48, l: 64 },
        hovermode: 'closest' as const,
        hoverlabel: {
          bgcolor: 'rgba(15, 23, 42, 0.96)',
          bordercolor: 'rgba(148, 163, 184, 0.22)',
          font: { color: '#e2e8f0', size: 11 },
        },
        legend: {
          orientation: 'h' as const,
          x: 0,
          y: 1.1,
          bgcolor: 'rgba(15, 23, 42, 0.78)',
          bordercolor: 'rgba(148, 163, 184, 0.15)',
          borderwidth: 1,
          font: { color: '#cbd5e1', size: 11 },
        },
        xaxis: {
          title: xAxis === 'delta' ? 'Delta' : 'Strike Offset (bps)',
          showline: true,
          linecolor: 'rgba(148, 163, 184, 0.3)',
          tickfont: { color: '#94a3b8', size: 10 },
          titlefont: { color: '#94a3b8', size: 11 },
          gridcolor: 'rgba(71, 85, 105, 0.18)',
          zeroline: true,
          zerolinecolor: 'rgba(148, 163, 184, 0.2)',
        },
        yaxis: {
          title: 'NVOL (bpvol)',
          showline: true,
          linecolor: 'rgba(148, 163, 184, 0.3)',
          tickfont: { color: '#94a3b8', size: 10 },
          titlefont: { color: '#94a3b8', size: 11 },
          gridcolor: 'rgba(71, 85, 105, 0.18)',
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
        try {
          plotly.purge(container)
        } catch {
          // no-op
        }
      }
    }
  }, [traces, annotations, xAxis])

  const addDate = () => {
    const nextDate = dateInput.trim()
    if (nextDate && !dates.includes(nextDate) && dates.length < 5) {
      setDates([...dates, nextDate].sort())
      setDateInput('')
    }
  }

  const removeDate = (dateToRemove: string) => {
    setDates(dates.filter((date) => date !== dateToRemove))
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 rounded-lg border border-slate-800/80 bg-slate-950/45 p-3 xl:grid-cols-[auto_auto_auto_auto]">
        <div className="flex flex-wrap items-center gap-3">
          <span className={LABEL_CLASS}>Asset</span>
          <div className="flex overflow-hidden rounded-md border border-slate-700/80">
            {(['ustf', 'swaption'] as AssetType[]).map((nextAssetType) => (
              <button
                key={nextAssetType}
                type="button"
                onClick={() => {
                  setAssetType(nextAssetType)
                  setExpiry('1M')
                }}
                className={segmentButtonClass(assetType === nextAssetType)}
              >
                {nextAssetType === 'ustf' ? 'USTF' : 'OTC'}
              </button>
            ))}
          </div>
        </div>

        {assetType === 'ustf' ? (
          <div className="flex items-center gap-3">
            <span className={LABEL_CLASS}>Product</span>
            <select
              value={product}
              onChange={(event) => setProduct(event.target.value as UstfProduct)}
              className={INPUT_CLASS}
            >
              {USTF_PRODUCTS.map((currentProduct) => (
                <option key={currentProduct} value={currentProduct}>
                  {currentProduct}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <span className={LABEL_CLASS}>Tail</span>
            <select
              value={tail}
              onChange={(event) => setTail(event.target.value as SwaptionTail)}
              className={INPUT_CLASS}
            >
              {SWAPTION_TAILS.map((currentTail) => (
                <option key={currentTail} value={currentTail}>
                  {currentTail}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="flex items-center gap-3">
          <span className={LABEL_CLASS}>Expiry</span>
          <select
            value={expiry}
            onChange={(event) => setExpiry(event.target.value)}
            className={INPUT_CLASS}
          >
            {expiries.map((currentExpiry) => (
              <option key={currentExpiry} value={currentExpiry}>
                {currentExpiry}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <span className={LABEL_CLASS}>X axis</span>
          <div className="flex overflow-hidden rounded-md border border-slate-700/80">
            {(['strike_offset_bps', 'delta'] as SmileXAxis[]).map((axis) => (
              <button
                key={axis}
                type="button"
                onClick={() => setXAxis(axis)}
                className={segmentButtonClass(xAxis === axis)}
              >
                {axis === 'delta' ? 'Delta' : 'Offset'}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-slate-800/80 bg-slate-950/45 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className={LABEL_CLASS}>Dates</span>
          {dates.map((date) => (
            <span
              key={date}
              className="inline-flex items-center gap-2 rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 py-1 font-mono text-[11px] text-slate-200"
            >
              {date}
              <button
                type="button"
                onClick={() => removeDate(date)}
                className="text-slate-500 transition hover:text-white"
              >
                x
              </button>
            </span>
          ))}

          {dates.length < 5 ? (
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="date"
                value={dateInput}
                onChange={(event) => setDateInput(event.target.value)}
                className={INPUT_CLASS}
              />
              <button
                type="button"
                onClick={addDate}
                className="rounded-md border border-slate-700/80 bg-slate-950/80 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-300 transition hover:border-slate-500 hover:text-white"
              >
                Add
              </button>
            </div>
          ) : null}
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-900/50 bg-rose-950/35 px-4 py-2 text-sm text-rose-200">
          {error}
        </div>
      ) : null}

      <div className="relative overflow-hidden rounded-lg border border-slate-800/80 bg-slate-950/65 p-2">
        {loading ? (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-950/55 backdrop-blur-sm">
            <div className="text-sm text-slate-400">Loading...</div>
          </div>
        ) : null}
        <div ref={chartRef} style={{ height: 420 }} className="w-full" />
      </div>
    </div>
  )
}
