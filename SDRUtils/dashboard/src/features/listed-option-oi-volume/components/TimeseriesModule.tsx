'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useListedOptionTimeseriesMulti } from '../hooks/useListedOptionTimeseriesMulti'
import { TimeseriesCommandBar } from './TimeseriesCommandBar'
import type {
  ListedOptionRange,
  ListedOptionSearchOption,
  ListedOptionSeriesConfig,
  ListedOptionTimeseriesFormulaConfig,
} from '../types'
import {
  buildFormulaSeries,
  formatNumber,
  formatSeriesConfigLabel,
  formatSignedNumber,
  getSeriesConfigKey,
  normalizeFormulaLegs,
  normalizeFormulaWeight,
  shouldPrefetchHistoricalTimeseries,
} from '../utils'

type Props = {
  searchOptions: ListedOptionSearchOption[]
  selectedSeries: ListedOptionSeriesConfig[]
  onSelectedSeriesChange: (series: ListedOptionSeriesConfig[]) => void
  periodBusinessDays: number
}

type WindowMode = 'preset' | 'custom'
type DisplayTransform = 'absolute' | 'rebased'
type FormulaDraftLeg = { id: string; seriesId: string; weight: number }

const RANGE_OPTIONS: ListedOptionRange[] = ['1M', '3M', '6M', '1Y', 'ALL']
const SERIES_COLORS = ['#38bdf8', '#f59e0b', '#34d399', '#f472b6', '#a78bfa', '#fb7185']
const INPUT_CLASS =
  'h-8 rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 text-[11px] text-slate-100 outline-none transition focus:border-slate-500'
const PLOTLY_FIGURE_HEIGHT_PX = 476

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10)
}

