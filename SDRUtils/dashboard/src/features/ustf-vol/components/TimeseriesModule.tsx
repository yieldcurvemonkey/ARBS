'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

import { SERIES_COLORS, STANDARD_PAIRS } from '../constants'
import { TimeseriesCommandBar } from './TimeseriesCommandBar'
import { useUstfTimeseriesMulti } from '../hooks/useUstfTimeseriesMulti'
import type { SeriesConfig, TimeRange, TimeseriesAxis } from '../types'
import {
  buildFormulaSeries,
  buildTechnicalStudySeries,
  computeTimeseriesHeadlineStats,
  formatSeriesConfigLabel,
  formatSignedNumber,
  formatTechnicalStudyShortLabel,
  formatVol,
  getSeriesConfigKey,
  normalizeFormulaLegs,
  normalizeFormulaWeight,
  shouldPrefetchHistoricalTimeseries,
  type TimeseriesFormulaConfig,
  type TimeseriesTechnicalStudyConfig,
  type TimeseriesTechnicalStudyKind,
} from '../utils'

type WindowMode = 'preset' | 'custom'
type DisplayTransform = 'absolute' | 'rebased'
type FormulaDraftLeg = { id: string; seriesId: string; weight: number }
type TechnicalStudyDraft = { kind: TimeseriesTechnicalStudyKind; window: number }

const LABEL_CLASS =
  'block text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500'
const INPUT_CLASS =
  'h-7 rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 text-[11px] text-slate-100 outline-none transition focus:border-slate-500'
const RANGE_OPTIONS: TimeRange[] = ['1M', '3M', '6M', '1Y', 'ALL']
const FORMULA_COLORS = ['#fbbf24', '#22d3ee', '#34d399', '#f472b6', '#c084fc', '#fb7185']
const DEFAULT_PAIR = STANDARD_PAIRS[0]
const DEFAULT_SELECTED_SERIES: SeriesConfig[] = [DEFAULT_PAIR.series1, DEFAULT_PAIR.series2]
// CSS zoom desynchronizes Plotly hover geometry from the visible cursor position.
const PLOTLY_FIGURE_HEIGHT_PX = 476
const TECHNICAL_STUDY_WINDOW_OPTIONS = [5, 10, 20, 40, 60, 120]
const DEFAULT_TECHNICAL_STUDY_DRAFT: TechnicalStudyDraft = { kind: 'ema', window: 20 }
const TECHNICAL_STUDY_OPTIONS: Array<{
  value: TimeseriesTechnicalStudyKind
  label: string
}> = [
  { value: 'sma', label: 'SMA' },
  { value: 'ema', label: 'EMA' },
  { value: 'bollinger_mid', label: 'Bollinger mid' },
  { value: 'bollinger_upper', label: 'Bollinger upper' },
  { value: 'bollinger_lower', label: 'Bollinger lower' },
  { value: 'rolling_zscore', label: 'Rolling z-score' },
  { value: 'realized_vol', label: 'Realized vol' },
  { value: 'momentum', label: 'Momentum' },
  { value: 'rate_of_change', label: 'ROC %' },
]

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10)
}

