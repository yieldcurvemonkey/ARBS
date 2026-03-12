'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { CircleHelp } from 'lucide-react'

import { STANDARD_PAIRS } from '../constants'
import type { SeriesConfig } from '../types'
import {
  buildTimeseriesSeriesSearchOptions,
  formatSeriesConfigLabel,
  getSeriesConfigKey,
  parseTimeseriesFormulaCommand,
  searchTimeseriesSeriesOptions,
  type TimeseriesFormulaLeg,
} from '../utils'

type FormulaInput = {
  name: string
  legs: TimeseriesFormulaLeg[]
  series: SeriesConfig[]
}

type Props = {
  selectedSeriesIds: string[]
  onAddSeries: (config: SeriesConfig) => void
  onAddFormula: (input: FormulaInput) => void
}

type CommandAction = {
  id: string
  section: 'Structures' | 'Series'
  badge: string
  title: string
  description: string
  onSelect: () => void
}

type SpreadPreset = {
  series1: SeriesConfig
  series2: SeriesConfig
  description: string
}

const LISTED_FLY_PRESETS: Array<[SeriesConfig, SeriesConfig, SeriesConfig]> = [
  [
    { type: 'ustf', product: 'TU', expiry: '1M' },
    { type: 'ustf', product: 'FV', expiry: '1M' },
    { type: 'ustf', product: 'TY', expiry: '1M' },
  ],
  [
    { type: 'ustf', product: 'FV', expiry: '1M' },
    { type: 'ustf', product: 'TY', expiry: '1M' },
    { type: 'ustf', product: 'TN', expiry: '1M' },
  ],
  [
    { type: 'ustf', product: 'TY', expiry: '1M' },
    { type: 'ustf', product: 'TN', expiry: '1M' },
    { type: 'ustf', product: 'US', expiry: '1M' },
  ],
  [
    { type: 'ustf', product: 'TN', expiry: '1M' },
    { type: 'ustf', product: 'US', expiry: '1M' },
    { type: 'ustf', product: 'UL', expiry: '1M' },
  ],
]
const DEFAULT_OTM_SPREAD_PRESETS: SpreadPreset[] = [
  {
    series1: { type: 'ustf', product: 'TY', expiry: '1M', volMetric: { kind: 'delta_otm', side: 'call', delta: 10 } },
    series2: { type: 'swaption', tail: '7Y', expiry: '1M', volMetric: { kind: 'delta_otm', side: 'payer', delta: 10 } },
    description: 'Add both OTM delta legs and plot a RHS listed-vs-OTC spread.',
  },
  {
    series1: { type: 'ustf', product: 'TY', expiry: '1M', volMetric: { kind: 'delta_otm', side: 'put', delta: 10 } },
    series2: { type: 'swaption', tail: '7Y', expiry: '1M', volMetric: { kind: 'delta_otm', side: 'receiver', delta: 10 } },
    description: 'Add both OTM delta legs and plot a RHS listed-vs-OTC spread.',
  },
  {
    series1: { type: 'ustf', product: 'TY', expiry: '1M', volMetric: { kind: 'strike_offset_otm', side: 'call', offsetBps: 25 } },
    series2: { type: 'swaption', tail: '7Y', expiry: '1M', volMetric: { kind: 'strike_offset_otm', side: 'payer', offsetBps: 25 } },
    description: 'Add both OTM strike-offset legs and plot a RHS listed-vs-OTC spread.',
  },
  {
    series1: { type: 'ustf', product: 'TY', expiry: '1M', volMetric: { kind: 'strike_offset_otm', side: 'put', offsetBps: 25 } },
    series2: { type: 'swaption', tail: '7Y', expiry: '1M', volMetric: { kind: 'strike_offset_otm', side: 'receiver', offsetBps: 25 } },
    description: 'Add both OTM strike-offset legs and plot a RHS listed-vs-OTC spread.',
  },
  {
    series1: { type: 'ustf', product: 'FV', expiry: '1M', volMetric: { kind: 'delta_otm', side: 'call', delta: 10 } },
    series2: { type: 'swaption', tail: '5Y', expiry: '1M', volMetric: { kind: 'delta_otm', side: 'payer', delta: 10 } },
    description: 'Add both OTM delta legs and plot a RHS listed-vs-OTC spread.',
  },
  {
    series1: { type: 'ustf', product: 'FV', expiry: '1M', volMetric: { kind: 'strike_offset_otm', side: 'put', offsetBps: 25 } },
    series2: { type: 'swaption', tail: '5Y', expiry: '1M', volMetric: { kind: 'strike_offset_otm', side: 'receiver', offsetBps: 25 } },
    description: 'Add both OTM strike-offset legs and plot a RHS listed-vs-OTC spread.',
  },
]
const DEFAULT_EMPTY_SERIES_PRESETS: SeriesConfig[] = [
  { type: 'ustf', product: 'TY', expiry: '1M' },
  { type: 'swaption', tail: '7Y', expiry: '1M' },
  { type: 'ustf', product: 'FV', expiry: '1M' },
  { type: 'swaption', tail: '5Y', expiry: '1M' },
  { type: 'ustf', product: 'US', expiry: '1M' },
  { type: 'swaption', tail: '20Y', expiry: '1M' },
  { type: 'ustf', product: 'TY', expiry: '1M', volMetric: { kind: 'delta_otm', side: 'call', delta: 10 } },
  { type: 'ustf', product: 'TY', expiry: '1M', volMetric: { kind: 'delta_otm', side: 'put', delta: 10 } },
  { type: 'ustf', product: 'TY', expiry: '1M', volMetric: { kind: 'strike_offset_otm', side: 'call', offsetBps: 25 } },
  { type: 'ustf', product: 'TY', expiry: '1M', volMetric: { kind: 'strike_offset_otm', side: 'put', offsetBps: 25 } },
  { type: 'swaption', tail: '7Y', expiry: '1M', volMetric: { kind: 'delta_otm', side: 'payer', delta: 10 } },
  { type: 'swaption', tail: '7Y', expiry: '1M', volMetric: { kind: 'delta_otm', side: 'receiver', delta: 10 } },
  { type: 'swaption', tail: '7Y', expiry: '1M', volMetric: { kind: 'strike_offset_otm', side: 'payer', offsetBps: 25 } },
  { type: 'swaption', tail: '7Y', expiry: '1M', volMetric: { kind: 'strike_offset_otm', side: 'receiver', offsetBps: 25 } },
  { type: 'ustf', product: 'FV', expiry: '1M', volMetric: { kind: 'delta_otm', side: 'call', delta: 10 } },
  { type: 'swaption', tail: '5Y', expiry: '1M', volMetric: { kind: 'delta_otm', side: 'payer', delta: 10 } },
]
const DEFAULT_EMPTY_STRUCTURE_RESULTS = 18
const DEFAULT_EMPTY_SERIES_RESULTS = 16

