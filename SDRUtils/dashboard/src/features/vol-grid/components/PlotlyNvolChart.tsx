'use client'

import { useEffect, useMemo, useRef } from 'react'

type PlotlyNvolPoint = {
  date: string
  nvol: number | null
}

type PlotlyNvolSeries = {
  key: string
  label: string
  color: string
  points: PlotlyNvolPoint[]
}

type PlotlyNvolChartProps = {
  series: PlotlyNvolSeries[]
  title: string
  height?: number
  showSma?: boolean
  yAxisTitle?: string
}

function computeSma(values: Array<number | null>, period: number): Array<number | null> {
  return values.map((_, index) => {
    if (index < period - 1) return null
    let sum = 0
    for (let cursor = index - period + 1; cursor <= index; cursor += 1) {
      const value = values[cursor]
      if (value === null || !Number.isFinite(value)) {
        return null
      }
      sum += value
    }
    return sum / period
  })
}

export function PlotlyNvolChart({
  series,
  title,
  height = 380,
  showSma = false,
  yAxisTitle = 'NVOL (bpvol)'
}: PlotlyNvolChartProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const normalizedSeries = useMemo(
    () =>
      series
        .map((entry) => ({
          ...entry,
          points: entry.points.filter(
            (point) => point.nvol !== null && Number.isFinite(point.nvol)
          ) as Array<{ date: string; nvol: number }>
        }))
        .filter((entry) => entry.points.length > 0),
    [series]
  )

  useEffect(() => {
    let disposed = false
    let plotly: any = null
    const container = rootRef.current

    const run = async () => {
      const plotlyModule = await import('plotly.js-dist-min')
      plotly = (plotlyModule as any).default ?? plotlyModule
      if (disposed || !container) return

      const data = normalizedSeries.flatMap((entry, index) => {
        const dates = entry.points.map((point) => point.date)
        const values = entry.points.map((point) => point.nvol)
        const traces: any[] = [
          {
            type: 'scatter',
            mode: 'lines+markers',
            name: entry.label,
            x: dates,
            y: values,
            line: { color: entry.color, width: 2.2 },
            marker: {
              color: entry.color,
              size: normalizedSeries.length > 1 ? 4 : 5,
              line: { color: 'rgba(226,232,240,0.3)', width: 0.5 }
            },
            hovertemplate: `${entry.label}<br>Date %{x}<br>NVOL %{y:.2f} bpvol<extra></extra>`
          }
        ]

        if (showSma) {
          traces.push({
            type: 'scatter',
            mode: 'lines',
            name: `${entry.label} SMA20`,
            x: dates,
            y: computeSma(values, 20),
            line: {
              color: index === 0 ? '#94a3b8' : entry.color,
              width: 1.15,
              dash: 'dot'
            },
            opacity: 0.85,
            hovertemplate: `${entry.label} SMA20<br>Date %{x}<br>NVOL %{y:.2f} bpvol<extra></extra>`
          })
        }

        return traces
      })

      const layout = {
        template: 'plotly_dark',
        paper_bgcolor: 'rgba(2, 6, 23, 0)',
        plot_bgcolor: 'rgba(2, 6, 23, 0.65)',
        autosize: true,
        height,
        margin: { t: 54, r: 24, b: 54, l: 72 },
        title: {
          text: title,
          x: 0.01,
          xanchor: 'left',
          font: { size: 14, color: '#e2e8f0' }
        },
        hovermode: 'x unified',
        hoverlabel: {
          bgcolor: 'rgba(15, 23, 42, 0.94)',
          bordercolor: 'rgba(148, 163, 184, 0.25)',
          font: { color: '#e2e8f0', size: 11 }
        },
        legend: {
          orientation: 'h',
          x: 0,
          y: 1.16,
          bgcolor: 'rgba(15, 23, 42, 0.55)',
          bordercolor: 'rgba(148, 163, 184, 0.15)',
          borderwidth: 1,
          font: { color: '#cbd5e1', size: 11 }
        },
        xaxis: {
          title: 'As Of Date',
          type: 'date',
          showspikes: true,
          spikesnap: 'cursor',
          spikemode: 'across',
          spikecolor: '#f8fafc',
          spikethickness: 0.55,
          showline: true,
          linecolor: 'rgba(148, 163, 184, 0.35)',
          tickfont: { color: '#94a3b8', size: 10 },
          titlefont: { color: '#94a3b8', size: 11 },
          gridcolor: 'rgba(148, 163, 184, 0.14)',
          zerolinecolor: 'rgba(148, 163, 184, 0.14)'
        },
        yaxis: {
          title: yAxisTitle,
          showspikes: true,
          spikesnap: 'cursor',
          spikecolor: '#f8fafc',
          spikethickness: 0.55,
          showline: true,
          linecolor: 'rgba(148, 163, 184, 0.35)',
          tickfont: { color: '#94a3b8', size: 10 },
          titlefont: { color: '#94a3b8', size: 11 },
          gridcolor: 'rgba(148, 163, 184, 0.14)',
          zerolinecolor: 'rgba(148, 163, 184, 0.14)'
        },
        uirevision: `vol-grid-nvol-${title}`
      }

      const config = {
        responsive: true,
        displaylogo: false
      }

      await plotly.react(container, data, layout, config)
    }

    run().catch((renderError) => {
      console.error('PlotlyNvolChart render error', renderError)
    })

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
  }, [height, normalizedSeries, showSma, title, yAxisTitle])

  return <div ref={rootRef} style={{ height }} className="w-full" />
}