function shiftIsoDate(dateIso: string, days: number) {
  const parsed = new Date(`${dateIso}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return dateIso
  parsed.setUTCDate(parsed.getUTCDate() + days)
  return parsed.toISOString().slice(0, 10)
}

function normalizePlotlyDateValue(value: unknown): string | null {
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) return null
    const parsed = new Date(trimmed)
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString().slice(0, 10)
  }

  if (typeof value === 'number' && Number.isFinite(value)) {
    const parsed = new Date(value)
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString().slice(0, 10)
  }

  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return value.toISOString().slice(0, 10)
  }

  return null
}

function extractPlotlyRelayoutDateRange(
  eventData: Record<string, unknown> | null | undefined
): { startDate: string | null; endDate: string | null } {
  if (!eventData) {
    return { startDate: null, endDate: null }
  }

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

function makeClientId(prefix: string) {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}-${crypto.randomUUID().slice(0, 8)}`
  }
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`
}

function segmentButtonClass(active: boolean) {
  return [
    'px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] transition',
    active
      ? 'bg-slate-100 text-slate-950'
      : 'bg-slate-950/70 text-slate-300 hover:bg-slate-900 hover:text-white',
  ].join(' ')
}

function axisShortLabel(axis: TimeseriesAxis) {
  return axis === 'y2' ? 'RHS' : 'LHS'
}

function firstFiniteValue(values: Array<number | null>) {
  return values.find((value): value is number => value !== null && Number.isFinite(value)) ?? null
}

function transformValues(
  values: Array<number | null>,
  displayTransform: DisplayTransform,
  fixedBase?: number | null
) {
  if (displayTransform === 'absolute') return values
  const base = fixedBase ?? firstFiniteValue(values)
  if (base === undefined || base === null || Math.abs(base) < 1e-12) {
    return values.map(() => null)
  }
  return values.map((value) => (value === null ? null : (value / base) * 100))
}

function shouldTransformTechnicalStudy(kind: TimeseriesTechnicalStudyKind) {
  return (
    kind === 'sma' ||
    kind === 'ema' ||
    kind === 'bollinger_mid' ||
    kind === 'bollinger_upper' ||
    kind === 'bollinger_lower'
  )
}

function technicalStudyLineStyle(kind: TimeseriesTechnicalStudyKind) {
  switch (kind) {
    case 'sma':
      return { dash: 'dash', width: 1.9 }
    case 'ema':
      return { dash: 'solid', width: 2 }
    case 'bollinger_mid':
      return { dash: 'dot', width: 1.6 }
    case 'bollinger_upper':
    case 'bollinger_lower':
      return { dash: 'dot', width: 1.4 }
    case 'rolling_zscore':
      return { dash: 'dashdot', width: 1.8 }
    case 'realized_vol':
      return { dash: 'longdash', width: 1.8 }
    case 'momentum':
      return { dash: 'dash', width: 1.8 }
    case 'rate_of_change':
      return { dash: 'longdashdot', width: 1.8 }
  }
}

function technicalStudyValueLabel(
  kind: TimeseriesTechnicalStudyKind,
  displayTransform: DisplayTransform
) {
  switch (kind) {
    case 'sma':
    case 'ema':
    case 'bollinger_mid':
    case 'bollinger_upper':
    case 'bollinger_lower':
      return displayTransform === 'rebased' ? 'Index' : 'NVOL'
    case 'rolling_zscore':
      return 'Z-score'
    case 'realized_vol':
      return 'Ann. sigma(dNVOL)'
    case 'momentum':
      return 'dNVOL'
    case 'rate_of_change':
      return 'ROC %'
  }
}

function statValueTone(value: number | null) {
  if (value === null || Math.abs(value) < 1e-12) return 'text-slate-100'
  return value > 0 ? 'text-emerald-200' : 'text-rose-200'
}

function formatStatPercent(value: number | null, decimals = 0) {
  if (value === null || !Number.isFinite(value)) return '--'
  return `${value.toFixed(decimals)}%`
}

function createFormulaDraftFromSeries(series: SeriesConfig[]): FormulaDraftLeg[] {
  const ids = series.map((config) => getSeriesConfigKey(config))
  return [
    { id: makeClientId('formula-leg'), seriesId: ids[0] ?? '', weight: 1 },
    { id: makeClientId('formula-leg'), seriesId: ids[1] ?? '', weight: -1 },
  ]
}

function makeUniqueFormulaName(baseName: string, existing: TimeseriesFormulaConfig[]) {
  const normalized = baseName.trim() || 'Formula'
  const names = new Set(existing.map((config) => config.name))
  if (!names.has(normalized)) return normalized
  let suffix = 2
  while (names.has(`${normalized} (${suffix})`)) suffix += 1
  return `${normalized} (${suffix})`
}

function renderFormulaExpression(
  legs: Array<{ seriesId: string; weight: number }>,
  seriesLabelsById: Map<string, string>
) {
  if (!legs.length) return '--'
  return legs
    .map((leg, index) => {
      const label = seriesLabelsById.get(leg.seriesId) ?? leg.seriesId
      const magnitude = Number.isInteger(Math.abs(leg.weight))
        ? Math.abs(leg.weight).toFixed(0)
        : Math.abs(leg.weight).toFixed(4)
      const token = `${leg.weight >= 0 ? '+' : '-'}${magnitude} * ${label}`
      return index === 0 ? token.replace(/^\+/, '') : token
    })
    .join(' ')
}

function PlotlyFigure({
  data,
  layout,
  config,
  heightPx,
  onRelayout,
}: {
  data: any[]
  layout: any
  config: any
  heightPx: number
  onRelayout?: (eventData: Record<string, unknown>) => void
}) {
  const rootRef = useRef<HTMLDivElement>(null)
  const relayoutHandlerRef = useRef(onRelayout)

  useEffect(() => {
    relayoutHandlerRef.current = onRelayout
  }, [onRelayout])

  useEffect(() => {
    let disposed = false
    let plotly: any = null
    const container = rootRef.current
    const handleRelayout = (eventData: Record<string, unknown>) => {
      relayoutHandlerRef.current?.(eventData)
    }

    const run = async () => {
      const plotlyModule = await import('plotly.js-dist-min')
      plotly = (plotlyModule as any).default ?? plotlyModule
      if (disposed || !container) return
      await plotly.react(container, data, layout, config)
      if (typeof container.on === 'function') {
        if (typeof container.removeListener === 'function') {
          container.removeListener('plotly_relayout', handleRelayout)
        }
        container.on('plotly_relayout', handleRelayout)
      }
    }

    run().catch((error) => {
      console.error('ustf-vol timeseries render error', error)
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
  }, [config, data, layout])

  return <div ref={rootRef} className="w-full" style={{ height: `${heightPx}px` }} />
}

export function TimeseriesModule() {
  const [selectedSeries, setSelectedSeries] = useState<SeriesConfig[]>(DEFAULT_SELECTED_SERIES)
  const [range, setRange] = useState<TimeRange>('6M')
  const [windowMode, setWindowMode] = useState<WindowMode>('preset')
  const [customStartDate, setCustomStartDate] = useState(() => shiftIsoDate(todayIsoDate(), -180))
  const [customEndDate, setCustomEndDate] = useState(() => todayIsoDate())
  const [displayTransform, setDisplayTransform] = useState<DisplayTransform>('absolute')
  const [showChartLegend, setShowChartLegend] = useState(true)
  const [seriesRightAxisIds, setSeriesRightAxisIds] = useState<string[]>([])
  const [seriesHiddenIds, setSeriesHiddenIds] = useState<string[]>([])
  const [formulaConfigs, setFormulaConfigs] = useState<TimeseriesFormulaConfig[]>([])
  const [formulaDraftName, setFormulaDraftName] = useState('')
  const [formulaDraftAxis, setFormulaDraftAxis] = useState<TimeseriesAxis>('y2')
  const [formulaDraftScaleBy100, setFormulaDraftScaleBy100] = useState(false)
  const [formulaDraftLegs, setFormulaDraftLegs] = useState<FormulaDraftLeg[]>(() =>
    createFormulaDraftFromSeries(DEFAULT_SELECTED_SERIES)
  )
  const [formulaError, setFormulaError] = useState<string | null>(null)
  const [showFormulaBuilder, setShowFormulaBuilder] = useState(false)
  const [showInstrumentList, setShowInstrumentList] = useState(true)
  const [technicalStudyConfigs, setTechnicalStudyConfigs] = useState<
    TimeseriesTechnicalStudyConfig[]
  >([])
  const [technicalStudyDrafts, setTechnicalStudyDrafts] = useState<
    Record<string, TechnicalStudyDraft>
  >({})

  const selectedSeriesIds = useMemo(
    () => selectedSeries.map((config) => getSeriesConfigKey(config)),
    [selectedSeries]
  )
  const hasInvalidCustomWindow =
    windowMode === 'custom' &&
    customStartDate.trim() &&
    customEndDate.trim() &&
    customStartDate > customEndDate

  const {
    data,
    loading,
    loadingHistorical,
    hasMoreHistorical,
    error,
    reload,
    loadHistorical,
  } = useUstfTimeseriesMulti({
    series: hasInvalidCustomWindow ? [] : selectedSeries,
    range,
    startDate: windowMode === 'custom' ? customStartDate : undefined,
    endDate: windowMode === 'custom' ? customEndDate : undefined,
  })

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

  useEffect(() => {
    const selectedSet = new Set(selectedSeriesIds)
    const firstSeriesId = selectedSeriesIds[0] ?? ''

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
    setTechnicalStudyConfigs((current) =>
      current.filter((config) => selectedSet.has(config.sourceSeriesId))
    )
    setFormulaDraftLegs((current) => {
      if (!current.length) return createFormulaDraftFromSeries(selectedSeries)
      return current.map((leg, index) => {
        if (!leg.seriesId || selectedSet.has(leg.seriesId)) return leg
        return { ...leg, seriesId: selectedSeriesIds[index] ?? firstSeriesId }
      })
    })
    setTechnicalStudyDrafts((current) =>
      Object.fromEntries(
        Object.entries(current).filter(([seriesId]) => selectedSet.has(seriesId))
      )
    )
  }, [selectedSeries, selectedSeriesIds])

  const seriesLabelsById = useMemo(
    () =>
      new Map(
        selectedSeries.map((config) => [
          getSeriesConfigKey(config),
          formatSeriesConfigLabel(config),
        ])
      ),
    [selectedSeries]
  )

  const seriesCatalog = useMemo(
    () =>
      selectedSeries.map((config) => ({
        id: getSeriesConfigKey(config),
        label: formatSeriesConfigLabel(config),
      })),
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

  const technicalStudyConfigsBySourceId = useMemo(() => {
    const grouped = new Map<string, TimeseriesTechnicalStudyConfig[]>()
    for (const config of technicalStudyConfigs) {
      const current = grouped.get(config.sourceSeriesId) ?? []
      current.push(config)
      grouped.set(config.sourceSeriesId, current)
    }
    return grouped
  }, [technicalStudyConfigs])

  const instrumentHeadlineStatsById = useMemo(
    () =>
      new Map(
        (data?.series ?? []).map((series) => [
          series.id,
          computeTimeseriesHeadlineStats(series.points),
        ])
      ),
    [data?.series]
  )

  const technicalStudySeries = useMemo(
    () =>
      technicalStudyConfigs
        .map((config) => {
          const sourceSeries = seriesMap.get(config.sourceSeriesId)
          if (!sourceSeries) return null
          return buildTechnicalStudySeries(config, sourceSeries)
        })
        .filter((series): series is NonNullable<typeof series> => Boolean(series)),
    [seriesMap, technicalStudyConfigs]
  )

  const formulaWarnings = useMemo(() => {
    const builtById = new Map(formulaSeries.map((series) => [series.id, series]))
    const warnings: string[] = []
    for (const config of formulaConfigs) {
      const built = builtById.get(config.id)
      if (!built) {
        warnings.push(
          `Formula '${config.name}' was skipped because one or more source series is unavailable.`
        )
      } else if (built.nonNullCount === 0) {
        warnings.push(
          `Formula '${config.name}' has no overlapping dates across its selected legs.`
        )
      }
    }
    return warnings
  }, [formulaConfigs, formulaSeries])

  const allWarnings = useMemo(
    () =>
      [
        ...(hasInvalidCustomWindow
          ? ['Custom date window is invalid. Start date must be on or before end date.']
          : []),
        ...(data?.warnings ?? []),
        ...formulaWarnings,
      ],
    [data?.warnings, formulaWarnings, hasInvalidCustomWindow]
  )

  const addSeriesConfig = (nextSeries: SeriesConfig) => {
    setSelectedSeries((current) => {
      const nextKey = getSeriesConfigKey(nextSeries)
      if (current.some((config) => getSeriesConfigKey(config) === nextKey)) return current
      return [...current, nextSeries]
    })
  }

  const addSeriesBatch = (seriesToAdd: SeriesConfig[]) => {
    setSelectedSeries((current) => {
      const merged = new Map(current.map((config) => [getSeriesConfigKey(config), config]))
      for (const config of seriesToAdd) {
        merged.set(getSeriesConfigKey(config), config)
      }
      return Array.from(merged.values())
    })
  }

  const removeSeries = (seriesId: string) => {
    setSelectedSeries((current) =>
      current.filter((config) => getSeriesConfigKey(config) !== seriesId)
    )
  }

  const toggleSeriesAxis = (seriesId: string) => {
    setSeriesRightAxisIds((current) =>
      current.includes(seriesId)
        ? current.filter((id) => id !== seriesId)
        : [...current, seriesId]
    )
  }

  const toggleSeriesVisibility = (seriesId: string) => {
    setSeriesHiddenIds((current) =>
      current.includes(seriesId)
        ? current.filter((id) => id !== seriesId)
        : [...current, seriesId]
    )
  }

  const clearMonitor = () => {
    setSelectedSeries([])
    setSeriesRightAxisIds([])
    setSeriesHiddenIds([])
    setFormulaConfigs([])
    setTechnicalStudyConfigs([])
    setTechnicalStudyDrafts({})
    setFormulaDraftLegs([])
    setFormulaDraftName('')
    setFormulaError(null)
  }

  const addFormulaFromCommand = ({
    name,
    series,
    legs,
  }: {
    name: string
    series: SeriesConfig[]
    legs: Array<{ seriesId: string; weight: number }>
  }) => {
    const normalizedLegs = normalizeFormulaLegs(legs)
    if (normalizedLegs.length < 2) {
      return
    }

    addSeriesBatch(series)
    setFormulaConfigs((current) => [
      ...current,
      {
        id: makeClientId('formula'),
        name: makeUniqueFormulaName(name, current),
        yaxis: 'y2',
        scaleBy100: false,
        legs: normalizedLegs,
      },
    ])
    setFormulaError(null)
  }

  const updateFormulaDraftLeg = (
    legId: string,
    update: Partial<Pick<FormulaDraftLeg, 'seriesId' | 'weight'>>
  ) => {
    setFormulaDraftLegs((current) =>
      current.map((leg) => (leg.id === legId ? { ...leg, ...update } : leg))
    )
  }

  const addFormulaDraftLeg = () => {
    setFormulaDraftLegs((current) => [
      ...current,
      { id: makeClientId('formula-leg'), seriesId: selectedSeriesIds[0] ?? '', weight: 0 },
    ])
  }

  const removeFormulaDraftLeg = (legId: string) => {
    setFormulaDraftLegs((current) => {
      if (current.length <= 2) return current
      return current.filter((leg) => leg.id !== legId)
    })
  }

  const resetFormulaDraft = () => {
    setFormulaDraftName('')
    setFormulaDraftAxis('y2')
    setFormulaDraftScaleBy100(false)
    setFormulaDraftLegs(createFormulaDraftFromSeries(selectedSeries))
    setFormulaError(null)
  }

  const loadSpreadTemplate = () => {
    if (selectedSeriesIds.length < 2) {
      setFormulaError('Spread template needs at least two selected series.')
      return
    }
    setFormulaDraftLegs([
      { id: makeClientId('formula-leg'), seriesId: selectedSeriesIds[0], weight: 1 },
      { id: makeClientId('formula-leg'), seriesId: selectedSeriesIds[1], weight: -1 },
    ])
    setFormulaError(null)
  }

  const loadFlyTemplate = () => {
    if (selectedSeriesIds.length < 3) {
      setFormulaError('Fly template needs at least three selected series.')
      return
    }
    setFormulaDraftLegs([
      { id: makeClientId('formula-leg'), seriesId: selectedSeriesIds[0], weight: 1 },
      { id: makeClientId('formula-leg'), seriesId: selectedSeriesIds[1], weight: -2 },
      { id: makeClientId('formula-leg'), seriesId: selectedSeriesIds[2], weight: 1 },
    ])
    setFormulaError(null)
  }

  const addFormulaSeries = () => {
    const normalizedLegs = normalizeFormulaLegs(
      formulaDraftLegs.map((leg) => ({ seriesId: leg.seriesId, weight: leg.weight }))
    ).filter((leg) => selectedSeriesIds.includes(leg.seriesId))

    if (normalizedLegs.length < 2) {
      setFormulaError('At least two valid formula legs are required.')
      return
    }
    if (normalizedLegs.every((leg) => Math.abs(leg.weight) < 1e-12)) {
      setFormulaError('Formula cannot have all-zero weights.')
      return
    }

    setFormulaConfigs((current) => [
      ...current,
      {
        id: makeClientId('formula'),
        name: makeUniqueFormulaName(
          formulaDraftName || `Formula ${current.length + 1}`,
          current
        ),
        yaxis: formulaDraftAxis,
        scaleBy100: formulaDraftScaleBy100,
        legs: normalizedLegs,
      },
    ])
    setFormulaError(null)
  }

  const removeFormulaSeries = (formulaId: string) => {
    setFormulaConfigs((current) => current.filter((config) => config.id !== formulaId))
  }

  const updateTechnicalStudyDraft = (
    seriesId: string,
    update: Partial<TechnicalStudyDraft>
  ) => {
    setTechnicalStudyDrafts((current) => ({
      ...current,
      [seriesId]: {
        ...(current[seriesId] ?? DEFAULT_TECHNICAL_STUDY_DRAFT),
        ...update,
      },
    }))
  }

  const addTechnicalStudy = (seriesId: string) => {
    const draft = technicalStudyDrafts[seriesId] ?? DEFAULT_TECHNICAL_STUDY_DRAFT
    const normalizedWindow = Math.max(2, Math.round(draft.window))

    setTechnicalStudyConfigs((current) => {
      if (
        current.some(
          (config) =>
            config.sourceSeriesId === seriesId &&
            config.kind === draft.kind &&
            config.window === normalizedWindow
        )
      ) {
        return current
      }

      return [
        ...current,
        {
          id: makeClientId('study'),
          sourceSeriesId: seriesId,
          kind: draft.kind,
          window: normalizedWindow,
        },
      ]
    })
  }

  const removeTechnicalStudy = (studyId: string) => {
    setTechnicalStudyConfigs((current) => current.filter((config) => config.id !== studyId))
  }

  const formulaDraftExpression = useMemo(
    () =>
      renderFormulaExpression(
        normalizeFormulaLegs(
          formulaDraftLegs.map((leg) => ({ seriesId: leg.seriesId, weight: leg.weight }))
        ),
        seriesLabelsById
      ),
    [formulaDraftLegs, seriesLabelsById]
  )

  const timeseriesTraces = useMemo(() => {
    if (!data) return []

    const hiddenIds = new Set(seriesHiddenIds)
    const out: any[] = []

    data.series.forEach((series, index) => {
      if (hiddenIds.has(series.id)) return
      const color = SERIES_COLORS[index % SERIES_COLORS.length]
      const yaxis: TimeseriesAxis = seriesRightAxisIds.includes(series.id) ? 'y2' : 'y'
      const x = series.points.map((point) => point.asOf)
      const transformedValues = transformValues(
        series.points.map((point) => point.value),
        displayTransform
      )

      out.push({
        type: 'scatter',
        mode: 'lines+markers',
        name: series.label,
        x,
        y: transformedValues,
        yaxis,
        line: { color, width: 2.35 },
        marker: { color, size: 4 },
        hovertemplate:
          `${series.label}<br>` +
          `Axis ${axisShortLabel(yaxis)}<br>` +
          `${displayTransform === 'rebased' ? 'Index' : 'NVOL'} %{y:.2f}<br>` +
          'Date %{x}<extra></extra>',
      })
    })

    formulaSeries.forEach((formula, index) => {
      const color = FORMULA_COLORS[index % FORMULA_COLORS.length]
      const x = formula.points.map((point) => point.asOf)
      const transformedValues = transformValues(
        formula.points.map((point) => point.value),
        displayTransform
      )

      out.push({
        type: 'scatter',
        mode: 'lines+markers',
        name: `Formula: ${formula.name}`,
        x,
        y: transformedValues,
        yaxis: formula.yaxis,
        line: { color, width: 2.4 },
        marker: { color, size: 3 },
        hovertemplate:
          `${formula.name}<br>` +
          `${formula.scaleBy100 ? 'Scaled x100<br>' : ''}` +
          `Axis ${axisShortLabel(formula.yaxis)}<br>` +
          `${displayTransform === 'rebased' ? 'Index' : 'Value'} %{y:.2f}<br>` +
          'Date %{x}<extra></extra>',
      })
    })

    technicalStudySeries.forEach((study) => {
      if (hiddenIds.has(study.sourceSeriesId)) return

      const sourceSeries = seriesMap.get(study.sourceSeriesId)
      if (!sourceSeries) return

      const sourceAxis: TimeseriesAxis = seriesRightAxisIds.includes(study.sourceSeriesId)
        ? 'y2'
        : 'y'
      const yaxis: TimeseriesAxis =
        study.axisMode === 'overlay'
          ? sourceAxis
          : sourceAxis === 'y'
            ? 'y2'
            : 'y'
      const x = study.points.map((point) => point.asOf)
      const sourceBase = firstFiniteValue(sourceSeries.points.map((point) => point.value))
      const y = shouldTransformTechnicalStudy(study.kind)
        ? transformValues(
            study.points.map((point) => point.value),
            displayTransform,
            sourceBase
          )
        : study.points.map((point) => point.value)
      const color = seriesColorsById.get(study.sourceSeriesId) ?? '#94a3b8'
      const style = technicalStudyLineStyle(study.kind)

      out.push({
        type: 'scatter',
        mode: 'lines',
        name: `${sourceSeries.label} ${study.shortLabel}`,
        x,
        y,
        yaxis,
        opacity: study.axisMode === 'overlay' ? 0.95 : 0.88,
        line: { color, width: style.width, dash: style.dash },
        hovertemplate:
          `${sourceSeries.label}<br>` +
          `${study.label}<br>` +
          `Axis ${axisShortLabel(yaxis)}<br>` +
          `${technicalStudyValueLabel(study.kind, displayTransform)} %{y:.2f}<br>` +
          'Date %{x}<extra></extra>',
      })
    })

    return out
  }, [
    data,
    displayTransform,
    formulaSeries,
    seriesColorsById,
    seriesHiddenIds,
    seriesMap,
    seriesRightAxisIds,
    technicalStudySeries,
  ])

  const hasSecondaryAxis = useMemo(
    () => timeseriesTraces.some((trace) => trace?.yaxis === 'y2'),
    [timeseriesTraces]
  )

  const hasVisibleTechnicalStudies = useMemo(
    () => technicalStudySeries.some((study) => !seriesHiddenIds.includes(study.sourceSeriesId)),
    [seriesHiddenIds, technicalStudySeries]
  )

  const axisTitle = hasVisibleTechnicalStudies
    ? displayTransform === 'rebased'
      ? 'Index / study value'
      : 'NVOL (bpvol) / study value'
    : displayTransform === 'rebased'
      ? 'Index (100 = first point)'
      : 'NVOL (bpvol)'

  const timeseriesLayout = useMemo(
    () => ({
      template: 'plotly_dark',
      paper_bgcolor: 'rgba(2, 6, 23, 0)',
      plot_bgcolor: 'rgba(2, 6, 23, 0.72)',
      autosize: true,
      height: PLOTLY_FIGURE_HEIGHT_PX,
      margin: { t: 28, r: 24, b: 54, l: 72 },
      showlegend: showChartLegend,
      hovermode: 'x unified',
      dragmode: 'zoom',
      legend: {
        orientation: 'h',
        x: 0,
        y: 1.15,
        bgcolor: 'rgba(15, 23, 42, 0.7)',
        bordercolor: 'rgba(148, 163, 184, 0.14)',
        borderwidth: 1,
      },
      hoverlabel: {
        bgcolor: 'rgba(15, 23, 42, 0.96)',
        bordercolor: 'rgba(148, 163, 184, 0.22)',
        font: { color: '#e2e8f0', size: 11 },
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
        linecolor: 'rgba(148, 163, 184, 0.3)',
        tickfont: { color: '#94a3b8', size: 10 },
        gridcolor: 'rgba(71, 85, 105, 0.18)',
      },
      yaxis: {
        title: hasSecondaryAxis ? `${axisTitle} (LHS)` : axisTitle,
        showspikes: true,
        spikesnap: 'cursor',
        spikecolor: '#f8fafc',
        spikethickness: 0.55,
        showline: true,
        linecolor: 'rgba(148, 163, 184, 0.3)',
        tickfont: { color: '#94a3b8', size: 10 },
        titlefont: { color: '#94a3b8', size: 11 },
        gridcolor: 'rgba(71, 85, 105, 0.18)',
      },
      ...(hasSecondaryAxis
        ? {
            yaxis2: {
              title: `${axisTitle} (RHS)`,
              overlaying: 'y',
              side: 'right',
              showgrid: false,
              zeroline: false,
              showspikes: true,
              spikesnap: 'cursor',
              spikecolor: '#f8fafc',
              spikethickness: 0.55,
            },
          }
        : {}),
      uirevision: `ustf-vol-timeseries-${displayTransform}-${hasSecondaryAxis ? 'dual' : 'single'}-${showChartLegend ? 'legend-on' : 'legend-off'}`,
    }),
    [axisTitle, displayTransform, hasSecondaryAxis, showChartLegend]
  )

  const timeseriesConfig = useMemo(
    () => ({
      responsive: true,
      displaylogo: false,
      editable: true,
      modeBarButtonsToAdd: [
        'drawline',
        'drawopenpath',
        'drawclosedpath',
        'drawcircle',
        'drawrect',
        'eraseshape',
      ],
    }),
    []
  )

  const instrumentListShouldScroll = selectedSeries.length > 4

  return (
    <div className="space-y-4">
      <div
        className="rounded-lg border border-slate-800/80 bg-slate-950/45 p-2"
        style={{ zoom: 0.9 }}
      >
        <div className="flex flex-wrap items-center justify-between gap-1.5">
          <div className={LABEL_CLASS}>Monitor lines</div>
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => reload()}
              className="rounded-md border border-slate-700/80 bg-slate-950/80 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-slate-300 transition hover:border-slate-500 hover:text-white"
            >
              Refresh
            </button>
            <button
              type="button"
              onClick={clearMonitor}
              className="rounded-md border border-slate-700/80 bg-slate-950/80 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-slate-400 transition hover:border-slate-500 hover:text-white"
            >
              Clear all
            </button>
          </div>
        </div>

        <div className="mt-2 rounded-lg border border-slate-800/80 bg-slate-950/55 p-2">
          <div className="flex flex-wrap items-end gap-3">
            <TimeseriesCommandBar
              selectedSeriesIds={selectedSeriesIds}
              onAddSeries={addSeriesConfig}
              onAddFormula={addFormulaFromCommand}
            />

            <div className="space-y-1">
              <span className={LABEL_CLASS}>Window</span>
              <div className="flex overflow-hidden rounded-md border border-slate-700/80">
                {(['preset', 'custom'] as WindowMode[]).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setWindowMode(mode)}
                    className={segmentButtonClass(windowMode === mode)}
                  >
                    {mode}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-1">
              <span className={LABEL_CLASS}>
                {windowMode === 'preset' ? 'Lookback' : 'Date window'}
              </span>
              {windowMode === 'preset' ? (
                <div className="flex flex-wrap overflow-hidden rounded-md border border-slate-700/80">
                  {RANGE_OPTIONS.map((rangeValue) => (
                    <button
                      key={rangeValue}
                      type="button"
                      onClick={() => setRange(rangeValue)}
                      className={segmentButtonClass(range === rangeValue)}
                    >
                      {rangeValue}
                    </button>
                  ))}
                </div>
              ) : (
                <div className="flex flex-wrap items-center gap-1.5">
                  <input
                    type="date"
                    value={customStartDate}
                    onChange={(event) => setCustomStartDate(event.target.value)}
                    className={INPUT_CLASS}
                  />
                  <input
                    type="date"
                    value={customEndDate}
                    onChange={(event) => setCustomEndDate(event.target.value)}
                    className={INPUT_CLASS}
                  />
                </div>
              )}
            </div>

            <div className="space-y-1">
              <span className={LABEL_CLASS}>Transform</span>
              <div className="flex overflow-hidden rounded-md border border-slate-700/80">
                {(['absolute', 'rebased'] as DisplayTransform[]).map((transform) => (
                  <button
                    key={transform}
                    type="button"
                    onClick={() => setDisplayTransform(transform)}
                    className={segmentButtonClass(displayTransform === transform)}
                  >
                    {transform === 'absolute' ? 'Absolute' : 'Rebased 100'}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-1">
              <span className={LABEL_CLASS}>Legend</span>
              <button
                type="button"
                onClick={() => setShowChartLegend((current) => !current)}
                className={`rounded-md border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] transition ${
                  showChartLegend
                    ? 'border-slate-500/80 bg-slate-200/10 text-slate-100'
                    : 'border-slate-700/80 bg-slate-950/80 text-slate-300 hover:border-slate-500 hover:text-white'
                }`}
              >
                {showChartLegend ? 'On' : 'Off'}
              </button>
            </div>
          </div>
        </div>

        <div className="mt-2 overflow-hidden rounded-lg border border-slate-800/80 bg-slate-950/35">
          <div className="flex flex-wrap items-center justify-between gap-1 border-b border-slate-800/80 bg-slate-950/80 px-2 py-1">
            <div>
              <div className={LABEL_CLASS}>Instrument list</div>
            </div>
            <button
              type="button"
              onClick={() => setShowInstrumentList((current) => !current)}
              className="inline-flex items-center gap-1 rounded-md border border-slate-700/80 bg-slate-950/80 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-slate-300 transition hover:border-slate-500 hover:text-white"
            >
              {showInstrumentList ? 'Collapse' : 'Expand'}
              {showInstrumentList ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            </button>
          </div>

          {showInstrumentList ? (
            <div
              className={`overflow-x-auto ${instrumentListShouldScroll ? 'max-h-[220px] overflow-y-auto' : ''}`}
            >
              <table className="min-w-[1500px] border-collapse text-left text-[12px] text-slate-300">
                <thead className="bg-slate-950/90">
                  <tr className="border-b border-slate-800/80">
                    {[
                      'Color',
                      'Instrument',
                      'Axis',
                      'Visible',
                      'Headline stats',
                      'Technical analysis',
                      'Actions',
                    ].map((column) => (
                      <th
                        key={column}
                        className="sticky top-0 bg-slate-950/95 px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-500"
                      >
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="bg-slate-950/35">
                  {selectedSeries.length ? (
                    selectedSeries.map((config) => {
                      const seriesId = getSeriesConfigKey(config)
                      const isHidden = seriesHiddenIds.includes(seriesId)
                      const isRhs = seriesRightAxisIds.includes(seriesId)
                      const seriesColor = seriesColorsById.get(seriesId) ?? '#94a3b8'
                      const headlineStats = instrumentHeadlineStatsById.get(seriesId)
                      const technicalStudyDraft =
                        technicalStudyDrafts[seriesId] ?? DEFAULT_TECHNICAL_STUDY_DRAFT
                      const activeStudyConfigs = technicalStudyConfigsBySourceId.get(seriesId) ?? []
                      const statCards = [
                        {
                          label: 'Px',
                          value: formatVol(headlineStats?.latest ?? null, 1),
                          tone: 'text-slate-100',
                        },
                        {
                          label: 'Min',
                          value: formatVol(headlineStats?.min ?? null, 1),
                          tone: 'text-slate-100',
                        },
                        {
                          label: 'Max',
                          value: formatVol(headlineStats?.max ?? null, 1),
                          tone: 'text-slate-100',
                        },
                        {
                          label: '1D',
                          value: formatSignedNumber(headlineStats?.change1d ?? null, 1),
                          tone: statValueTone(headlineStats?.change1d ?? null),
                        },
                        {
                          label: '1W',
                          value: formatSignedNumber(headlineStats?.change5d ?? null, 1),
                          tone: statValueTone(headlineStats?.change5d ?? null),
                        },
                        {
                          label: 'vs20D',
                          value: formatSignedNumber(headlineStats?.vsSma20 ?? null, 1),
                          tone: statValueTone(headlineStats?.vsSma20 ?? null),
                        },
                        {
                          label: '20D Z',
                          value: formatSignedNumber(headlineStats?.zScore20 ?? null, 2),
                          tone: statValueTone(headlineStats?.zScore20 ?? null),
                        },
                        {
                          label: 'Win %ile',
                          value: formatStatPercent(headlineStats?.rangePercentile ?? null, 0),
                          tone: 'text-slate-100',
                        },
                        {
                          label: 'VoV20',
                          value: formatVol(headlineStats?.realizedVol20 ?? null, 1),
                          tone: 'text-slate-100',
                        },
                      ]

                      return (
                        <tr
                          key={seriesId}
                          className="border-b border-slate-800/80 transition hover:bg-slate-900/45 last:border-b-0"
                        >
                          <td className="px-2 py-1">
                            <div className="flex items-center">
                              <span
                                className={`inline-flex h-3 w-8 rounded-full border border-white/10 shadow-[0_0_0_1px_rgba(15,23,42,0.5)] ${
                                  isHidden ? 'opacity-45' : ''
                                }`}
                                style={{ backgroundColor: seriesColor }}
                                aria-label={`${formatSeriesConfigLabel(config)} color`}
                                title={seriesColor}
                              />
                            </div>
                          </td>
                          <td className="px-2 py-1 text-[13px] font-medium text-slate-100">
                            {formatSeriesConfigLabel(config)}
                          </td>
                          <td className="px-2 py-1">
                            <button
                              type="button"
                              onClick={() => toggleSeriesAxis(seriesId)}
                              className={`rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] transition ${
                                isRhs
                                  ? 'border-cyan-500/60 bg-cyan-500/12 text-cyan-100'
                                  : 'border-slate-700/80 bg-slate-950/80 text-slate-300 hover:border-slate-500 hover:text-white'
                              }`}
                            >
                              {isRhs ? 'RHS' : 'LHS'}
                            </button>
                          </td>
                          <td className="px-2 py-1">
                            <button
                              type="button"
                              onClick={() => toggleSeriesVisibility(seriesId)}
                              className={`rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] transition ${
                                !isHidden
                                  ? 'border-slate-500/80 bg-slate-200/10 text-slate-100'
                                  : 'border-slate-700/80 bg-slate-950/80 text-slate-300 hover:border-slate-500 hover:text-white'
                              }`}
                            >
                              {!isHidden ? 'On' : 'Off'}
                            </button>
                          </td>
                          <td className="min-w-[720px] px-2 py-1">
                            <div className="grid grid-cols-9 gap-1">
                              {statCards.map((card) => (
                                <div
                                  key={card.label}
                                  className="rounded-md border border-slate-800/80 bg-slate-950/70 px-1.5 py-0.5"
                                >
                                  <div className="text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                                    {card.label}
                                  </div>
                                  <div className={`mt-0.5 font-mono text-[13px] ${card.tone}`}>
                                    {card.value}
                                  </div>
                                </div>
                              ))}
                            </div>
                            <div className="mt-0.5 text-[11px] text-slate-500">
                              {headlineStats?.latestDate
                                ? `As of ${headlineStats.latestDate}`
                                : 'Waiting for timeseries history'}
                            </div>
                          </td>
                          <td className="min-w-[296px] px-2 py-1">
                            <div className="flex flex-wrap items-center gap-0.5">
                              <select
                                value={technicalStudyDraft.kind}
                                onChange={(event) =>
                                  updateTechnicalStudyDraft(seriesId, {
                                    kind: event.target.value as TimeseriesTechnicalStudyKind,
                                  })
                                }
                                className="h-6 min-w-[144px] rounded-md border border-slate-700/80 bg-slate-950/80 px-2 text-[12px] text-slate-100 outline-none transition focus:border-slate-500"
                              >
                                {TECHNICAL_STUDY_OPTIONS.map((option) => (
                                  <option key={option.value} value={option.value}>
                                    {option.label}
                                  </option>
                                ))}
                              </select>
                              <select
                                value={technicalStudyDraft.window}
                                onChange={(event) =>
                                  updateTechnicalStudyDraft(seriesId, {
                                    window: Number(event.target.value),
                                  })
                                }
                                className="h-6 w-[72px] rounded-md border border-slate-700/80 bg-slate-950/80 px-2 text-[12px] text-slate-100 outline-none transition focus:border-slate-500"
                              >
                                {TECHNICAL_STUDY_WINDOW_OPTIONS.map((windowValue) => (
                                  <option key={windowValue} value={windowValue}>
                                    {windowValue}D
                                  </option>
                                ))}
                              </select>
                              <button
                                type="button"
                                onClick={() => addTechnicalStudy(seriesId)}
                                className="rounded-md border border-slate-700/80 bg-slate-950/80 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-200 transition hover:border-slate-500 hover:text-white"
                              >
                                Add
                              </button>
                            </div>
                            <div className="mt-1 flex flex-wrap gap-0.5">
                              {activeStudyConfigs.length ? (
                                activeStudyConfigs.map((studyConfig) => (
                                  <span
                                    key={studyConfig.id}
                                    className="inline-flex items-center gap-0.5 rounded-md border border-slate-700/80 bg-slate-950/85 px-1.5 py-0.5 text-[11px] text-slate-200"
                                  >
                                    {formatTechnicalStudyShortLabel(
                                      studyConfig.kind,
                                      studyConfig.window
                                    )}
                                    <button
                                      type="button"
                                      onClick={() => removeTechnicalStudy(studyConfig.id)}
                                      className="text-slate-500 transition hover:text-white"
                                      aria-label={`Remove ${formatTechnicalStudyShortLabel(
                                        studyConfig.kind,
                                        studyConfig.window
                                      )}`}
                                    >
                                      ×
                                    </button>
                                  </span>
                                ))
                              ) : (
                                <span className="text-[11px] text-slate-500">
                                  No active studies. Add overlays or oscillators for this line.
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="px-2 py-1">
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
                      <td colSpan={7} className="px-3 py-4 text-center text-[11px] text-slate-500">
                        No base series selected. Add lines above to populate the monitor.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          ) : null}

          <div className="border-t border-slate-800/80 bg-slate-950/20">
            <div className="flex flex-wrap items-center justify-between gap-1.5 px-2.5 py-1.5">
              <div>
                <div className={LABEL_CLASS}>Formula builder</div>
                <div className="mt-0.5 text-[10px] text-slate-500">
                  Build spreads and flies from selected monitor lines.
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowFormulaBuilder((current) => !current)}
                className="rounded-md border border-slate-700/80 bg-slate-950/80 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-slate-300 transition hover:border-slate-500 hover:text-white"
              >
                {showFormulaBuilder ? 'Collapse' : 'Expand'}
              </button>
            </div>

            {showFormulaBuilder ? (
              <div className="border-t border-slate-800/80 px-2.5 py-2">
                <div className="flex flex-wrap gap-1.5">
                  <button
                    type="button"
                    onClick={loadSpreadTemplate}
                    className="rounded-md border border-slate-700/80 px-2 py-1 text-[10px] text-slate-300 transition hover:border-slate-500 hover:text-white"
                  >
                    Load spread
                  </button>
                  <button
                    type="button"
                    onClick={loadFlyTemplate}
                    className="rounded-md border border-slate-700/80 px-2 py-1 text-[10px] text-slate-300 transition hover:border-slate-500 hover:text-white"
                  >
                    Load fly
                  </button>
                </div>

                <div className="mt-2.5 grid gap-2.5 xl:grid-cols-[minmax(0,1.2fr)_150px_108px_auto]">
                  <label className="text-[10px] text-slate-400">
                    Formula Name
                    <input
                      type="text"
                      value={formulaDraftName}
                      onChange={(event) => setFormulaDraftName(event.target.value)}
                      placeholder={`Formula ${formulaConfigs.length + 1}`}
                      className="mt-1 w-full rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 py-1.5 text-[11px] text-slate-200"
                    />
                  </label>
                  <label className="text-[10px] text-slate-400">
                    Output Axis
                    <select
                      value={formulaDraftAxis}
                      onChange={(event) => setFormulaDraftAxis(event.target.value as TimeseriesAxis)}
                      className="mt-1 w-full rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 py-1.5 text-[11px] text-slate-200"
                    >
                      <option value="y">Left Axis</option>
                      <option value="y2">Right Axis</option>
                    </select>
                  </label>
                  <label className="inline-flex items-center gap-1.5 self-end pb-1.5 text-[10px] text-slate-300">
                    <input
                      type="checkbox"
                      checked={formulaDraftScaleBy100}
                      onChange={(event) => setFormulaDraftScaleBy100(event.target.checked)}
                    />
                    x100
                  </label>
                  <div className="flex flex-wrap items-end gap-1.5">
                    <button
                      type="button"
                      onClick={addFormulaSeries}
                      className="rounded-md border border-amber-500/60 bg-amber-500/12 px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-amber-100 transition hover:border-amber-400"
                    >
                      Add formula
                    </button>
                    <button
                      type="button"
                      onClick={resetFormulaDraft}
                      className="rounded-md border border-slate-700/80 px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-300 transition hover:border-slate-500 hover:text-white"
                    >
                      Reset
                    </button>
                  </div>
                </div>

                <div className="mt-2.5 space-y-2">
                  {formulaDraftLegs.map((leg, index) => (
                    <div
                      key={leg.id}
                      className="grid gap-2 md:grid-cols-[minmax(0,1fr)_112px_84px]"
                    >
                      <label className="text-[10px] text-slate-400">
                        Leg {index + 1}
                        <select
                          value={leg.seriesId}
                          onChange={(event) =>
                            updateFormulaDraftLeg(leg.id, { seriesId: event.target.value })
                          }
                          className="mt-1 w-full rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 py-1.5 text-[11px] text-slate-200"
                        >
                          <option value="">Select series</option>
                          {seriesCatalog.map((series) => (
                            <option key={series.id} value={series.id}>
                              {series.label}
                            </option>
                          ))}
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
                          onClick={() => removeFormulaDraftLeg(leg.id)}
                          disabled={formulaDraftLegs.length <= 2}
                          className="w-full rounded-md border border-slate-700/80 px-2 py-1.5 text-[10px] text-slate-300 disabled:opacity-40"
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    onClick={addFormulaDraftLeg}
                    className="rounded-md border border-slate-700/80 px-2 py-1 text-[10px] text-slate-300 transition hover:border-slate-500 hover:text-white"
                  >
                    Add leg
                  </button>
                  <div className="text-[10px] text-slate-500">
                    Draft: {formulaDraftExpression}
                    {formulaDraftScaleBy100 ? ' | scaled x100' : ''}
                  </div>
                </div>

                {formulaError ? (
                  <div className="mt-2.5 rounded-md border border-rose-900/50 bg-rose-950/35 px-2.5 py-2 text-[11px] text-rose-200">
                    {formulaError}
                  </div>
                ) : null}

                {formulaConfigs.length ? (
                  <div className="mt-2.5 space-y-2">
                    {formulaConfigs.map((formula) => (
                      <div
                        key={formula.id}
                        className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 py-2"
                      >
                        <div className="min-w-0">
                          <div className="text-[11px] font-medium text-slate-100">
                            {formula.name}
                          </div>
                          <div className="text-[10px] text-slate-500">
                            {renderFormulaExpression(normalizeFormulaLegs(formula.legs), seriesLabelsById)}{' '}
                            | {axisShortLabel(formula.yaxis)}
                            {formula.scaleBy100 ? ' | x100' : ''}
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => removeFormulaSeries(formula.id)}
                          className="rounded-md border border-slate-700/80 px-2 py-1 text-[10px] text-slate-300 transition hover:border-slate-500 hover:text-white"
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      </div>

      {allWarnings.length ? (
        <div className="rounded-lg border border-amber-900/50 bg-amber-950/30 px-4 py-3 text-xs text-amber-200">
          {allWarnings.map((warning) => (
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
            config={timeseriesConfig}
            heightPx={PLOTLY_FIGURE_HEIGHT_PX}
            onRelayout={handleTimeseriesRelayout}
          />
        ) : (
          <div
            className="flex items-center justify-center text-sm text-slate-500"
            style={{ height: `${PLOTLY_FIGURE_HEIGHT_PX}px` }}
          >
            Add monitor lines to populate the chart.
          </div>
        )}
      </div>
    </div>
  )
}
