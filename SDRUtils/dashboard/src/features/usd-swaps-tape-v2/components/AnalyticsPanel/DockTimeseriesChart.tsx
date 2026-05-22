'use client'
// ABOUTME: Plotly-based dock chart for fixed_rate / spread_to_mid views.
// Mirrors the dynamic-import + dark-template pattern used by the UST RV
// and Listed-vs-OTC USTF Vol modules so the dock chart matches that
// styling, while keeping the analytics-dock palette tokens (Custy
// amber, IDB sky, focused fuchsia, IQR cyan) so it still reads as part
// of the USD Swaps Tape v2 surface. DV01 / Notional / VOLUME views
// keep using the Recharts ComposedChart inside TimeseriesTab — those
// rely on stacked-bar rendering that's cleaner in Recharts.
import { useEffect, useRef } from 'react'
import { ANALYTICS_COLORS, sequenceColor } from './analytics-format'
import type {
  AnalyticsMetricKey,
  AnalyticsViewKey,
  DistributionStats,
  FocusedTrade,
  TimeseriesPointAug,
} from './analytics-types'

export interface DockTimeseriesChartProps {
  data: ReadonlyArray<TimeseriesPointAug & { idxPos?: number }>
  focused: FocusedTrade
  metric: AnalyticsMetricKey
  view: AnalyticsViewKey
  unit: string
  showCusty: boolean
  showIdb: boolean
  showSigmaBands: boolean
  showIqrBand: boolean
  showDots: boolean
  stats: DistributionStats
  focusedValue: number
  focusedPercentile: number
  yMin: string
  yMax: string
  height: number
  // Sequence-mode overlays — N reference lines + dots at each
  // sequence trade's rate. Hidden ids skip rendering.
  sequence?: ReadonlyArray<FocusedTrade>
  hiddenSequenceIds?: ReadonlySet<string>
}

type PlotlyContainer = HTMLDivElement & {
  on?: (event: string, handler: (...args: unknown[]) => void) => void
  removeListener?: (event: string, handler: (...args: unknown[]) => void) => void
}

