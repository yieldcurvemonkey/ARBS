'use client'
// ABOUTME: The intraday traded-prints figure, in Plotly — dark, crosshaired,
// two stacked panels on one shared time axis.
//
// Follows the dynamic-import + purge pattern of DockTimeseriesChart in this
// same directory: plotly.js-dist-min is ~3MB and must never reach the initial
// bundle, and it has no SSR story, so it is imported inside the effect.
//
// TWO PANELS, ONE X AXIS, ONE CROSSHAIR:
//   top     the rate — the modelled 1-minute mid, with a mark per print
//   bottom  the same prints as signed distance from mid, in bp
//
// They share `xaxis` so a spike line crosses both, which is the whole reason to
// put them in one figure rather than two: the question a reader has at a mark
// is "how far off mid was that", and the answer is directly below it.
//
// THE SIGN ENCODING IS NOT RE-DERIVED HERE. Direction comes from the server's
// dealer_direction, via directionOf(). The classifier's call is
// sign(deviation - mid_bias), not sign(deviation), and re-deriving it from the
// deviation alone would invert exactly the near-mid prints while looking
// completely plausible.
import type { JSX } from 'react'
import { useEffect, useRef } from 'react'
import { ANALYTICS_COLORS } from './analytics-format'
import {
  clampToDomain,
  directionOf,
  markerRadius,
  type MidPoint,
  type MidSource,
  type PrintRow,
  sizeNotRead,
  tsMillis,
} from './IntradayPrintsPanel.helpers'

/** Plotly wants ISO strings on a date axis, not epoch ms. */
function iso(t: number): string {
  return new Date(t).toISOString()
}

type Props = {
  rows: PrintRow[]
  mid: MidPoint[]
  midSource: MidSource
  yDomain: [number, number] | null
  tDomain: [number, number] | null
  height: number
  tenor: string
  rateIndex: string
}

type Group = {
  name: string
  rows: PrintRow[]
  symbol: string
  color: string
  filled: boolean
}

