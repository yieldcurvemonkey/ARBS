'use client'

import { useEffect, useMemo, useRef, useState } from 'react'

import { SERIES_COLORS } from '../constants'
import { useUstfTimeseries } from '../hooks/useUstfTimeseries'
import type { SeriesConfig, TimeRange, TimeseriesMode } from '../types'
import { TimeseriesPairSelector } from './TimeseriesPairSelector'

const DEFAULT_S1: SeriesConfig = { type: 'ustf', product: 'TY', expiry: '1M' }
const DEFAULT_S2: SeriesConfig = { type: 'swaption', expiry: '1M', tail: '7Y' }

function formatVol(v: number | null, decimals = 1): string {
  if (v === null || !Number.isFinite(v)) return '—'
  return v.toFixed(decimals)
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="text-xs uppercase text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-white">{value}</div>
      {sub && <div className="mt-0.5 text-sm text-slate-400">{sub}</div>}
    </div>
  )
}

export function TimeseriesModule() {
  const [series1, setSeries1] = useState<SeriesConfig>(DEFAULT_S1)
  const [series2, setSeries2] = useState<SeriesConfig | null>(DEFAULT_S2)
  const [mode, setMode] = useState<TimeseriesMode>('overlay')
  const [range, setRange] = useState<TimeRange>('6M')

  const { data, loading, error } = useUstfTimeseries({
    series1,
    series2,
    mode,
    range,
  })

  const chartRef = useRef<HTMLDivElement>(null)

  const traces = useMemo(() => {
    if (!data?.points?.length) return []
    const dates = data.points.map((p) => p.date)

    if (mode === 'spread' && series2) {
      return [
        {
          type: 'scatter' as const,
          mode: 'lines+markers' as const,
          name: `${data.series1Label} - ${data.series2Label}`,
          x: dates,
          y: data.points.map((p) => p.spread),
          line: { color: SERIES_COLORS[2], width: 2.2 },
          marker: { size: 4, color: SERIES_COLORS[2] },
          hovertemplate: `Spread<br>%{x}<br>%{y:.2f} bpvol<extra></extra>`,
        },
      ]
    }

    const result: any[] = [
      {
        type: 'scatter' as const,
        mode: 'lines+markers' as const,
        name: data.series1Label,
        x: dates,
        y: data.points.map((p) => p.series1),
        line: { color: SERIES_COLORS[0], width: 2.2 },
        marker: { size: 4, color: SERIES_COLORS[0] },
        hovertemplate: `${data.series1Label}<br>%{x}<br>%{y:.2f} bpvol<extra></extra>`,
      },
    ]
    if (data.series2Label) {
      result.push({
        type: 'scatter' as const,
        mode: 'lines+markers' as const,
        name: data.series2Label,
        x: dates,
        y: data.points.map((p) => p.series2),
        line: { color: SERIES_COLORS[1], width: 2.2 },
        marker: { size: 4, color: SERIES_COLORS[1] },
        hovertemplate: `${data.series2Label}<br>%{x}<br>%{y:.2f} bpvol<extra></extra>`,
      })
    }
    return result
  }, [data, mode, series2])

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
          type: 'date' as const,
          showspikes: true,
          spikesnap: 'cursor' as const,
          spikemode: 'across' as const,
          spikecolor: '#f8fafc',
          spikethickness: 0.55,
          showline: true,
          linecolor: 'rgba(148, 163, 184, 0.35)',
          tickfont: { color: '#94a3b8', size: 10 },
          gridcolor: 'rgba(148, 163, 184, 0.14)',
        },
        yaxis: {
          title: 'NVOL (bpvol)',
          showspikes: true,
          spikesnap: 'cursor' as const,
          spikecolor: '#f8fafc',
          spikethickness: 0.55,
          showline: true,
          linecolor: 'rgba(148, 163, 184, 0.35)',
          tickfont: { color: '#94a3b8', size: 10 },
          titlefont: { color: '#94a3b8', size: 11 },
          gridcolor: 'rgba(148, 163, 184, 0.14)',
        },
        uirevision: 'ustf-timeseries',
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
  }, [traces])

  const stats = data?.stats

  return (
    <div className="space-y-4">
      <TimeseriesPairSelector
        series1={series1}
        series2={series2}
        mode={mode}
        range={range}
        onSeries1Change={setSeries1}
        onSeries2Change={setSeries2}
        onModeChange={setMode}
        onRangeChange={setRange}
      />

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

      {stats && (
        <div className="grid gap-3 md:grid-cols-3">
          <StatCard
            label={data?.series1Label ?? 'Series 1'}
            value={formatVol(stats.series1.latest)}
            sub={stats.series1.zScore !== null ? `z ${formatVol(stats.series1.zScore, 2)}` : undefined}
          />
          {stats.series2 && (
            <StatCard
              label={data?.series2Label ?? 'Series 2'}
              value={formatVol(stats.series2.latest)}
              sub={stats.series2.zScore !== null ? `z ${formatVol(stats.series2.zScore, 2)}` : undefined}
            />
          )}
          {stats.spread && (
            <StatCard
              label="Spread"
              value={formatVol(stats.spread.latest)}
              sub={stats.spread.zScore !== null ? `z ${formatVol(stats.spread.zScore, 2)}` : undefined}
            />
          )}
        </div>
      )}
    </div>
  )
}
