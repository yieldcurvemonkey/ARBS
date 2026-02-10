'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type {
  UstsRvSnapshotRequest,
  UstsRvSnapshotResponse,
  UstsRvSplineMethod,
  UstsRvValueColumn,
  UstsRvXColumn
} from '@/features/usts-rv/types'

const VALUE_OPTIONS: Array<{ key: UstsRvValueColumn; label: string }> = [
  { key: 'mmss', label: 'MMSS' },
  { key: 'ytm', label: 'YTM' },
  { key: 'clean_price', label: 'Clean Price' },
  { key: 'dirty_price', label: 'Dirty Price' },
  { key: 'mdur', label: 'Mod Duration' },
  { key: 'coupon', label: 'Coupon' }
]

const X_OPTIONS: Array<{ key: UstsRvXColumn; label: string }> = [
  { key: 'ttm', label: 'Time To Maturity' },
  { key: 'mdur', label: 'Mod Duration' }
]

const TRACE_COLORS: Record<string, string> = {
  mmss: '#f97316',
  ytm: '#38bdf8',
  clean_price: '#22c55e',
  dirty_price: '#a78bfa',
  mdur: '#f59e0b',
  coupon: '#e879f9'
}

type SplineDraft = {
  id: string
  enabled: boolean
  name: string
  method: UstsRvSplineMethod
  valueColumn: UstsRvValueColumn
  xColumn: UstsRvXColumn
  color: string
  lineWidth: number
  degree: number
  knotsText: string
  frac: number
  it: number
  excludeRanksText: string
}

type PlotlyFigureProps = {
  data: any[]
  layout: any
  config: any
}

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10)
}

function formatTimestamp(value: string | null | undefined) {
  if (!value) return '--'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(d)
}

function parseNumberList(raw: string): number[] {
  return raw
    .split(',')
    .map((tok) => Number(tok.trim()))
    .filter((v) => Number.isFinite(v))
}

function parseIntegerList(raw: string): number[] {
  return raw
    .split(',')
    .map((tok) => Number(tok.trim()))
    .filter((v) => Number.isFinite(v))
    .map((v) => Math.trunc(v))
}

function createSplineDraft(
  valueColumn: UstsRvValueColumn = 'mmss',
  xColumn: UstsRvXColumn = 'ttm'
): SplineDraft {
  const hasCrypto = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
  const id = hasCrypto ? crypto.randomUUID() : `spline-${Date.now()}-${Math.random()}`
  return {
    id,
    enabled: true,
    name: 'Custom B-Spline',
    method: 'bspline',
    valueColumn,
    xColumn,
    color: '#ef4444',
    lineWidth: 2,
    degree: 2,
    knotsText: '2,3,5,7,10,20,25',
    frac: 0.25,
    it: 50,
    excludeRanksText: '0,1,2'
  }
}

function PlotlyFigure({ data, layout, config }: PlotlyFigureProps) {
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let disposed = false
    let plotly: any = null
    const container = rootRef.current

    const run = async () => {
      const plotlyModule = await import('plotly.js-dist-min')
      plotly = plotlyModule.default ?? plotlyModule
      if (disposed || !container) return
      await plotly.react(container, data, layout, config)
    }

    run().catch((err) => {
      console.error('plotly render error', err)
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
  }, [data, layout, config])

  return <div ref={rootRef} className="h-[780px] w-full" />
}

