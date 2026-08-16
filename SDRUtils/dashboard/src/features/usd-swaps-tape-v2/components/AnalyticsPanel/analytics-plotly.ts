// ABOUTME: The one dark Plotly layout the direction charts share.
//
// There are now two of them — a rate chart for outrights and a spread chart for
// CURVE/FLY structures — and they sit a scroll apart in the same dock. The
// single most likely way for them to mislead is to DRIFT: one gets a crosshair
// and the other does not, one paints received sky and the other green, one
// snaps the spike to the cursor and the other to data. So the layout, the
// colours and the hover behaviour are built here once and parameterised only by
// the axis titles and number formats.
import { ANALYTICS_COLORS } from './analytics-format'

export type DarkLayoutOpts = {
  height: number
  /** Top panel: the level. */
  yTitle: string
  yTickFormat: string
  /** Bottom panel: the signed distance from mid, always in bp. */
  y2Title: string
  /** Epoch-ms bounds across EVERY series — recharts and plotly alike compute
   *  their own domain from the data they are given, so a per-series domain
   *  would silently crop. */
  xRange?: [string, string]
  yRange?: [number, number]
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

/**
 * Two stacked panels on ONE shared x axis.
 *
 * They share `xaxis` so a spike line crosses both — which is the whole reason
 * to put them in one figure rather than two: the question a reader has at a
 * mark is "how far off mid was that", and the answer is directly below it.
 */
export function darkLayout(o: DarkLayoutOpts): Record<string, unknown> {
  return {
    height: o.height,
    margin: { l: 62, r: 12, t: 8, b: 26 },
    paper_bgcolor: 'rgba(2, 6, 23, 0)',
    plot_bgcolor: 'rgba(2, 6, 23, 0.4)',
    font: { color: ANALYTICS_COLORS.slate400, family: 'monospace', size: 10 },
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
      range: o.xRange,
      anchor: 'y2' as const,
    },
    yaxis: {
      ...spike,
      domain: [0.34, 1] as [number, number],
      title: { text: o.yTitle, font: tick, standoff: 6 },
      tickformat: o.yTickFormat,
      gridcolor: ANALYTICS_COLORS.slate800,
      zeroline: false,
      tickfont: tick,
      range: o.yRange,
    },
    yaxis2: {
      domain: [0, 0.26] as [number, number],
      title: { text: o.y2Title, font: tick, standoff: 6 },
      tickformat: '+.2f',
      gridcolor: ANALYTICS_COLORS.slate800,
      zerolinecolor: ANALYTICS_COLORS.slate700,
      zeroline: true,
      tickfont: tick,
    },
  }
}

export const DARK_CONFIG = {
  responsive: true,
  displaylogo: false,
  scrollZoom: true,
  modeBarButtonsToRemove: [
    'lasso2d', 'select2d', 'hoverClosestCartesian', 'hoverCompareCartesian',
  ],
}

/**
 * Load plotly and render, once, into `el`.
 *
 * plotly.js-dist-min is ~3MB and has no SSR story, so it is imported inside the
 * effect and never reaches the initial bundle. Returns a disposer that purges
 * the graph — without it, switching dock tabs leaks a full WebGL/SVG graph per
 * mount.
 */
export async function renderPlot(
  el: HTMLElement,
  traces: unknown[],
  layout: Record<string, unknown>,
  isCancelled: () => boolean,
): Promise<unknown> {
  const modmod = await import('plotly.js-dist-min')
  const lib = (modmod as unknown as { default?: unknown }).default ?? modmod
  if (isCancelled()) return lib
  const reactFn = (lib as { react: (...a: unknown[]) => Promise<void> }).react
  await reactFn(el, traces, layout, DARK_CONFIG)
  return lib
}

export function purgePlot(lib: unknown, el: HTMLElement): void {
  if (!lib) return
  try {
    ;(lib as { purge: (e: HTMLElement) => void }).purge(el)
  } catch {
    /* ignore */
  }
}

/** Plotly wants ISO strings on a date axis, not epoch ms. */
export function iso(t: number): string {
  return new Date(t).toISOString()
}
