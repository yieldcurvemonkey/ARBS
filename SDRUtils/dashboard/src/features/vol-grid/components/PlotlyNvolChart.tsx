'use client'

import { useEffect, useRef } from 'react'

type PlotlyNvolChartProps = {
  timeseries: { date: string; nvol: number }[]
  title: string
  height?: number
}

function computeSma(values: number[], period: number): (number | null)[] {
  return values.map((_, i) => {
    if (i < period - 1) return null
    let sum = 0
    for (let j = i - period + 1; j <= i; j++) sum += values[j]
    return sum / period
  })
}

export function PlotlyNvolChart({ timeseries, title, height = 400 }: PlotlyNvolChartProps) {
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let disposed = false
    let plotly: any = null
    const container = rootRef.current

    const run = async () => {
      const plotlyModule = await import('plotly.js-dist-min')
      plotly = (plotlyModule as any).default ?? plotlyModule
      if (disposed || !container) return

      const dates = timeseries.map((p) => p.date)
      const nvols = timeseries.map((p) => p.nvol)
      const sma20 = computeSma(nvols, 20)

      const data = [
        {
          type: 'scatter' as const,
          mode: 'lines' as const,
          name: 'NVOL',
          x: dates,
          y: nvols,
          line: { color: '#f59e0b', width: 2 },
          hovertemplate: 'NVOL: %{y:.1f}<br>Date: %{x}<extra></extra>'
        },
        {
          type: 'scatter' as const,
          mode: 'lines' as const,
          name: 'SMA20',
          x: dates,
          y: sma20,
          line: { color: '#38bdf8', width: 1.2, dash: 'dot' as const },
          hovertemplate: 'SMA20: %{y:.1f}<br>Date: %{x}<extra></extra>'
        }
      ]

      const layout = {
        template: 'plotly_dark',
        paper_bgcolor: 'rgba(2, 6, 23, 0)',
        plot_bgcolor: 'rgba(2, 6, 23, 0.65)',
        autosize: true,
        height,
        margin: { t: 40, r: 16, b: 48, l: 56 },
        title: { text: title, font: { size: 13, color: '#e2e8f0' } },
        hovermode: 'x unified' as const,
        legend: {
          orientation: 'h' as const,
          x: 0,
          y: 1.12,
          bgcolor: 'rgba(15, 23, 42, 0.65)',
          font: { color: '#94a3b8', size: 11 }
        },
        xaxis: {
          type: 'date' as const,
          showspikes: true,
          spikesnap: 'cursor' as const,
          spikemode: 'across' as const,
          spikecolor: '#f8fafc',
          spikethickness: 0.55,
          gridcolor: 'rgba(148, 163, 184, 0.15)'
        },
        yaxis: {
          title: 'bpvol',
          showspikes: true,
          spikesnap: 'cursor' as const,
          spikecolor: '#f8fafc',
          spikethickness: 0.55,
          gridcolor: 'rgba(148, 163, 184, 0.15)'
        },
        uirevision: 'vol-grid-nvol'
      }

      const config = {
        responsive: true,
        displaylogo: false,
        modeBarButtonsToAdd: [
          'drawline',
          'drawopenpath',
          'drawclosedpath',
          'drawcircle',
          'drawrect',
          'eraseshape'
        ]
      }

      await plotly.react(container, data, layout, config)
    }

    run().catch((err) => console.error('PlotlyNvolChart render error', err))

    return () => {
      disposed = true
      if (plotly && container) {
        try {
          plotly.purge(container)
        } catch {
          /* no-op */
        }
      }
    }
  }, [timeseries, title, height])

  return <div ref={rootRef} style={{ height }} className="w-full" />
}