function normalizeCommandText(value: string): string {
  return value.toUpperCase().replace(/[^A-Z0-9]+/g, '')
}

function matchesCommandText(query: string, ...candidates: string[]): boolean {
  const normalizedQuery = normalizeCommandText(query)
  if (!normalizedQuery) return true

  return candidates.some((candidate) =>
    normalizeCommandText(candidate).includes(normalizedQuery)
  )
}

export function TimeseriesCommandBar({
  selectedSeriesIds,
  onAddSeries,
  onAddFormula,
}: Props) {
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [isOpen, setIsOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const [showHelp, setShowHelp] = useState(false)

  const seriesUniverse = useMemo(() => buildTimeseriesSeriesSearchOptions(), [])
  const seriesUniverseById = useMemo(
    () => new Map(seriesUniverse.map((option) => [option.id, option])),
    [seriesUniverse]
  )

  const commonStructureActions = useMemo<CommandAction[]>(
    () => [
      ...STANDARD_PAIRS.map((pair) => {
        const title = `Spread: ${pair.label}`
        return {
          id: `pair-${pair.label}`,
          section: 'Structures' as const,
          badge: 'SPREAD',
          title,
          description: 'Add both legs and plot a RHS comparison spread.',
          onSelect: () =>
            onAddFormula({
              name: `${pair.label} spread`,
              series: [pair.series1, pair.series2],
              legs: [
                { seriesId: getSeriesConfigKey(pair.series1), weight: 1 },
                { seriesId: getSeriesConfigKey(pair.series2), weight: -1 },
              ],
            }),
        }
      }),
      ...LISTED_FLY_PRESETS.map((series) => {
        const labels = series.map((config) => formatSeriesConfigLabel(config))
        return {
          id: `fly-${series.map((config) => getSeriesConfigKey(config)).join('-')}`,
          section: 'Structures' as const,
          badge: 'FLY',
          title: `Fly: ${labels.join(' / ')}`,
          description: 'Add the three listed legs and plot a +1 / -2 / +1 fly on RHS.',
          onSelect: () =>
            onAddFormula({
              name: `${labels.join(' / ')} fly`,
              series,
              legs: [
                { seriesId: getSeriesConfigKey(series[0]), weight: 1 },
                { seriesId: getSeriesConfigKey(series[1]), weight: -2 },
                { seriesId: getSeriesConfigKey(series[2]), weight: 1 },
              ],
            }),
        }
      }),
      ...DEFAULT_OTM_SPREAD_PRESETS.map(({ series1, series2, description }) => {
        const label1 = formatSeriesConfigLabel(series1)
        const label2 = formatSeriesConfigLabel(series2)
        return {
          id: `spread-${getSeriesConfigKey(series1)}-${getSeriesConfigKey(series2)}`,
          section: 'Structures' as const,
          badge: 'SPREAD',
          title: `Spread: ${label1} vs ${label2}`,
          description,
          onSelect: () =>
            onAddFormula({
              name: `${label1} vs ${label2} spread`,
              series: [series1, series2],
              legs: [
                { seriesId: getSeriesConfigKey(series1), weight: 1 },
                { seriesId: getSeriesConfigKey(series2), weight: -1 },
              ],
            }),
        }
      }),
    ],
    [onAddFormula]
  )

  const formulaAction = useMemo<CommandAction | null>(() => {
    const parsed = parseTimeseriesFormulaCommand(query, seriesUniverse)
    if (!parsed) {
      return null
    }

    return {
      id: `query-${parsed.formulaKind}-${parsed.name}`,
      section: 'Structures',
      badge: parsed.formulaKind.toUpperCase(),
      title: parsed.name,
      description: `Query command: ${parsed.description}`,
      onSelect: () =>
        onAddFormula({
          name: parsed.name,
          series: parsed.series,
          legs: parsed.legs,
        }),
    }
  }, [onAddFormula, query, seriesUniverse])

  const seriesActions = useMemo<CommandAction[]>(() => {
    const availableOptions = seriesUniverse.filter((option) => !selectedSeriesIds.includes(option.id))

    if (!query.trim()) {
      const seen = new Set<string>()
      const curated = DEFAULT_EMPTY_SERIES_PRESETS
        .map((config) => seriesUniverseById.get(getSeriesConfigKey(config)))
        .filter((option): option is NonNullable<typeof option> => Boolean(option))
        .filter((option) => !selectedSeriesIds.includes(option.id))
        .filter((option) => {
          if (seen.has(option.id)) return false
          seen.add(option.id)
          return true
        })

      const extras = searchTimeseriesSeriesOptions(
        '',
        availableOptions.filter((option) => !seen.has(option.id)),
        Math.max(DEFAULT_EMPTY_SERIES_RESULTS - curated.length, 0)
      )

      return [...curated, ...extras].map((option) => ({
        id: option.id,
        section: 'Series' as const,
        badge: option.bucket.toUpperCase(),
        title: option.label,
        description: option.subtitle,
        onSelect: () => onAddSeries(option.config),
      }))
    }

    return searchTimeseriesSeriesOptions(query, availableOptions, 8).map((option) => ({
      id: option.id,
      section: 'Series' as const,
      badge: option.bucket.toUpperCase(),
      title: option.label,
      description: option.subtitle,
      onSelect: () => onAddSeries(option.config),
    }))
  }, [onAddSeries, query, selectedSeriesIds, seriesUniverse, seriesUniverseById])

  const structureActions = useMemo<CommandAction[]>(() => {
    const seen = new Set<string>()
    const out: CommandAction[] = []

    if (formulaAction) {
      seen.add(formulaAction.title)
      out.push(formulaAction)
    }

    const filtered = commonStructureActions.filter((action) =>
      matchesCommandText(query, action.title, action.description)
    )

    for (const action of filtered) {
      if (seen.has(action.title)) continue
      seen.add(action.title)
      out.push(action)
    }

    return out.slice(0, query.trim() ? 6 : DEFAULT_EMPTY_STRUCTURE_RESULTS)
  }, [commonStructureActions, formulaAction, query])

  const sections = useMemo(
    () =>
      [
        { title: 'Structures', items: structureActions },
        { title: 'Series', items: seriesActions },
      ].filter((section) => section.items.length > 0),
    [seriesActions, structureActions]
  )

  const flatActions = useMemo(
    () => sections.flatMap((section) => section.items),
    [sections]
  )

  useEffect(() => {
    setActiveIndex(0)
  }, [query, flatActions.length])

  useEffect(() => {
    const handleMouseDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setIsOpen(false)
        setShowHelp(false)
      }
    }

    document.addEventListener('mousedown', handleMouseDown)
    return () => document.removeEventListener('mousedown', handleMouseDown)
  }, [])

  const applyAction = (action: CommandAction) => {
    action.onSelect()
    setQuery('')
    setIsOpen(false)
    setShowHelp(false)
    setActiveIndex(0)
    inputRef.current?.focus()
  }

  return (
    <div ref={rootRef} className="relative min-w-[320px] flex-1">
      <div className="space-y-1">
        <span className="text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Add Instrument / Structure
        </span>
        <div className="relative rounded-md border border-slate-700/80 bg-slate-950/85 px-2.5 py-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onFocus={() => setIsOpen(true)}
            onChange={(event) => {
              setQuery(event.target.value)
              setIsOpen(true)
            }}
            onKeyDown={(event) => {
              if (!flatActions.length) {
                if (event.key === 'Escape') {
                  setIsOpen(false)
                }
                return
              }

              if (event.key === 'ArrowDown') {
                event.preventDefault()
                setIsOpen(true)
                setActiveIndex((current) => (current + 1) % flatActions.length)
              } else if (event.key === 'ArrowUp') {
                event.preventDefault()
                setIsOpen(true)
                setActiveIndex((current) => (current - 1 + flatActions.length) % flatActions.length)
              } else if (event.key === 'Enter') {
                event.preventDefault()
                applyAction(flatActions[activeIndex] ?? flatActions[0])
              } else if (event.key === 'Escape') {
                setIsOpen(false)
                setShowHelp(false)
              }
            }}
            placeholder="TY1M, TY1M 10D Call, 1Mx7Y 25bp Payer, spread TY1M vs 1Mx7Y"
            className="w-full border-0 bg-transparent p-0 pr-7 text-[12px] leading-4 text-slate-100 outline-none placeholder:text-[11px] placeholder:text-slate-500"
          />

          <button
            type="button"
            aria-label="Command bar help"
            aria-expanded={showHelp}
            onClick={() => setShowHelp((current) => !current)}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-slate-500 transition hover:bg-slate-900 hover:text-slate-200"
          >
            <CircleHelp className="h-3.5 w-3.5" />
          </button>

          {showHelp ? (
            <div className="absolute bottom-full right-0 z-40 mb-2 w-[340px] rounded-lg border border-slate-700/80 bg-slate-950/98 p-3 shadow-2xl shadow-black/40">
              <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                Search Guide
              </div>
              <div className="mt-2 space-y-2 text-[11px] leading-5 text-slate-300">
                <div>
                  Search any listed or OTC series with fuzzy aliases such as `TY1M`, `1Mx7Y`,
                  `1M TY`, or `7Y 1M`.
                </div>
                <div>
                  OTM nodes are supported with queries like `TY1M 10D Call`, `TY1M 25bp Put`,
                  `1Mx7Y 10D Payer`, or `1Mx7Y 25bp Receiver`.
                </div>
                <div>
                  Type spread commands like `spread TY1M vs 1Mx7Y` or `TY1M / 1Mx7Y` to add both
                  legs and create a RHS formula line automatically.
                </div>
                <div>
                  Type fly commands like `fly TU1M/FV1M/TY1M` to add three legs and build a
                  +1 / -2 / +1 fly structure.
                </div>
                <div className="text-slate-500">
                  Press `Enter` to accept the highlighted result. Arrow keys navigate the command
                  list.
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {isOpen ? (
        <div className="absolute left-0 right-0 top-full z-30 mt-2 overflow-hidden rounded-lg border border-slate-700/80 bg-slate-950/98 shadow-2xl shadow-black/40">
          {sections.length ? (
            <div className="max-h-[320px] overflow-y-auto">
              {sections.map((section) => (
                <div key={section.title} className="border-b border-slate-800/80 last:border-b-0">
                  <div className="bg-slate-950/90 px-3 py-1.5 text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                    {section.title}
                  </div>
                  <div>
                    {section.items.map((action) => {
                      const optionIndex = flatActions.findIndex((candidate) => candidate.id === action.id)
                      const isActive = optionIndex === activeIndex

                      return (
                        <button
                          key={action.id}
                          type="button"
                          onMouseDown={(event) => {
                            event.preventDefault()
                            applyAction(action)
                          }}
                          onMouseEnter={() => setActiveIndex(optionIndex)}
                          className={`flex w-full items-start justify-between gap-2.5 px-3 py-1.5 text-left transition ${
                            isActive ? 'bg-slate-900/90' : 'hover:bg-slate-900/65'
                          }`}
                        >
                          <div className="min-w-0">
                            <div className="truncate text-[12px] leading-4 text-slate-100">
                              {action.title}
                            </div>
                            <div className="truncate text-[10px] leading-4 text-slate-500">
                              {action.description}
                            </div>
                          </div>
                          <span className="shrink-0 rounded border border-slate-700/80 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.1em] text-slate-300">
                            {action.badge}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="px-3 py-4 text-sm text-slate-500">
              No matching series or structures. Try `TY1M`, `1Mx7Y`, or a spread/fly command.
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}