function shiftIsoDate(dateIso: string, days: number) {
  const parsed = new Date(`${dateIso}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return dateIso
  parsed.setUTCDate(parsed.getUTCDate() + days)
  return parsed.toISOString().slice(0, 10)
}

function makeClientId(prefix: string) {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}-${crypto.randomUUID().slice(0, 8)}`
  }
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`
}

function normalizePlotlyDateValue(value: unknown): string | null {
  if (typeof value === 'string') {
    const parsed = new Date(value)
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString().slice(0, 10)
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    const parsed = new Date(value)
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString().slice(0, 10)
  }
  return null
}

function extractPlotlyRelayoutDateRange(eventData: Record<string, unknown> | null | undefined) {
  if (!eventData) return { startDate: null, endDate: null }
  const directStart = normalizePlotlyDateValue(eventData['xaxis.range[0]'])
  const directEnd = normalizePlotlyDateValue(eventData['xaxis.range[1]'])
  if (directStart && directEnd) {
    return { startDate: directStart, endDate: directEnd }
  }

  const xaxis = eventData.xaxis as { range?: unknown } | undefined
  const range = xaxis?.range
  if (Array.isArray(range) && range.length >= 2) {
    return {
      startDate: normalizePlotlyDateValue(range[0]),
      endDate: normalizePlotlyDateValue(range[1]),
    }
  }

  return { startDate: null, endDate: null }
}

function transformValues(values: Array<number | null>, displayTransform: DisplayTransform) {
  if (displayTransform === 'absolute') return values
  const base = values.find((value): value is number => value !== null && Number.isFinite(value)) ?? null
  if (base === null || Math.abs(base) < 1e-12) return values.map(() => null)
  return values.map((value) => (value === null ? null : (value / base) * 100))
}

function createFormulaDraftFromSeries(series: ListedOptionSeriesConfig[]): FormulaDraftLeg[] {
  const ids = series.map((config) => getSeriesConfigKey(config))
  return [
    { id: makeClientId('formula-leg'), seriesId: ids[0] ?? '', weight: 1 },
    { id: makeClientId('formula-leg'), seriesId: ids[1] ?? '', weight: -1 },
  ]
}

function PlotlyFigure(props: {
  data: any[]
  layout: any
  config: any
  heightPx: number
  onRelayout?: (eventData: Record<string, unknown>) => void
}) {
  const rootRef = useRef<HTMLDivElement>(null)
  const relayoutHandlerRef = useRef(props.onRelayout)

  useEffect(() => {
    relayoutHandlerRef.current = props.onRelayout
  }, [props.onRelayout])

  useEffect(() => {
    let disposed = false
    let plotly: any = null
    const container = rootRef.current as (HTMLDivElement & {
      on?: (event: string, handler: (eventData: Record<string, unknown>) => void) => void
      removeListener?: (event: string, handler: (eventData: Record<string, unknown>) => void) => void
    }) | null
    const handleRelayout = (eventData: Record<string, unknown>) => {
      relayoutHandlerRef.current?.(eventData)
    }

    const run = async () => {
      const plotlyModule = await import('plotly.js-dist-min')
      plotly = (plotlyModule as any).default ?? plotlyModule
      if (disposed || !container) return
      await plotly.react(container, props.data, props.layout, props.config)
      if (typeof container.on === 'function') {
        if (typeof container.removeListener === 'function') {
          container.removeListener('plotly_relayout', handleRelayout)
        }
        container.on('plotly_relayout', handleRelayout)
      }
    }

    run().catch((error) => {
      console.error('listed-option-oi-volume timeseries render error', error)
    })

    return () => {
      disposed = true
      if (container && typeof container.removeListener === 'function') {
        container.removeListener('plotly_relayout', handleRelayout)
      }
      if (plotly && container) {
        try {
          plotly.purge(container)
        } catch {
          // no-op
        }
      }
    }
  }, [props.config, props.data, props.heightPx, props.layout])

  return <div ref={rootRef} className="w-full" style={{ height: `${props.heightPx}px` }} />
}

export function TimeseriesModule({
  searchOptions,
  selectedSeries,
  onSelectedSeriesChange,
  periodBusinessDays,
}: Props) {
  const [range, setRange] = useState<ListedOptionRange>('6M')
  const [windowMode, setWindowMode] = useState<WindowMode>('preset')
  const [customStartDate, setCustomStartDate] = useState(() => shiftIsoDate(todayIsoDate(), -180))
  const [customEndDate, setCustomEndDate] = useState(() => todayIsoDate())
  const [displayTransform, setDisplayTransform] = useState<DisplayTransform>('absolute')
  const [showChartLegend, setShowChartLegend] = useState(true)
  const [seriesRightAxisIds, setSeriesRightAxisIds] = useState<string[]>([])
  const [seriesHiddenIds, setSeriesHiddenIds] = useState<string[]>([])
  const [formulaConfigs, setFormulaConfigs] = useState<ListedOptionTimeseriesFormulaConfig[]>([])
  const [formulaDraftName, setFormulaDraftName] = useState('')
  const [formulaDraftAxis, setFormulaDraftAxis] = useState<'y' | 'y2'>('y2')
  const [formulaDraftScaleBy100, setFormulaDraftScaleBy100] = useState(false)
  const [formulaDraftLegs, setFormulaDraftLegs] = useState<FormulaDraftLeg[]>(() =>
    createFormulaDraftFromSeries(selectedSeries)
  )
  const [formulaError, setFormulaError] = useState<string | null>(null)
  const [showFormulaBuilder, setShowFormulaBuilder] = useState(false)

  const hasInvalidCustomWindow =
    windowMode === 'custom' && customStartDate.trim() && customEndDate.trim() && customStartDate > customEndDate

  const { data, loading, loadingHistorical, hasMoreHistorical, error, loadHistorical } =
    useListedOptionTimeseriesMulti({
      series: hasInvalidCustomWindow ? [] : selectedSeries,
      range,
      startDate: windowMode === 'custom' ? customStartDate : undefined,
      endDate: windowMode === 'custom' ? customEndDate : undefined,
      periodBusinessDays,
    })

  const selectedSeriesIds = useMemo(
    () => selectedSeries.map((config) => getSeriesConfigKey(config)),
    [selectedSeries]
  )

  useEffect(() => {
    const selectedSet = new Set(selectedSeriesIds)
    setSeriesRightAxisIds((current) => current.filter((id) => selectedSet.has(id)))
    setSeriesHiddenIds((current) => current.filter((id) => selectedSet.has(id)))
    setFormulaConfigs((current) =>
      current
        .map((config) => ({
          ...config,
          legs: config.legs.filter((leg) => selectedSet.has(leg.seriesId)),
        }))
        .filter((config) => normalizeFormulaLegs(config.legs).length >= 2)
    )
    setFormulaDraftLegs((current) => {
      if (!current.length) return createFormulaDraftFromSeries(selectedSeries)
      return current.map((leg, index) => ({
        ...leg,
        seriesId: selectedSet.has(leg.seriesId) ? leg.seriesId : selectedSeriesIds[index] ?? selectedSeriesIds[0] ?? '',
      }))
    })
  }, [selectedSeries, selectedSeriesIds])

  const handleTimeseriesRelayout = useCallback(
    (eventData: Record<string, unknown>) => {
      const { startDate, endDate } = extractPlotlyRelayoutDateRange(eventData)
      if (
        !shouldPrefetchHistoricalTimeseries({
          loadedStartDate: data?.startDate ?? null,
          viewportStartDate: startDate,
          viewportEndDate: endDate,
          hasMoreHistorical,
          loadingHistorical,
        })
      ) {
        return
      }

      void loadHistorical()
    },
    [data?.startDate, hasMoreHistorical, loadHistorical, loadingHistorical]
  )

  const seriesLabelsById = useMemo(
    () =>
      new Map(
        selectedSeries.map((config) => [getSeriesConfigKey(config), formatSeriesConfigLabel(config)])
      ),
    [selectedSeries]
  )

  const seriesColorsById = useMemo(
    () =>
      new Map(
        selectedSeries.map((config, index) => [
          getSeriesConfigKey(config),
          SERIES_COLORS[index % SERIES_COLORS.length],
        ])
      ),
    [selectedSeries]
  )

  const seriesMap = useMemo(
    () => new Map((data?.series ?? []).map((series) => [series.id, series])),
    [data?.series]
  )

  const formulaSeries = useMemo(
    () =>
      formulaConfigs
        .map((config) => buildFormulaSeries(config, seriesMap))
        .filter((series): series is NonNullable<typeof series> => Boolean(series)),
    [formulaConfigs, seriesMap]
  )

  const addSeries = useCallback(
    (config: ListedOptionSeriesConfig) => {
      onSelectedSeriesChange(
        Array.from(
          new Map(
            [...selectedSeries, config].map((entry) => [getSeriesConfigKey(entry), entry])
          ).values()
        )
      )
    },
    [onSelectedSeriesChange, selectedSeries]
  )

  const addSeriesBatch = useCallback(
    (configs: ListedOptionSeriesConfig[]) => {
      onSelectedSeriesChange(
        Array.from(
          new Map(
            [...selectedSeries, ...configs].map((entry) => [getSeriesConfigKey(entry), entry])
          ).values()
        )
      )
    },
    [onSelectedSeriesChange, selectedSeries]
  )

  const removeSeries = useCallback(
    (seriesId: string) => {
      onSelectedSeriesChange(
        selectedSeries.filter((config) => getSeriesConfigKey(config) !== seriesId)
      )
    },
    [onSelectedSeriesChange, selectedSeries]
  )

  const addFormulaFromCommand = ({
    name,
    series,
    legs,
  }: {
    name: string
    series: ListedOptionSeriesConfig[]
    legs: Array<{ seriesId: string; weight: number }>
  }) => {
    const normalizedLegs = normalizeFormulaLegs(legs)
    if (normalizedLegs.length < 2) return

    addSeriesBatch(series)
    setFormulaConfigs((current) => [
      ...current,
      {
        id: makeClientId('formula'),
        name,
        yaxis: 'y2',
        scaleBy100: false,
        legs: normalizedLegs,
      },
    ])
  }

  const updateFormulaDraftLeg = (
    legId: string,
    patch: Partial<Pick<FormulaDraftLeg, 'seriesId' | 'weight'>>
  ) => {
    setFormulaDraftLegs((current) =>
      current.map((leg) => (leg.id === legId ? { ...leg, ...patch } : leg))
    )
  }

  const addFormulaDraftLeg = () => {
    setFormulaDraftLegs((current) => [
      ...current,
      {
        id: makeClientId('formula-leg'),
        seriesId: selectedSeriesIds[0] ?? '',
        weight: current.length % 2 === 0 ? 1 : -1,
      },
    ])
  }

  const addFormulaSeries = () => {
    const normalizedLegs = normalizeFormulaLegs(formulaDraftLegs)
    if (normalizedLegs.length < 2) {
      setFormulaError('A formula needs at least two valid legs.')
      return
    }

    setFormulaConfigs((current) => [
      ...current,
      {
        id: makeClientId('formula'),
        name: formulaDraftName.trim() || `Formula ${current.length + 1}`,
        yaxis: formulaDraftAxis,
        scaleBy100: formulaDraftScaleBy100,
        legs: normalizedLegs,
      },
    ])
    setFormulaError(null)
    setFormulaDraftName('')
    setFormulaDraftAxis('y2')
    setFormulaDraftScaleBy100(false)
    setFormulaDraftLegs(createFormulaDraftFromSeries(selectedSeries))
  }

  const formulaDraftExpression = useMemo(
    () =>
      normalizeFormulaLegs(formulaDraftLegs)
        .map((leg, index) => {
          const label = seriesLabelsById.get(leg.seriesId) ?? leg.seriesId
          const token = `${leg.weight >= 0 ? '+' : ''}${leg.weight} * ${label}`
          return index === 0 ? token.replace(/^\+/, '') : token
        })
        .join(' '),
    [formulaDraftLegs, seriesLabelsById]
  )

  const chartSeries = useMemo(() => {
    const baseSeries = (data?.series ?? []).map((series) => ({
      id: series.id,
      label: series.label,
      yaxis: seriesRightAxisIds.includes(series.id) ? 'y2' : 'y',
      color: seriesColorsById.get(series.id) ?? SERIES_COLORS[0],
      points: series.points,
      hidden: seriesHiddenIds.includes(series.id),
    }))
    const derivedSeries = formulaSeries.map((series, index) => ({
      id: series.id,
      label: series.name,
      yaxis: series.yaxis,
      color: SERIES_COLORS[(baseSeries.length + index) % SERIES_COLORS.length],
      points: series.points,
      hidden: false,
    }))
    return [...baseSeries, ...derivedSeries]
  }, [data?.series, formulaSeries, seriesColorsById, seriesHiddenIds, seriesRightAxisIds])

  const timeseriesTraces = useMemo(
    () =>
      chartSeries
        .filter((series) => !series.hidden)
        .map((series) => ({
          type: 'scatter',
          mode: 'lines',
          name: series.label,
          x: series.points.map((point) => point.asOf),
          y: transformValues(
            series.points.map((point) => point.value),
            displayTransform
          ),
          yaxis: series.yaxis,
          line: {
            color: series.color,
            width: 2,
          },
          hovertemplate: '%{x}<br>%{fullData.name}: %{y:,.2f}<extra></extra>',
        })),
    [chartSeries, displayTransform]
  )

  const timeseriesLayout = useMemo(
    () => ({
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(15,23,42,0.65)',
      margin: { l: 56, r: 56, t: 28, b: 44 },
      hovermode: 'x unified',
      legend: {
        orientation: 'h',
        x: 0,
        y: 1.14,
        font: { size: 11, color: '#cbd5e1' },
      },
      showlegend: showChartLegend,
      xaxis: {
        gridcolor: 'rgba(148,163,184,0.14)',
        tickfont: { color: '#94a3b8', size: 11 },
        zeroline: false,
      },
      yaxis: {
        title: { text: displayTransform === 'rebased' ? 'Index' : 'Value', font: { color: '#cbd5e1' } },
        gridcolor: 'rgba(148,163,184,0.14)',
        tickfont: { color: '#cbd5e1', size: 11 },
      },
      yaxis2: {
        title: { text: displayTransform === 'rebased' ? 'Index' : 'Value', font: { color: '#cbd5e1' } },
        overlaying: 'y',
        side: 'right',
        tickfont: { color: '#cbd5e1', size: 11 },
      },
    }),
    [displayTransform, showChartLegend]
  )

  const warnings = useMemo(
    () =>
      [
        ...(hasInvalidCustomWindow
          ? ['Custom window is invalid. Start date must be on or before end date.']
          : []),
        ...(data?.warnings ?? []),
      ],
    [data?.warnings, hasInvalidCustomWindow]
  )

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-800/80 bg-slate-950/70 p-3">
        <div className="flex flex-wrap items-end gap-3">
          <TimeseriesCommandBar
            options={searchOptions}
            selectedSeriesIds={selectedSeriesIds}
            onAddSeries={addSeries}
            onAddFormula={addFormulaFromCommand}
          />
          <label>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
              Range
            </div>
            <select
              value={range}
              onChange={(event) => setRange(event.target.value as ListedOptionRange)}
              className={`${INPUT_CLASS} min-w-[90px]`}
            >
              {RANGE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
              Window
            </div>
            <select
              value={windowMode}
              onChange={(event) => setWindowMode(event.target.value as WindowMode)}
              className={`${INPUT_CLASS} min-w-[112px]`}
            >
              <option value="preset">Preset</option>
              <option value="custom">Custom</option>
            </select>
          </label>
          {windowMode === 'custom' ? (
            <>
              <label>
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                  Start
                </div>
                <input
                  type="date"
                  value={customStartDate}
                  onChange={(event) => setCustomStartDate(event.target.value)}
                  className={INPUT_CLASS}
                />
              </label>
              <label>
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                  End
                </div>
                <input
                  type="date"
                  value={customEndDate}
                  onChange={(event) => setCustomEndDate(event.target.value)}
                  className={INPUT_CLASS}
                />
              </label>
            </>
          ) : null}
          <label>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
              Transform
            </div>
            <select
              value={displayTransform}
              onChange={(event) => setDisplayTransform(event.target.value as DisplayTransform)}
              className={`${INPUT_CLASS} min-w-[120px]`}
            >
              <option value="absolute">Absolute</option>
              <option value="rebased">Rebased</option>
            </select>
          </label>
          <label className="mb-1 inline-flex items-center gap-2 text-[11px] text-slate-300">
            <input
              type="checkbox"
              checked={showChartLegend}
              onChange={(event) => setShowChartLegend(event.target.checked)}
            />
            Show legend
          </label>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800/80 bg-slate-950/70">
        <div className="flex items-center justify-between gap-3 border-b border-slate-800/80 px-3 py-2">
          <div>
            <div className="text-sm font-semibold text-slate-100">Selected Series</div>
            <div className="text-[11px] text-slate-500">
              {selectedSeries.length} base series | {formulaConfigs.length} formulas | {periodBusinessDays}D lag
            </div>
          </div>
          <button
            type="button"
            onClick={() => onSelectedSeriesChange([])}
            className="rounded-md border border-slate-700/80 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-300 transition hover:border-slate-500 hover:text-white"
          >
            Clear
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-[11px] text-slate-300">
            <thead className="bg-slate-900/70 text-[10px] uppercase tracking-[0.16em] text-slate-500">
              <tr>
                <th className="px-3 py-2">Series</th>
                <th className="px-3 py-2">Axis</th>
                <th className="px-3 py-2">Visible</th>
                <th className="px-3 py-2">Latest</th>
                <th className="px-3 py-2">1D</th>
                <th className="px-3 py-2">Action</th>
              </tr>
            </thead>
            <tbody>
              {selectedSeries.length ? (
                selectedSeries.map((config) => {
                  const seriesId = getSeriesConfigKey(config)
                  const series = data?.series.find((entry) => entry.id === seriesId)
                  const latest = series?.points.at(-1)?.value ?? null
                  const prior = series && series.points.length >= 2 ? series.points.at(-2)?.value ?? null : null
                  const change1d = latest !== null && prior !== null ? latest - prior : null

                  return (
                    <tr key={seriesId} className="border-t border-slate-800/70">
                      <td className="px-3 py-2 font-medium text-slate-100">{formatSeriesConfigLabel(config)}</td>
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          onClick={() =>
                            setSeriesRightAxisIds((current) =>
                              current.includes(seriesId)
                                ? current.filter((id) => id !== seriesId)
                                : [...current, seriesId]
                            )
                          }
                          className="rounded border border-slate-700/80 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-slate-300"
                        >
                          {seriesRightAxisIds.includes(seriesId) ? 'RHS' : 'LHS'}
                        </button>
                      </td>
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          onClick={() =>
                            setSeriesHiddenIds((current) =>
                              current.includes(seriesId)
                                ? current.filter((id) => id !== seriesId)
                                : [...current, seriesId]
                            )
                          }
                          className="rounded border border-slate-700/80 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-slate-300"
                        >
                          {seriesHiddenIds.includes(seriesId) ? 'Off' : 'On'}
                        </button>
                      </td>
                      <td className="px-3 py-2 font-mono text-slate-100">{formatNumber(latest, 2)}</td>
                      <td className="px-3 py-2 font-mono text-slate-100">{formatSignedNumber(change1d, 2)}</td>
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          onClick={() => removeSeries(seriesId)}
                          className="rounded border border-slate-700/80 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-slate-400 transition hover:border-slate-500 hover:text-white"
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  )
                })
              ) : (
                <tr>
                  <td colSpan={6} className="px-3 py-4 text-center text-[11px] text-slate-500">
                    No series selected. Click matrix cells or use the command bar.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800/80 bg-slate-950/70">
        <div className="flex items-center justify-between gap-3 border-b border-slate-800/80 px-3 py-2">
          <div>
            <div className="text-sm font-semibold text-slate-100">Formula Builder</div>
            <div className="text-[11px] text-slate-500">
              Add weighted custom formulas on top of base series.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowFormulaBuilder((current) => !current)}
            className="rounded-md border border-slate-700/80 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-300 transition hover:border-slate-500 hover:text-white"
          >
            {showFormulaBuilder ? 'Collapse' : 'Expand'}
          </button>
        </div>

        {showFormulaBuilder ? (
          <div className="space-y-3 px-3 py-3">
            <div className="grid gap-3 xl:grid-cols-[minmax(0,1.2fr)_140px_110px_auto]">
              <label className="text-[10px] text-slate-400">
                Name
                <input
                  type="text"
                  value={formulaDraftName}
                  onChange={(event) => setFormulaDraftName(event.target.value)}
                  placeholder={`Formula ${formulaConfigs.length + 1}`}
                  className="mt-1 w-full rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 py-1.5 text-[11px] text-slate-200"
                />
              </label>
              <label className="text-[10px] text-slate-400">
                Axis
                <select
                  value={formulaDraftAxis}
                  onChange={(event) => setFormulaDraftAxis(event.target.value as 'y' | 'y2')}
                  className="mt-1 w-full rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 py-1.5 text-[11px] text-slate-200"
                >
                  <option value="y">Left Axis</option>
                  <option value="y2">Right Axis</option>
                </select>
              </label>
              <label className="inline-flex items-center gap-2 self-end pb-2 text-[10px] text-slate-300">
                <input
                  type="checkbox"
                  checked={formulaDraftScaleBy100}
                  onChange={(event) => setFormulaDraftScaleBy100(event.target.checked)}
                />
                x100
              </label>
              <div className="flex items-end gap-2">
                <button
                  type="button"
                  onClick={addFormulaSeries}
                  className="rounded-md border border-amber-500/60 bg-amber-500/12 px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-amber-100 transition hover:border-amber-400"
                >
                  Add formula
                </button>
                <button
                  type="button"
                  onClick={addFormulaDraftLeg}
                  className="rounded-md border border-slate-700/80 px-2.5 py-1.5 text-[10px] text-slate-300 transition hover:border-slate-500 hover:text-white"
                >
                  Add leg
                </button>
              </div>
            </div>

            <div className="space-y-2">
              {formulaDraftLegs.map((leg, index) => (
                <div key={leg.id} className="grid gap-2 md:grid-cols-[minmax(0,1fr)_112px_84px]">
                  <label className="text-[10px] text-slate-400">
                    Leg {index + 1}
                    <select
                      value={leg.seriesId}
                      onChange={(event) => updateFormulaDraftLeg(leg.id, { seriesId: event.target.value })}
                      className="mt-1 w-full rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 py-1.5 text-[11px] text-slate-200"
                    >
                      <option value="">Select series</option>
                      {selectedSeries.map((series) => {
                        const seriesId = getSeriesConfigKey(series)
                        return (
                          <option key={seriesId} value={seriesId}>
                            {formatSeriesConfigLabel(series)}
                          </option>
                        )
                      })}
                    </select>
                  </label>
                  <label className="text-[10px] text-slate-400">
                    Weight
                    <input
                      type="number"
                      step="0.01"
                      value={leg.weight}
                      onChange={(event) =>
                        updateFormulaDraftLeg(leg.id, {
                          weight: normalizeFormulaWeight(event.target.value),
                        })
                      }
                      className="mt-1 w-full rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 py-1.5 text-[11px] text-slate-200"
                    />
                  </label>
                  <div className="flex items-end">
                    <button
                      type="button"
                      onClick={() =>
                        setFormulaDraftLegs((current) => current.filter((entry) => entry.id !== leg.id))
                      }
                      disabled={formulaDraftLegs.length <= 2}
                      className="w-full rounded-md border border-slate-700/80 px-2 py-1.5 text-[10px] text-slate-300 disabled:opacity-40"
                    >
                      Remove
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <div className="text-[10px] text-slate-500">Draft: {formulaDraftExpression || '--'}</div>
            {formulaError ? (
              <div className="rounded-md border border-rose-900/50 bg-rose-950/35 px-2.5 py-2 text-[11px] text-rose-200">
                {formulaError}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {warnings.length ? (
        <div className="rounded-lg border border-amber-900/50 bg-amber-950/30 px-4 py-3 text-xs text-amber-200">
          {warnings.map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </div>
      ) : null}

      {error ? (
        <div className="rounded-lg border border-rose-900/50 bg-rose-950/35 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      ) : null}

      <div className="rounded-lg border border-slate-800/80 bg-slate-950/65 p-2">
        {loadingHistorical && !loading ? (
          <div className="px-1 pb-2 text-[11px] uppercase tracking-[0.16em] text-cyan-200/80">
            Loading earlier history...
          </div>
        ) : null}
        {loading ? (
          <div
            className="flex items-center justify-center text-sm text-slate-400"
            style={{ height: `${PLOTLY_FIGURE_HEIGHT_PX}px` }}
          >
            Loading timeseries...
          </div>
        ) : timeseriesTraces.length ? (
          <PlotlyFigure
            data={timeseriesTraces}
            layout={timeseriesLayout}
            config={{ displayModeBar: false, responsive: true }}
            heightPx={PLOTLY_FIGURE_HEIGHT_PX}
            onRelayout={handleTimeseriesRelayout}
          />
        ) : (
          <div
            className="flex items-center justify-center text-sm text-slate-500"
            style={{ height: `${PLOTLY_FIGURE_HEIGHT_PX}px` }}
          >
            Add series from the matrix or command bar to populate the chart.
          </div>
        )}
      </div>
    </div>
  )
}