export function DockTimeseriesChart(props: DockTimeseriesChartProps) {
  const {
    data, focused, metric, view, unit,
    showCusty, showIdb, showSigmaBands, showIqrBand, showDots,
    stats, focusedValue, focusedPercentile,
    yMin, yMax, height, sequence, hiddenSequenceIds,
  } = props
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let disposed = false
    let plotly: unknown = null
    const container = rootRef.current as PlotlyContainer | null

    const isIntraday = view === 'INTRADAY'
    const xs = data.map((d) => d.ts)
    const idbY = data.map((d) => d.idbClose ?? null)
    const custyY = data.map((d) => d.custyClose ?? null)
    const yFmt = metric === 'pts' ? '.6f' : '.2f'

    const traces: Array<Record<string, unknown>> = []

    // Custy line — amber per dock palette. `connectgaps:false` so days
    // without a Custy print render as gaps instead of a sloped line
    // toward zero.
    if (showCusty) {
      traces.push({
        type: 'scatter',
        mode: showDots ? 'lines+markers' : 'lines',
        name: 'Custy',
        x: xs,
        y: custyY,
        line: {
          color: ANALYTICS_COLORS.custy,
          width: 1.6,
          // Intraday LOCF interpolation produces a stepwise series; let
          // Plotly draw it as such so the rate plateaus read clearly.
          shape: isIntraday && metric === 'fixed_rate' ? 'hv' : 'spline',
          smoothing: 0.6,
        },
        marker: { color: ANALYTICS_COLORS.custy, size: 3.5 },
        hovertemplate:
          `<b>Custy</b> %{y:${yFmt}} ${unit}<br>%{x|%b %d %Y %H:%M} NY<extra></extra>`,
        connectgaps: false,
      })
    }

    if (showIdb) {
      traces.push({
        type: 'scatter',
        mode: showDots ? 'lines+markers' : 'lines',
        name: 'IDB',
        x: xs,
        y: idbY,
        line: {
          color: ANALYTICS_COLORS.idb,
          width: 1.7,
          shape: isIntraday && metric === 'fixed_rate' ? 'hv' : 'spline',
          smoothing: 0.6,
        },
        marker: { color: ANALYTICS_COLORS.idb, size: 3.5 },
        hovertemplate:
          `<b>IDB</b> %{y:${yFmt}} ${unit}<br>%{x|%b %d %Y %H:%M} NY<extra></extra>`,
        connectgaps: false,
      })
    }

    // Focused trade marker as its own scatter trace so it lands above
    // the lines + reference dot. Fuchsia per the dock's `focused`
    // accent. Plotly's `shapes` (used for the reference line below)
    // doesn't support markers, so we render the dot here.
    const focusedTs = focused.execution_start
      ?? (xs.length > 0 ? xs[xs.length - 1] : null)
    if (metric === 'fixed_rate' && focusedTs != null) {
      traces.push({
        type: 'scatter',
        mode: 'markers',
        name: `Focused trade (P${Math.round(focusedPercentile)})`,
        x: [focusedTs],
        y: [focusedValue],
        marker: {
          color: ANALYTICS_COLORS.focused,
          size: 10,
          line: { color: '#0f172a', width: 1.5 },
          symbol: 'circle',
        },
        hovertemplate:
          `<b>Focused</b> %{y:.2f} ${unit}<br>P${Math.round(focusedPercentile)}<extra></extra>`,
      })
    }

    // Sequence overlay dots — one per non-hidden sequence trade.
    // Reference lines are added as horizontal shapes below.
    const visibleSeq = (sequence ?? []).filter(
      (t) => !(hiddenSequenceIds?.has(t.id)),
    )
    if (metric === 'fixed_rate' && visibleSeq.length > 0) {
      const lastTs = xs.length > 0 ? xs[xs.length - 1] : null
      visibleSeq.forEach((t, i) => {
        const colour = sequenceColor(i)
        const ts = t.execution_start ?? lastTs
        if (ts == null) return
        traces.push({
          type: 'scatter',
          mode: 'markers',
          name: `Seq ${i + 1}: ${t.tape_label}`,
          x: [ts],
          y: [t.fixed_rate_bps],
          marker: {
            color: colour,
            size: 7,
            line: { color: '#0f172a', width: 1 },
            symbol: 'circle',
          },
          hovertemplate:
            `<b>${t.tape_label}</b><br>%{y:.2f} ${unit}<extra></extra>`,
          showlegend: false,
        })
      })
    }

    // Reference lines: focused-trade horizontal + per-sequence lines.
    // Modelled as Plotly shapes so they paint behind the markers but
    // above the gridlines.
    const shapes: Array<Record<string, unknown>> = []
    if (metric === 'fixed_rate' && Number.isFinite(focusedValue)) {
      shapes.push({
        type: 'line',
        xref: 'paper', x0: 0, x1: 1,
        yref: 'y', y0: focusedValue, y1: focusedValue,
        line: {
          color: ANALYTICS_COLORS.focused,
          width: 1.25,
          dash: 'dash',
        },
      })
    }
    if (metric === 'fixed_rate' && visibleSeq.length > 0) {
      visibleSeq.forEach((t, i) => {
        if (!Number.isFinite(t.fixed_rate_bps)) return
        shapes.push({
          type: 'line',
          xref: 'paper', x0: 0, x1: 1,
          yref: 'y', y0: t.fixed_rate_bps, y1: t.fixed_rate_bps,
          line: {
            color: sequenceColor(i),
            width: 1,
            dash: 'dot',
          },
        })
      })
    }

    // IQR band as a translucent rectangle. Cyan per dock palette.
    if (metric === 'fixed_rate' && showIqrBand
        && Number.isFinite(stats.p25) && Number.isFinite(stats.p75)) {
      shapes.push({
        type: 'rect',
        xref: 'paper', x0: 0, x1: 1,
        yref: 'y', y0: stats.p25, y1: stats.p75,
        fillcolor: ANALYTICS_COLORS.iqr,
        line: { color: ANALYTICS_COLORS.iqrRing, width: 0.5, dash: 'dot' },
        layer: 'below',
      })
    }

    // ±σ bands. Two stacked rectangles (2σ outer, 1σ inner) for the
    // visual hierarchy.
    if (metric === 'fixed_rate' && showSigmaBands
        && Number.isFinite(stats.mean) && Number.isFinite(stats.stddev)) {
      shapes.push({
        type: 'rect',
        xref: 'paper', x0: 0, x1: 1,
        yref: 'y',
        y0: stats.mean - 2 * stats.stddev,
        y1: stats.mean + 2 * stats.stddev,
        fillcolor: ANALYTICS_COLORS.sigma2,
        line: { width: 0 },
        layer: 'below',
      })
      shapes.push({
        type: 'rect',
        xref: 'paper', x0: 0, x1: 1,
        yref: 'y',
        y0: stats.mean - stats.stddev,
        y1: stats.mean + stats.stddev,
        fillcolor: ANALYTICS_COLORS.sigma1,
        line: { width: 0 },
        layer: 'below',
      })
    }

    // Annotations: focused-trade label at the right edge of the chart.
    const annotations: Array<Record<string, unknown>> = []
    if (metric === 'fixed_rate' && Number.isFinite(focusedValue)) {
      annotations.push({
        xref: 'paper', x: 1.0, xanchor: 'right',
        yref: 'y', y: focusedValue, yanchor: 'bottom',
        text: `${focusedValue.toFixed(2)} ${unit}  (P${Math.round(focusedPercentile)})`,
        font: {
          color: ANALYTICS_COLORS.focused,
          size: 10,
          family: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        },
        showarrow: false,
        bgcolor: 'rgba(15, 23, 42, 0.55)',
        borderpad: 2,
      })
    }

    const yDomainLow: number | undefined =
      yMin === '' ? undefined : Number(yMin)
    const yDomainHigh: number | undefined =
      yMax === '' ? undefined : Number(yMax)
    const yRange =
      yDomainLow != null || yDomainHigh != null
        ? [yDomainLow ?? null, yDomainHigh ?? null]
        : undefined

    const layout = {
      template: 'plotly_dark',
      paper_bgcolor: 'rgba(2, 6, 23, 0)',
      plot_bgcolor: 'rgba(2, 6, 23, 0.4)',
      autosize: true,
      height,
      margin: { t: 18, r: 70, b: 36, l: 56 },
      showlegend: false,
      hovermode: 'x unified',
      dragmode: 'zoom',
      hoverlabel: {
        bgcolor: 'rgba(15, 23, 42, 0.95)',
        bordercolor: 'rgba(148, 163, 184, 0.22)',
        font: {
          color: ANALYTICS_COLORS.slate200,
          size: 11,
          family: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        },
      },
      xaxis: {
        type: 'date',
        showspikes: true,
        spikesnap: 'cursor',
        spikemode: 'across',
        spikecolor: ANALYTICS_COLORS.slate100,
        spikethickness: 0.55,
        showline: true,
        linecolor: 'rgba(148, 163, 184, 0.3)',
        gridcolor: 'rgba(71, 85, 105, 0.18)',
        tickfont: {
          color: ANALYTICS_COLORS.slate400,
          size: 10,
          family: 'ui-monospace',
        },
      },
      yaxis: {
        title: {
          text: `${metricLabelFor(metric)} (${unit})`,
          font: {
            color: ANALYTICS_COLORS.slate400,
            size: 10,
            family: 'ui-monospace',
          },
          standoff: 8,
        },
        showspikes: true,
        spikesnap: 'cursor',
        spikecolor: ANALYTICS_COLORS.slate100,
        spikethickness: 0.55,
        showline: true,
        linecolor: 'rgba(148, 163, 184, 0.3)',
        gridcolor: 'rgba(71, 85, 105, 0.18)',
        tickfont: {
          color: ANALYTICS_COLORS.slate400,
          size: 10,
          family: 'ui-monospace',
        },
        ...(yRange ? { range: yRange, autorange: false } : {}),
      },
      shapes,
      annotations,
      uirevision: `dock-ts-${metric}-${view}`,
    }

    const config = {
      responsive: true,
      displaylogo: false,
      // Strip Plotly's heavier modebar buttons; the dock context only
      // needs basic zoom / pan and reset.
      modeBarButtonsToRemove: [
        'lasso2d', 'select2d', 'autoScale2d',
        'hoverClosestCartesian', 'hoverCompareCartesian',
        'toggleSpikelines',
      ],
    }

    const run = async () => {
      const mod = await import('plotly.js-dist-min')
      const lib = (mod as unknown as { default?: unknown }).default ?? mod
      plotly = lib
      if (disposed || !container) return
      const reactFn = (lib as { react: (...a: unknown[]) => Promise<void> }).react
      await reactFn(container, traces, layout, config)
    }
    run().catch((err) => {
      console.error('DockTimeseriesChart render error', err)
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
  }, [
    data, focused, metric, view, unit,
    showCusty, showIdb, showSigmaBands, showIqrBand, showDots,
    stats, focusedValue, focusedPercentile,
    yMin, yMax, height, sequence, hiddenSequenceIds,
  ])

  return <div ref={rootRef} className="w-full" style={{ height: `${height}px` }} />
}

function metricLabelFor(metric: AnalyticsMetricKey): string {
  switch (metric) {
    case 'fixed_rate': return 'Fixed Rate'
    case 'spread_to_mid': return 'Spread to Mid'
    case 'dv01': return 'DV01'
    case 'notional': return 'Notional'
    case 'pts': return 'PTS'
  }
}
