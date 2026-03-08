'use client'

import { useEffect, useMemo, useRef } from 'react'
import type { VolGridCell } from '../types'
import { buildSurfaceMatrix } from '../analytics'

type VolGridSurface3DProps = {
  cells: VolGridCell[]
  expiries: string[]
  tenors: string[]
  asOfDate: string | null
  height?: number
}

export function VolGridSurface3D({
  cells,
  expiries,
  tenors,
  asOfDate,
  height = 500
}: VolGridSurface3DProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const { z, hoverText } = useMemo(
    () => buildSurfaceMatrix(cells, expiries, tenors),
    [cells, expiries, tenors]
  )
  const xAxis = useMemo(() => tenors.map((_, index) => index), [tenors])
  const yAxis = useMemo(() => expiries.map((_, index) => index), [expiries])

  useEffect(() => {
    let disposed = false
    let plotly: any = null
    const container = rootRef.current

    const run = async () => {
      const plotlyModule = await import('plotly.js-dist-min')
      plotly = (plotlyModule as any).default ?? plotlyModule
      if (disposed || !container) return

      const data = [
        {
          type: 'surface' as const,
          x: xAxis,
          y: yAxis,
          z,
          text: hoverText,
          colorscale: [
            [0, '#0f172a'],
            [0.25, '#1d4ed8'],
            [0.55, '#2563eb'],
            [0.8, '#f59e0b'],
            [1, '#f97316']
          ],
          showscale: true,
          colorbar: {
            title: { text: 'bpvol', font: { color: '#cbd5e1', size: 11 } },
            tickfont: { color: '#94a3b8', size: 10 },
            outlinecolor: 'rgba(148, 163, 184, 0.3)',
            bgcolor: 'rgba(15, 23, 42, 0.35)'
          },
          contours: {
            z: {
              show: true,
              usecolormap: true,
              highlightcolor: '#e2e8f0',
              project: { z: true }
            }
          },
          hovertemplate: '%{text}<br>Vol %{z:.2f} bpvol<extra></extra>'
        }
      ]

      const layout = {
        template: 'plotly_dark',
        paper_bgcolor: 'rgba(2, 6, 23, 0)',
        plot_bgcolor: 'rgba(2, 6, 23, 0)',
        autosize: true,
        height,
        margin: { t: 24, r: 24, b: 24, l: 24 },
        scene: {
          bgcolor: 'rgba(2, 6, 23, 0)',
          aspectmode: 'manual',
          aspectratio: {
            x: 1.9,
            y: 1.55,
            z: 0.42
          },
          xaxis: {
            title: { text: 'Tenor', font: { color: '#94a3b8', size: 11 } },
            tickmode: 'array',
            tickvals: xAxis,
            ticktext: tenors,
            tickfont: { color: '#94a3b8', size: 10 },
            gridcolor: 'rgba(148, 163, 184, 0.15)',
            zerolinecolor: 'rgba(148, 163, 184, 0.15)'
          },
          yaxis: {
            title: { text: 'Expiry', font: { color: '#94a3b8', size: 11 } },
            tickmode: 'array',
            tickvals: yAxis,
            ticktext: expiries,
            tickfont: { color: '#94a3b8', size: 10 },
            gridcolor: 'rgba(148, 163, 184, 0.15)',
            zerolinecolor: 'rgba(148, 163, 184, 0.15)'
          },
          zaxis: {
            title: { text: 'bpvol', font: { color: '#94a3b8', size: 11 } },
            tickfont: { color: '#94a3b8', size: 10 },
            gridcolor: 'rgba(148, 163, 184, 0.15)',
            zerolinecolor: 'rgba(148, 163, 184, 0.15)',
            nticks: 6
          },
          camera: {
            eye: { x: 1.35, y: -1.45, z: 0.42 },
            projection: {
              type: 'orthographic'
            }
          }
        },
        annotations: [
          {
            xref: 'paper',
            yref: 'paper',
            x: 0,
            y: 1.08,
            xanchor: 'left',
            yanchor: 'bottom',
            showarrow: false,
            text: asOfDate ? `ATMF surface for ${asOfDate}` : 'ATMF surface',
            font: { color: '#e2e8f0', size: 13 }
          }
        ],
        uirevision: `vol-grid-surface-${asOfDate ?? 'live'}`
      }

      await plotly.react(container, data, layout, {
        responsive: true,
        displaylogo: false
      })
    }

    run().catch((error) => {
      console.error('VolGridSurface3D render error', error)
    })

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
  }, [asOfDate, expiries, height, hoverText, tenors, xAxis, yAxis, z])

  return <div ref={rootRef} style={{ height }} className="w-full" />
}
