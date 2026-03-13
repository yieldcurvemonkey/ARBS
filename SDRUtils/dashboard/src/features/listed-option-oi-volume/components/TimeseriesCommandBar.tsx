'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { CircleHelp } from 'lucide-react'

import type {
  ListedOptionSearchOption,
  ListedOptionSeriesConfig,
} from '../types'
import {
  parseTimeseriesFormulaCommand,
  searchTimeseriesSeriesOptions,
} from '../utils'

type FormulaInput = {
  name: string
  legs: Array<{ seriesId: string; weight: number }>
  series: ListedOptionSeriesConfig[]
}

type Props = {
  options: ListedOptionSearchOption[]
  selectedSeriesIds: string[]
  onAddSeries: (config: ListedOptionSeriesConfig) => void
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

export function TimeseriesCommandBar({
  options,
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

  const availableOptions = useMemo(
    () => options.filter((option) => !selectedSeriesIds.includes(option.id)),
    [options, selectedSeriesIds]
  )

  const formulaAction = useMemo<CommandAction | null>(() => {
    const parsed = parseTimeseriesFormulaCommand(query, availableOptions)
    if (!parsed) return null

    return {
      id: `${parsed.formulaKind}:${parsed.name}`,
      section: 'Structures',
      badge: parsed.formulaKind.toUpperCase(),
      title: parsed.name,
      description: parsed.description,
      onSelect: () =>
        onAddFormula({
          name: parsed.name,
          series: parsed.series,
          legs: parsed.legs,
        }),
    }
  }, [availableOptions, onAddFormula, query])

  const seriesActions = useMemo<CommandAction[]>(
    () =>
      searchTimeseriesSeriesOptions(query, availableOptions, query.trim() ? 12 : 18).map((option) => ({
        id: option.id,
        section: 'Series',
        badge: option.bucket.toUpperCase(),
        title: option.label,
        description: option.subtitle,
        onSelect: () => onAddSeries(option.config),
      })),
    [availableOptions, onAddSeries, query]
  )

  const sections = useMemo(
    () =>
      [
        formulaAction
          ? {
              title: 'Structures' as const,
              items: [formulaAction],
            }
          : null,
        {
          title: 'Series' as const,
          items: seriesActions,
        },
      ].filter((section): section is { title: 'Structures' | 'Series'; items: CommandAction[] } =>
        Boolean(section && section.items.length)
      ),
    [formulaAction, seriesActions]
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
          Add Series / Structure
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
                applyAction(flatActions[activeIndex] ?? flatActions[0]!)
              } else if (event.key === 'Escape') {
                setIsOpen(false)
                setShowHelp(false)
              }
            }}
            placeholder="Type a symbol, alias, spread, or fly"
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
            <div className="absolute bottom-full right-0 z-40 mb-2 w-[360px] rounded-lg border border-slate-700/80 bg-slate-950/98 p-3 shadow-2xl shadow-black/40">
              <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                Search Guide
              </div>
              <div className="mt-2 space-y-2 text-[11px] leading-5 text-slate-300">
                <div>
                  Search visible contracts, constant-maturity rows, or raw option symbols from the
                  current matrix.
                </div>
                <div>
                  Type commands like `spread TY CM1 25D Call OI vs SFR CM1 25D Call OI` or
                  `fly TU CM1 25bp Call OI / FV CM1 25bp Call OI / TY CM1 25bp Call OI`.
                </div>
                <div>
                  Clicking a matrix cell also adds its canonical chart series directly to the monitor.
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
              No matching series or structures. Try a visible contract alias or a spread/fly command.
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}