export function IntradayPrintsPlot({
  rows, mid, midSource, yDomain, tDomain, height, tenor, rateIndex,
}: Props): JSX.Element {
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = rootRef.current
    if (!container) return
    let disposed = false
    let plotly: unknown = null

    // --- group the marks by how they are drawn --------------------------
    // One trace per (tone, shape) rather than one per print: plotly draws a
    // trace as a single scatter, so this is ~5 traces instead of N marks.
    const groups = new Map<string, Group>()
    for (const r of rows) {
      const st = directionOf(r)
      const off = r.is_off_market === true
      const shape =
        off ? 'diamond-open'
          : st.shape === 'up' ? 'triangle-up'
          : st.shape === 'down' ? 'triangle-down'
          : st.shape === 'ring' ? 'circle-open'
          : 'circle'
      const key = `${st.tone}|${shape}|${st.filled}`
      const g = groups.get(key) ?? {
        name: off ? `${st.label} (off-mkt)` : st.label,
        rows: [], symbol: shape, color: st.color, filled: st.filled && !off,
      }
      g.rows.push(r)
      groups.set(key, g)
    }

    const markTrace = (g: Group) => {
      const x: string[] = []
      const y: number[] = []
      const size: number[] = []
      const custom: (string | number | null)[][] = []
      const lineW: number[] = []
      for (const r of g.rows) {
        const t = tsMillis(r.execution_timestamp)
        if (t == null) continue
        // Off-domain marks are PINNED to the edge, never allowed to own the
        // axis: 11 off-market prints stretched the traded band 31x on the
        // reference day. The tooltip carries the true rate.
        const { value, pinned } = clampToDomain(Number(r.traded_pct), yDomain)
        x.push(iso(t))
        y.push(value)
        size.push(markerRadius(r.structure_dv01) * 2)
        lineW.push(sizeNotRead(r) ? 1.6 : g.filled ? 0 : 1.4)
        custom.push([
          r.dealer_direction,
          Number(r.traded_pct).toFixed(5),
          r.mid_pct == null ? '—' : Number(r.mid_pct).toFixed(5),
          r.deviation_bps == null ? '—' : Number(r.deviation_bps).toFixed(3),
          r.structure_dv01 == null ? '—' : Math.round(Number(r.structure_dv01)).toLocaleString(),
          r.notional == null ? '—' : `${(Number(r.notional) / 1e6).toFixed(1)}M`,
          r.tenor_display ?? '—',
          r.special_tenor_type ?? '—',
          pinned ? ' (PINNED — off domain)' : '',
        ])
      }
      return {
        type: 'scattergl', mode: 'markers', name: g.name,
        x, y, customdata: custom,
        marker: {
          symbol: g.symbol, size,
          color: g.filled ? g.color : 'rgba(0,0,0,0)',
          opacity: 0.9,
          line: { color: g.color, width: lineW },
        },
        hovertemplate:
          '<b>dealer %{customdata[0]}</b>%{customdata[8]}<br>'
          + 'traded %{customdata[1]}%  ·  mid %{customdata[2]}%<br>'
          + 'deviation %{customdata[3]} bp<br>'
          + 'DV01 %{customdata[4]} / bp  ·  notional %{customdata[5]}<br>'
          + '%{customdata[6]}  ·  %{customdata[7]}<extra></extra>',
        xaxis: 'x', yaxis: 'y',
      }
    }

    const traces: unknown[] = []

    // --- the mid line ----------------------------------------------------
    if (mid.length > 0 && midSource !== 'none') {
      traces.push({
        type: 'scattergl', mode: 'lines', name: 'mid',
        x: mid.map((m) => iso(m.t)),
        // nulls break the line rather than bridging it — connectgaps:false
        y: mid.map((m) => m.mid),
        connectgaps: false,
        line: {
          color: ANALYTICS_COLORS.slate400,
          width: midSource === 'grid' ? 1.6 : 1.25,
          dash: midSource === 'grid' ? 'solid' : 'dash',
          shape: 'linear',
        },
        hovertemplate: 'mid %{y:.5f}%<extra></extra>',
        xaxis: 'x', yaxis: 'y',
      })
    }

    for (const g of groups.values()) traces.push(markTrace(g))

    // --- the deviation panel, on the shared x ----------------------------
    const devX: string[] = []
    const devY: number[] = []
    const devC: string[] = []
    for (const r of rows) {
      const t = tsMillis(r.execution_timestamp)
      const d = r.deviation_bps == null ? null : Number(r.deviation_bps)
      if (t == null || d == null || !Number.isFinite(d)) continue
      devX.push(iso(t))
      devY.push(d)
      devC.push(directionOf(r).color)
    }
    if (devX.length > 0) {
      traces.push({
        type: 'bar', name: 'deviation', x: devX, y: devY,
        marker: { color: devC, line: { width: 0 } },
        hovertemplate: '%{y:+.3f} bp off mid<extra></extra>',
        xaxis: 'x', yaxis: 'y2', showlegend: false,
      })
    }

    const spike = {
      showspikes: true,
      spikesnap: 'cursor' as const,
      spikemode: 'across' as const,
      spikecolor: ANALYTICS_COLORS.slate100,
      spikethickness: 0.55,
      spikedash: 'dot' as const,
    }
    const tick = { color: ANALYTICS_COLORS.slate500, size: 9, family: 'monospace' }

    const layout = {
      height,
      margin: { l: 58, r: 12, t: 8, b: 26 },
      paper_bgcolor: 'rgba(2, 6, 23, 0)',
      plot_bgcolor: 'rgba(2, 6, 23, 0.4)',
      font: { color: ANALYTICS_COLORS.slate400, family: 'monospace', size: 10 },
      // ONE crosshair across BOTH panels — the reason they share a figure.
      hovermode: 'x unified',
      hoverlabel: {
        bgcolor: '#0f172a',
        bordercolor: '#334155',
        font: { color: '#e2e8f0', family: 'monospace', size: 10 },
        align: 'left' as const,
      },
      showlegend: false,
      dragmode: 'pan' as const,
      bargap: 0.6,
      xaxis: {
        ...spike,
        type: 'date' as const,
        // ET, because the whole panel is on the New York clock.
        tickformat: '%H:%M',
        gridcolor: ANALYTICS_COLORS.slate800,
        zeroline: false,
        tickfont: tick,
        range: tDomain ? [iso(tDomain[0]), iso(tDomain[1])] : undefined,
        anchor: 'y2' as const,
      },
      yaxis: {
        ...spike,
        domain: [0.34, 1] as [number, number],
        title: { text: 'rate %', font: tick, standoff: 6 },
        tickformat: '.3f',
        gridcolor: ANALYTICS_COLORS.slate800,
        zeroline: false,
        tickfont: tick,
        range: yDomain ?? undefined,
        fixedrange: false,
      },
      yaxis2: {
        domain: [0, 0.26] as [number, number],
        title: { text: 'off mid, bp', font: tick, standoff: 6 },
        tickformat: '+.2f',
        gridcolor: ANALYTICS_COLORS.slate800,
        zerolinecolor: ANALYTICS_COLORS.slate700,
        zeroline: true,
        tickfont: tick,
      },
    }

    const config = {
      responsive: true,
      displaylogo: false,
      scrollZoom: true,
      modeBarButtonsToRemove: [
        'lasso2d', 'select2d', 'hoverClosestCartesian', 'hoverCompareCartesian',
      ],
    }

    const run = async () => {
      const modmod = await import('plotly.js-dist-min')
      const lib = (modmod as unknown as { default?: unknown }).default ?? modmod
      plotly = lib
      if (disposed || !container) return
      const reactFn = (lib as { react: (...a: unknown[]) => Promise<void> }).react
      await reactFn(container, traces, layout, config)
    }
    run().catch((err) => {
      console.error('IntradayPrintsPlot render error', err)
    })

    return () => {
      disposed = true
      if (plotly && container) {
        try {
          ;(plotly as { purge: (el: HTMLElement) => void }).purge(container)
        } catch {
          /* ignore */
        }
      }
    }
  }, [rows, mid, midSource, yDomain, tDomain, height, tenor, rateIndex])

  return <div ref={rootRef} className="w-full" style={{ height: `${height}px` }} />
}