export default function UstsRvDashboard() {
  const [asOf, setAsOf] = useState(todayIsoDate())
  const [minTtm, setMinTtm] = useState(1)
  const [xColumn, setXColumn] = useState<UstsRvXColumn>('ttm')
  const [valueColumns, setValueColumns] = useState<UstsRvValueColumn[]>(['mmss', 'ytm'])
  const [splines, setSplines] = useState<SplineDraft[]>([
    createSplineDraft('mmss', 'ttm')
  ])
  const [snapshot, setSnapshot] = useState<UstsRvSnapshotResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastRefresh, setLastRefresh] = useState<string | null>(null)

  const didInit = useRef(false)

  const buildRequest = useCallback((): UstsRvSnapshotRequest => {
    return {
      asOf: asOf || undefined,
      minTtm,
      xColumn,
      includeValues: valueColumns,
      splineConfigs: splines.map((s) => ({
        id: s.id,
        enabled: s.enabled,
        name: s.name,
        method: s.method,
        valueColumn: s.valueColumn,
        xColumn: s.xColumn,
        color: s.color,
        lineWidth: s.lineWidth,
        degree: s.method === 'bspline' ? s.degree : undefined,
        knots: s.method === 'bspline' ? parseNumberList(s.knotsText) : undefined,
        frac: s.method === 'loess' ? s.frac : undefined,
        it: s.method === 'loess' ? s.it : undefined,
        excludeRanks: parseIntegerList(s.excludeRanksText)
      }))
    }
  }, [asOf, minTtm, xColumn, valueColumns, splines])

  const fetchSnapshot = useCallback(async (requestPayload: UstsRvSnapshotRequest) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/usts-rv/snapshot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestPayload)
      })
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data?.error || 'Failed to load UST RV snapshot')
      }
      setSnapshot(data as UstsRvSnapshotResponse)
      setLastRefresh(new Date().toISOString())
    } catch (err: any) {
      setError(err?.message || 'Failed to load UST RV snapshot')
    } finally {
      setLoading(false)
    }
  }, [])

  const refresh = useCallback(() => {
    void fetchSnapshot(buildRequest())
  }, [fetchSnapshot, buildRequest])

  useEffect(() => {
    if (didInit.current) return
    didInit.current = true
    refresh()
  }, [refresh])

  const toggleValueColumn = (col: UstsRvValueColumn) => {
    setValueColumns((current) => {
      if (current.includes(col)) {
        if (current.length === 1) return current
        return current.filter((x) => x !== col)
      }
      return [...current, col]
    })
  }

  const updateSpline = <K extends keyof SplineDraft>(
    id: string,
    key: K,
    value: SplineDraft[K]
  ) => {
    setSplines((current) =>
      current.map((s) => (s.id === id ? { ...s, [key]: value } : s))
    )
  }

  const addSpline = () => {
    setSplines((current) => [...current, createSplineDraft(valueColumns[0], xColumn)])
  }

  const removeSpline = (id: string) => {
    setSplines((current) => {
      if (current.length <= 1) return current
      return current.filter((s) => s.id !== id)
    })
  }

  const traces = useMemo(() => {
    if (!snapshot) return []

    const points = snapshot.points ?? []
    const nextTraces: any[] = []

    for (const valueColumn of valueColumns) {
      const filtered = points.filter((point) => {
        const x = point[xColumn]
        const y = point[valueColumn]
        return (
          typeof x === 'number' &&
          Number.isFinite(x) &&
          typeof y === 'number' &&
          Number.isFinite(y)
        )
      })
      if (!filtered.length) continue

      nextTraces.push({
        type: 'scattergl',
        mode: 'markers',
        name: valueColumn.toUpperCase(),
        x: filtered.map((point) => point[xColumn]),
        y: filtered.map((point) => point[valueColumn]),
        customdata: filtered.map((point) => [
          point.cusip,
          point.ust_label ?? '--',
          point.oi ?? '--',
          point.rank ?? '--',
          point.ttm ?? '--',
          point.mdur ?? '--',
          point.market_timestamp ?? '--'
        ]),
        marker: {
          color: TRACE_COLORS[valueColumn] ?? '#38bdf8',
          size: filtered.map((point) => (point.rank === 0 ? 12 : 8)),
          opacity: 0.88,
          line: {
            color: '#0f172a',
            width: 1
          }
        },
        hovertemplate:
          'CUSIP %{customdata[0]}<br>' +
          'Label %{customdata[1]}<br>' +
          'OI %{customdata[2]}<br>' +
          'Rank %{customdata[3]}<br>' +
          'TTM %{customdata[4]}<br>' +
          'MDur %{customdata[5]}<br>' +
          `${valueColumn.toUpperCase()} %{y:.4f}<br>` +
          'Market TS %{customdata[6]}<extra></extra>'
      })
    }

    for (const spline of snapshot.splineSeries ?? []) {
      if (spline.error || !spline.x?.length || !spline.y?.length) continue
      nextTraces.push({
        type: 'scatter',
        mode: 'lines',
        name: `Spline: ${spline.name}`,
        x: spline.x,
        y: spline.y,
        line: {
          color: spline.color || '#ef4444',
          width: spline.lineWidth || 2,
          dash: spline.method === 'loess' ? 'solid' : 'dot'
        },
        hovertemplate:
          `${spline.name}<br>x %{x:.3f}<br>y %{y:.4f}<extra></extra>`
      })
    }

    return nextTraces
  }, [snapshot, valueColumns, xColumn])

  const layout = useMemo(
    () => ({
      template: 'plotly_dark',
      paper_bgcolor: 'rgba(2, 6, 23, 0)',
      plot_bgcolor: 'rgba(2, 6, 23, 0.65)',
      autosize: true,
      margin: { t: 64, r: 24, b: 56, l: 72 },
      title: `UST RV Snapshot: ${snapshot?.asOf ?? asOf}`,
      hovermode: 'closest',
      legend: {
        orientation: 'h',
        x: 0,
        y: 1.1,
        bgcolor: 'rgba(15, 23, 42, 0.65)'
      },
      xaxis: {
        title: xColumn === 'ttm' ? 'Time To Maturity (Years)' : 'Modified Duration',
        showspikes: true,
        spikesnap: 'cursor',
        spikemode: 'across',
        spikecolor: '#f8fafc',
        gridcolor: 'rgba(148, 163, 184, 0.15)'
      },
      yaxis: {
        title: 'Value',
        showspikes: true,
        spikesnap: 'cursor',
        spikecolor: '#f8fafc',
        gridcolor: 'rgba(148, 163, 184, 0.15)'
      },
      uirevision: 'usts-rv'
    }),
    [snapshot?.asOf, asOf, xColumn]
  )

  const config = useMemo(
    () => ({
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
    }),
    []
  )

  const splineIssues = useMemo(
    () => (snapshot?.splineSeries ?? []).filter((series) => Boolean(series.error)),
    [snapshot?.splineSeries]
  )

  const tableRows = useMemo(() => {
    if (!snapshot) return []
    return snapshot.points
      .filter((row) => row.ttm !== null)
      .slice()
      .sort((a, b) => (a.ttm ?? 0) - (b.ttm ?? 0))
      .slice(0, 16)
  }, [snapshot])

  const warnings = snapshot?.meta?.warnings ?? []

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-white">
              UST Relative Value Explorer
            </h1>
            <p className="text-sm text-slate-400">
              Notebook-based UST RV scatter with custom spline construction.
            </p>
          </div>
          <div className="text-xs text-slate-400">
            <div>As Of: {snapshot?.asOf ?? '--'}</div>
            <div>Points: {snapshot?.meta?.pointCount ?? '--'}</div>
            <div>Last Refresh: {formatTimestamp(lastRefresh)}</div>
          </div>
        </div>

        <div className="mt-6 grid gap-4 lg:grid-cols-4">
          <label className="text-xs text-slate-400">
            As Of Date
            <input
              type="date"
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
            />
          </label>
          <label className="text-xs text-slate-400">
            X Axis
            <select
              value={xColumn}
              onChange={(e) => setXColumn(e.target.value as UstsRvXColumn)}
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
            >
              {X_OPTIONS.map((opt) => (
                <option key={opt.key} value={opt.key}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-slate-400">
            Min TTM
            <input
              type="number"
              step="0.25"
              value={minTtm}
              onChange={(e) => setMinTtm(Number(e.target.value))}
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
            />
          </label>
          <div className="flex items-end">
            <button
              onClick={refresh}
              disabled={loading}
              className="w-full rounded-md bg-amber-400 px-4 py-2 text-sm font-semibold text-slate-900 disabled:opacity-60"
            >
              {loading ? 'Loading...' : 'Refresh Plot'}
            </button>
          </div>
        </div>

        <div className="mt-5">
          <div className="text-xs uppercase tracking-wide text-slate-400">
            Value Series
          </div>
          <div className="mt-2 flex flex-wrap gap-4">
            {VALUE_OPTIONS.map((opt) => (
              <label key={opt.key} className="flex items-center gap-2 text-sm text-slate-200">
                <input
                  type="checkbox"
                  checked={valueColumns.includes(opt.key)}
                  onChange={() => toggleValueColumn(opt.key)}
                />
                {opt.label}
              </label>
            ))}
          </div>
        </div>

        <div className="mt-6 rounded-xl border border-slate-800 bg-slate-950/70 p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-200">Spline Builder</h2>
            <button
              onClick={addSpline}
              className="rounded-md border border-slate-600 px-3 py-1 text-xs text-slate-200 hover:border-slate-400"
            >
              Add Spline
            </button>
          </div>
          <div className="mt-4 space-y-4">
            {splines.map((spline) => (
              <div key={spline.id} className="rounded-lg border border-slate-800 bg-slate-900/70 p-3">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  <label className="text-xs text-slate-400">
                    Name
                    <input
                      value={spline.name}
                      onChange={(e) => updateSpline(spline.id, 'name', e.target.value)}
                      className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-xs text-slate-200"
                    />
                  </label>
                  <label className="text-xs text-slate-400">
                    Method
                    <select
                      value={spline.method}
                      onChange={(e) =>
                        updateSpline(
                          spline.id,
                          'method',
                          e.target.value as UstsRvSplineMethod
                        )
                      }
                      className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-xs text-slate-200"
                    >
                      <option value="bspline">B-Spline</option>
                      <option value="loess">LOESS</option>
                    </select>
                  </label>
                  <label className="text-xs text-slate-400">
                    Value
                    <select
                      value={spline.valueColumn}
                      onChange={(e) =>
                        updateSpline(
                          spline.id,
                          'valueColumn',
                          e.target.value as UstsRvValueColumn
                        )
                      }
                      className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-xs text-slate-200"
                    >
                      {VALUE_OPTIONS.map((opt) => (
                        <option key={opt.key} value={opt.key}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-xs text-slate-400">
                    X Axis
                    <select
                      value={spline.xColumn}
                      onChange={(e) =>
                        updateSpline(spline.id, 'xColumn', e.target.value as UstsRvXColumn)
                      }
                      className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-xs text-slate-200"
                    >
                      {X_OPTIONS.map((opt) => (
                        <option key={opt.key} value={opt.key}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-xs text-slate-400">
                    Color
                    <input
                      value={spline.color}
                      onChange={(e) => updateSpline(spline.id, 'color', e.target.value)}
                      className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-xs text-slate-200"
                    />
                  </label>
                  <label className="text-xs text-slate-400">
                    Line Width
                    <input
                      type="number"
                      min={1}
                      step={0.5}
                      value={spline.lineWidth}
                      onChange={(e) =>
                        updateSpline(spline.id, 'lineWidth', Number(e.target.value))
                      }
                      className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-xs text-slate-200"
                    />
                  </label>
                  <label className="text-xs text-slate-400">
                    Exclude Ranks
                    <input
                      value={spline.excludeRanksText}
                      onChange={(e) =>
                        updateSpline(spline.id, 'excludeRanksText', e.target.value)
                      }
                      className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-xs text-slate-200"
                    />
                  </label>
                  <label className="flex items-end gap-2 text-xs text-slate-300">
                    <input
                      type="checkbox"
                      checked={spline.enabled}
                      onChange={(e) => updateSpline(spline.id, 'enabled', e.target.checked)}
                    />
                    Enabled
                  </label>
                </div>

                {spline.method === 'bspline' ? (
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    <label className="text-xs text-slate-400">
                      Degree
                      <input
                        type="number"
                        min={1}
                        max={5}
                        value={spline.degree}
                        onChange={(e) =>
                          updateSpline(spline.id, 'degree', Number(e.target.value))
                        }
                        className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-xs text-slate-200"
                      />
                    </label>
                    <label className="text-xs text-slate-400">
                      Knots (comma-separated)
                      <input
                        value={spline.knotsText}
                        onChange={(e) => updateSpline(spline.id, 'knotsText', e.target.value)}
                        className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-xs text-slate-200"
                      />
                    </label>
                  </div>
                ) : (
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    <label className="text-xs text-slate-400">
                      LOESS Frac
                      <input
                        type="number"
                        min={0.05}
                        max={1}
                        step={0.01}
                        value={spline.frac}
                        onChange={(e) => updateSpline(spline.id, 'frac', Number(e.target.value))}
                        className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-xs text-slate-200"
                      />
                    </label>
                    <label className="text-xs text-slate-400">
                      LOESS Iterations
                      <input
                        type="number"
                        min={0}
                        max={200}
                        step={1}
                        value={spline.it}
                        onChange={(e) => updateSpline(spline.id, 'it', Number(e.target.value))}
                        className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-xs text-slate-200"
                      />
                    </label>
                  </div>
                )}

                <div className="mt-3 flex justify-end">
                  <button
                    onClick={() => removeSpline(spline.id)}
                    className="rounded-md border border-rose-600 px-3 py-1 text-xs text-rose-300 hover:bg-rose-900/20"
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {!!warnings.length && (
          <div className="mt-4 rounded-md border border-amber-800 bg-amber-950/40 p-3 text-xs text-amber-200">
            {warnings.map((warn) => (
              <div key={warn}>{warn}</div>
            ))}
          </div>
        )}

        {!!splineIssues.length && (
          <div className="mt-3 rounded-md border border-rose-800 bg-rose-950/40 p-3 text-xs text-rose-200">
            {splineIssues.map((issue) => (
              <div key={issue.id}>
                {issue.name}: {issue.error}
              </div>
            ))}
          </div>
        )}

        {error && (
          <div className="mt-3 rounded-md border border-rose-800 bg-rose-950/40 p-3 text-xs text-rose-200">
            {error}
          </div>
        )}
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
        {!loading && traces.length === 0 && (
          <div className="p-4 text-sm text-slate-400">
            No data points for the selected values/x-axis.
          </div>
        )}
        {loading ? (
          <div className="p-4 text-sm text-slate-400">Loading chart...</div>
        ) : (
          <PlotlyFigure data={traces} layout={layout} config={config} />
        )}
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
        <h2 className="text-sm font-semibold text-slate-200">Snapshot Preview</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-full text-left text-xs text-slate-300">
            <thead className="text-slate-400">
              <tr>
                <th className="px-2 py-1">CUSIP</th>
                <th className="px-2 py-1">Label</th>
                <th className="px-2 py-1">Rank</th>
                <th className="px-2 py-1">TTM</th>
                <th className="px-2 py-1">MMSS</th>
                <th className="px-2 py-1">YTM</th>
                <th className="px-2 py-1">Clean Px</th>
              </tr>
            </thead>
            <tbody>
              {tableRows.map((row) => (
                <tr key={row.cusip} className="border-t border-slate-800">
                  <td className="px-2 py-1">{row.cusip}</td>
                  <td className="px-2 py-1">{row.ust_label ?? '--'}</td>
                  <td className="px-2 py-1">{row.rank ?? '--'}</td>
                  <td className="px-2 py-1">
                    {typeof row.ttm === 'number' ? row.ttm.toFixed(3) : '--'}
                  </td>
                  <td className="px-2 py-1">
                    {typeof row.mmss === 'number' ? row.mmss.toFixed(3) : '--'}
                  </td>
                  <td className="px-2 py-1">
                    {typeof row.ytm === 'number' ? row.ytm.toFixed(3) : '--'}
                  </td>
                  <td className="px-2 py-1">
                    {typeof row.clean_price === 'number'
                      ? row.clean_price.toFixed(3)
                      : '--'}
                  </td>
                </tr>
              ))}
              {tableRows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-2 py-3 text-slate-500">
                    No preview rows available.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
