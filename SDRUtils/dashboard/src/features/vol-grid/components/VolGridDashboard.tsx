'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import type {
  CalibrationFilterConfig,
  CalibrationObservation,
  CalibrationPresetKey,
  VolGridHeatmapConfig,
  VolGridSessionMeta,
  VolGridSurfaceResponse
} from '../types'
import {
  CALIBRATION_PRESETS,
  CANONICAL_PRESET_OPTIONS,
  GRID_DEFINITION,
  IDB_STRADDLES_PRESET,
  resolveSnapshotPreset
} from '../constants'
import {
  formatDateTime,
  formatNotional,
  formatNumber,
  parseHeatmapHighlightTargets
} from '../utils'
import { UnifiedGridCell } from './UnifiedGridCell'
import { CellAnalyticsModal } from './CellAnalyticsModal'
import { CellSettingsPopover } from './CellSettingsPopover'
import { SummaryBar } from './SummaryBar'
import { VolGridSurface3D } from './VolGridSurface3D'
import { useCellDetail } from '../hooks/useCellDetail'
import { useCellDisplayConfig } from '../hooks/useCellDisplayConfig'

const DEFAULT_PRESET: CalibrationPresetKey = 'idb_straddles'
const EMPTY_GRID_CELLS: VolGridSurfaceResponse['cells'] = []

function normalizeSelectablePreset(value: CalibrationPresetKey) {
  return resolveSnapshotPreset(value)
}

function formatSnapshotKindLabel(value: VolGridSurfaceResponse['meta']['snapshotKind'] | null) {
  switch (value) {
    case 'close_pca':
      return 'PCA close'
    case 'close_mdp':
      return 'MDP close'
    case 'intraday':
      return 'intraday snapshot'
    default:
      return 'snapshot'
  }
}

function formatDisplayDateKey(value: string | null | undefined) {
  if (!value) return '--'
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: 'short',
    day: '2-digit'
  }).format(new Date(`${value}T12:00:00Z`))
}

function getSessionAccent(session: VolGridSessionMeta | null) {
  switch (session?.mode) {
    case 'weekend_close':
      return 'border-violet-500/40 bg-violet-500/10 text-violet-100'
    case 'eod_close':
      return 'border-amber-500/40 bg-amber-500/10 text-amber-100'
    case 'preopen_close':
      return 'border-sky-500/40 bg-sky-500/10 text-sky-100'
    case 'prior_close':
      return 'border-slate-600 bg-slate-800/70 text-slate-100'
    case 'historical':
      return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-100'
    default:
      return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-100'
  }
}

type DashboardTab = 'grid' | 'surface'

type VolGridDashboardProps = {
  initialTab?: DashboardTab
  lockTab?: boolean
  showDatePicker?: boolean
}

function formatHeatmapSummary(
  heatmap: VolGridHeatmapConfig,
  highlightedCount: number
) {
  switch (heatmap.strategy) {
    case 'none':
      return 'Heatmap: off'
    case 'absolute':
      return `Heatmap: absolute ${heatmap.metric === 'premium' ? 'premium' : 'vol'}${
        heatmap.inverted ? ' (inverse)' : ''
      }`
    case 'delta':
      return `Heatmap: delta ${heatmap.metric === 'premium' ? 'premium' : 'vol'}${
        heatmap.inverted ? ' (inverse)' : ''
      }`
    case 'custom':
      return `Heatmap: custom ${
        highlightedCount === 1 ? 'highlight' : 'highlights'
      } (${highlightedCount})${heatmap.inverted ? ' (inverse)' : ''}`
    default:
      return 'Heatmap: off'
  }
}

export default function VolGridDashboard({
  initialTab = 'grid',
  lockTab = false,
  showDatePicker = true
}: VolGridDashboardProps) {
  const [surface, setSurface] = useState<VolGridSurfaceResponse | null>(null)
  const [preset, setPreset] = useState<CalibrationPresetKey>(DEFAULT_PRESET)
  const [activeTab, setActiveTab] = useState<DashboardTab>(initialTab)
  const [selectedDate, setSelectedDate] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [feed, setFeed] = useState<CalibrationObservation[]>([])
  const [filteredOutCount, setFilteredOutCount] = useState(0)
  const [configOpen, setConfigOpen] = useState(false)
  const [cellSettingsOpen, setCellSettingsOpen] = useState(false)
  const [feedOpen, setFeedOpen] = useState(false)
  const [configDraft, setConfigDraft] =
    useState<CalibrationFilterConfig>(IDB_STRADDLES_PRESET)
  const [specificPlatforms, setSpecificPlatforms] = useState('')
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null)

  const {
    config: displayConfig,
    toggleField,
    toggleLastTradedLevelField,
    setHeatmapStrategy,
    setHeatmapMetric,
    toggleHeatmapInversion,
    setHeatmapCustomTargets,
    resetToDefaults
  } = useCellDisplayConfig()

  const selectedCell = useMemo(
    () => surface?.cells.find((cell) => cell.nodeKey === selectedNodeKey) ?? null,
    [surface, selectedNodeKey]
  )
  const detail = useCellDetail(
    selectedCell?.expiry ?? null,
    selectedCell?.tenor ?? null,
    preset,
    surface?.meta.session.effectiveDate ?? null
  )
  const comparisonMeta = surface?.meta.comparison ?? null

  const heatmapRange = useMemo(() => {
    const cells = surface?.cells ?? EMPTY_GRID_CELLS
    const volValues = cells
      .map((cell) => cell.atmfVol)
      .filter((value): value is number => value !== null && Number.isFinite(value))
    const premiumValues = cells
      .map((cell) => cell.atmfPremiumBps)
      .filter((value): value is number => value !== null && Number.isFinite(value))
    const volChangeValues = cells
      .map((cell) => cell.atmfVolChange)
      .filter((value): value is number => value !== null && Number.isFinite(value))
    const premiumChangeValues = cells
      .map((cell) => cell.atmfPremiumBpsChange)
      .filter((value): value is number => value !== null && Number.isFinite(value))
    return {
      volMin: volValues.length ? Math.min(...volValues) : 0,
      volMax: volValues.length ? Math.max(...volValues) : 0,
      premiumMin: premiumValues.length ? Math.min(...premiumValues) : 0,
      premiumMax: premiumValues.length ? Math.max(...premiumValues) : 0,
      volChangeMaxAbs: volChangeValues.length
        ? Math.max(...volChangeValues.map((value) => Math.abs(value)))
        : 0,
      premiumChangeMaxAbs: premiumChangeValues.length
        ? Math.max(...premiumChangeValues.map((value) => Math.abs(value)))
        : 0
    }
  }, [surface?.cells])

  const highlightedNodeKeys = useMemo(
    () => new Set(parseHeatmapHighlightTargets(displayConfig.heatmap.customTargets)),
    [displayConfig.heatmap.customTargets]
  )
  const resolvedTab = lockTab ? initialTab : activeTab
  const isGridView = resolvedTab === 'grid'
  const isSurfaceView = resolvedTab === 'surface'
  const pageTitle = isSurfaceView ? 'Vol Plotter' : 'Live ATMF Vol Grid'

  const loadConfig = useCallback(async () => {
    try {
      const res = await fetch('/api/vol-grid/calibration-config')
      if (!res.ok) return
      const data = await res.json()
      if (data?.config) {
        setConfigDraft(data.config)
        setSpecificPlatforms((data.config.platforms?.specificPlatforms ?? []).join(', '))
      }
      if (data?.preset) {
        setPreset(normalizeSelectablePreset(data.preset as CalibrationPresetKey))
      }
    } catch (fetchError) {
      console.error(fetchError)
    }
  }, [])

  const loadSurface = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        calibration_preset: preset,
        include_premium: 'true'
      })
      if (selectedDate) {
        params.set('date', selectedDate)
      }
      const res = await fetch(`/api/vol-grid/surface?${params.toString()}`)
      if (!res.ok) throw new Error('Surface fetch failed')
      const data = (await res.json()) as VolGridSurfaceResponse
      setSurface(data)
      setFilteredOutCount(data.meta.filteredOutCount)
    } catch (fetchError: any) {
      setError(fetchError?.message || 'Unable to load vol grid')
    } finally {
      setLoading(false)
    }
  }, [preset, selectedDate])

  const loadFeed = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        calibration_preset: preset
      })
      if (selectedDate) {
        params.set('date', selectedDate)
      }
      const res = await fetch(`/api/vol-grid/calibration-trades?${params.toString()}`)
      if (!res.ok) return
      const data = await res.json()
      if (Array.isArray(data?.trades)) {
        setFeed(data.trades)
      }
      if (typeof data?.filteredOutCount === 'number') {
        setFilteredOutCount(data.filteredOutCount)
      }
    } catch (fetchError) {
      console.error(fetchError)
    }
  }, [preset, selectedDate])

  useEffect(() => {
    loadConfig()
  }, [loadConfig])

  useEffect(() => {
    loadSurface()
    if (isGridView) {
      loadFeed()
    }
  }, [isGridView, loadFeed, loadSurface])

  useEffect(() => {
    if (selectedDate || isSurfaceView) return
    const interval = setInterval(() => {
      loadSurface()
      loadFeed()
    }, 5000)
    return () => clearInterval(interval)
  }, [isSurfaceView, loadFeed, loadSurface, selectedDate])

  useEffect(() => {
    setSelectedNodeKey(null)
  }, [preset, selectedDate])

  const handlePresetChange = async (value: CalibrationPresetKey) => {
    setPreset(value)
    try {
      await fetch('/api/vol-grid/calibration-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preset: value })
      })
      loadConfig()
    } catch (fetchError) {
      console.error(fetchError)
    }
  }

  const handleApplyConfig = async () => {
    const platforms = specificPlatforms
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
    const nextConfig: CalibrationFilterConfig = {
      ...configDraft,
      platforms: {
        ...configDraft.platforms,
        specificPlatforms: platforms.length ? platforms : undefined
      }
    }

    try {
      await fetch('/api/vol-grid/calibration-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: nextConfig, preset })
      })
      setConfigOpen(false)
      loadSurface()
      if (isGridView) {
        loadFeed()
      }
    } catch (fetchError) {
      console.error(fetchError)
    }
  }

  const handleResetConfig = () => {
    const presetConfig = CALIBRATION_PRESETS[preset]
    setConfigDraft(presetConfig)
    setSpecificPlatforms((presetConfig.platforms.specificPlatforms ?? []).join(', '))
  }

  const gridCells = surface?.cells ?? EMPTY_GRID_CELLS
  const cellMap = useMemo(
    () => new Map(gridCells.map((cell) => [cell.nodeKey, cell])),
    [gridCells]
  )
  const heatmapSummary = useMemo(
    () => formatHeatmapSummary(displayConfig.heatmap, highlightedNodeKeys.size),
    [displayConfig.heatmap, highlightedNodeKeys]
  )
  const packageTypeEntries = Object.entries(
    configDraft.packageTypes
  ) as Array<[keyof CalibrationFilterConfig['packageTypes'], boolean]>
  const curveLabel = surface?.curve
    ? `Curve: ${surface.curve.curveName} (${surface.curve.source})`
    : 'Curve: --'
  const curveMetaLabel = useMemo(() => {
    if (!surface?.curve) return null
    const surfaceDate = formatDisplayDateKey(surface.asOfDate)
    const referenceDate = surface.curve.referenceDate
      ? formatDisplayDateKey(surface.curve.referenceDate)
      : null

    if (referenceDate && surface.curve.referenceDate && surface.curve.referenceDate !== surface.asOfDate) {
      return `Surface date ${surfaceDate}. Base MDP reference ${referenceDate}.`
    }

    return `Surface date ${surfaceDate}.`
  }, [surface])
  const session = surface?.meta.session ?? null

  const lastUpdateLabel = useMemo(() => {
    if (!surface) return 'Snapshot: --'
    if (!surface.meta.hasData) return 'Snapshot: no stored data'
    if (!surface.meta.lastUpdate) return 'Snapshot: --'
    const label = formatDateTime(surface.meta.lastUpdate)
    const prefix =
      surface.meta.snapshotKind === 'close_mdp'
        ? 'MDP close'
        : surface.meta.snapshotKind === 'close_pca'
          ? 'Closing snapshot'
          : 'Live snapshot'
    return `${prefix}: ${label}`
  }, [surface])

  const observationMessage = useMemo(() => {
    if (!surface) return null
    if (!surface.meta.hasData) {
      return surface.meta.emptyReason
    }
    if (surface.meta.snapshotKind === 'close_mdp') {
      return `${surface.meta.session.label}. Showing the direct ${formatSnapshotKindLabel(surface.meta.snapshotKind)}${surface.meta.comparison ? ' alongside the PCA close comparison.' : '.'}`
    }
    if (surface.meta.calibrationTradeCount > 0) {
      if (surface.meta.session.isClosingView) {
        return `${surface.meta.session.label}. ${surface.meta.calibrationTradeCount} mapped observations in the snapshot.`
      }
      return null
    }
    if (surface.meta.session.isClosingView) {
      return `${surface.meta.session.label}. No mapped observations are available, so the dashboard is showing the closing surface.`
    }
    return 'No direct observations for this preset. Showing the prior surface.'
  }, [surface])

  const feedTitle = 'Observation Feed'
  const feedEmptyMessage = !surface?.meta.hasData
    ? 'No stored live snapshot or EOD close history is available yet.'
    : session?.isClosingView
      ? 'No mapped observations for this closing snapshot.'
      : 'No calibration trades yet.'
  const comparisonBanner = comparisonMeta
    ? `Comparing ${formatSnapshotKindLabel(surface?.meta.snapshotKind ?? null)} against ${formatSnapshotKindLabel(comparisonMeta.snapshotKind)}.`
    : null
  const requestedDateMismatch =
    Boolean(selectedDate) && Boolean(session?.effectiveDate) && session?.effectiveDate !== selectedDate

  return (
    <>
      <div className="space-y-4">
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 shadow-xl xl:[zoom:0.8]">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-white">
                {pageTitle}
              </h1>
              <p className="text-sm text-slate-400">{curveLabel}</p>
              {curveMetaLabel && (
                <p className="mt-1 text-xs text-slate-500">{curveMetaLabel}</p>
              )}
            </div>
            <div className="flex flex-wrap items-center justify-end gap-3">
              {!lockTab && (
                <div className="inline-flex overflow-hidden rounded-lg border border-slate-700">
                  {([
                    ['grid', 'Grid'],
                    ['surface', 'Surface 3D']
                  ] as Array<[DashboardTab, string]>).map(([tab, label]) => (
                    <button
                      key={tab}
                      type="button"
                      onClick={() => setActiveTab(tab)}
                      className={`px-3 py-2 text-xs font-semibold uppercase tracking-wide transition ${
                        activeTab === tab
                          ? 'bg-slate-700 text-slate-100'
                          : 'text-slate-300 hover:bg-slate-800'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}
              {showDatePicker && (
                <>
                  <label className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-300">
                    <span className="uppercase tracking-wide text-slate-500">Date</span>
                    <input
                      type="date"
                      value={selectedDate}
                      onChange={(event) => setSelectedDate(event.target.value)}
                      className="bg-transparent text-slate-100 outline-none"
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => setSelectedDate('')}
                    disabled={!selectedDate}
                    className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-200 transition hover:border-slate-500 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Live
                  </button>
                </>
              )}
              <select
                value={normalizeSelectablePreset(preset)}
                onChange={(event) =>
                  handlePresetChange(event.target.value as CalibrationPresetKey)
                }
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
              >
                {CANONICAL_PRESET_OPTIONS.map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.label}
                  </option>
                ))}
              </select>
              {isGridView && (
                <button
                  onClick={() => setCellSettingsOpen((open) => !open)}
                  className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:border-slate-500"
                >
                  Cell Fields
                </button>
              )}
              <button
                onClick={() => setConfigOpen((open) => !open)}
                className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:border-slate-500"
              >
                Configure
              </button>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <div className="text-xs text-slate-400">{lastUpdateLabel}</div>
            {loading && <div className="text-xs text-slate-500">Refreshing...</div>}
            {error && <div className="text-xs text-rose-400">{error}</div>}
            {selectedDate && (
              <div className="rounded-full border border-slate-700 px-2.5 py-1 text-[11px] text-slate-300">
                Requested date {selectedDate}
              </div>
            )}
          </div>

          {comparisonBanner && (
            <div className="mt-2 text-xs text-slate-500">{comparisonBanner}</div>
          )}

          {requestedDateMismatch && session && (
            <div className="mt-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
              Requested {selectedDate}, showing latest stored surface on or before{' '}
              {session.effectiveDate}.
            </div>
          )}

          {session && surface?.meta.hasData && (
            <div
              className={`mt-4 flex flex-wrap items-center gap-3 rounded-xl border px-3 py-2 text-xs ${getSessionAccent(session)}`}
            >
              <span className="font-semibold uppercase tracking-[0.2em]">
                {session.mode === 'live' ? 'Live' : 'Closing View'}
              </span>
              <span>{session.label}</span>
            </div>
          )}

          {observationMessage && (
            <div className="mt-2 text-xs text-slate-500">{observationMessage}</div>
          )}

          {isGridView && cellSettingsOpen && (
            <CellSettingsPopover
              config={displayConfig}
              onToggle={toggleField}
              onToggleLastTradedLevelField={toggleLastTradedLevelField}
              onSetHeatmapStrategy={setHeatmapStrategy}
              onSetHeatmapMetric={setHeatmapMetric}
              onToggleHeatmapInversion={toggleHeatmapInversion}
              onSetHeatmapCustomTargets={setHeatmapCustomTargets}
              onReset={resetToDefaults}
            />
          )}

          {configOpen && (
            <div className="mt-6 rounded-xl border border-slate-800 bg-slate-950/70 p-4">
              <h2 className="text-sm font-semibold text-slate-200">
                Calibration Settings
              </h2>
              <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
                <label className="text-xs text-slate-400">
                  Platforms
                  <div className="mt-2 flex flex-wrap gap-3 text-sm">
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={configDraft.platforms.idb}
                        onChange={(event) =>
                          setConfigDraft({
                            ...configDraft,
                            platforms: {
                              ...configDraft.platforms,
                              idb: event.target.checked
                            }
                          })
                        }
                      />
                      IDB
                    </label>
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={configDraft.platforms.custy}
                        onChange={(event) =>
                          setConfigDraft({
                            ...configDraft,
                            platforms: {
                              ...configDraft.platforms,
                              custy: event.target.checked
                            }
                          })
                        }
                      />
                      Custy
                    </label>
                  </div>
                  <input
                    value={specificPlatforms}
                    onChange={(event) => setSpecificPlatforms(event.target.value)}
                    placeholder="Specific platforms (comma-separated)"
                    className="mt-2 w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200"
                  />
                </label>
                <label className="text-xs text-slate-400">
                  Structures
                  <div className="mt-2 flex flex-wrap gap-3 text-sm">
                    {packageTypeEntries.map(([key, value]) => (
                      <label key={key} className="flex items-center gap-2 capitalize">
                        <input
                          type="checkbox"
                          checked={value}
                          onChange={(event) =>
                            setConfigDraft({
                              ...configDraft,
                              packageTypes: {
                                ...configDraft.packageTypes,
                                [key]: event.target.checked
                              }
                            })
                          }
                        />
                        {key}
                      </label>
                    ))}
                  </div>
                </label>
                <label className="text-xs text-slate-400">
                  Observation Half-life (min)
                  <input
                    type="number"
                    value={configDraft.observationHalfLife}
                    onChange={(event) =>
                      setConfigDraft({
                        ...configDraft,
                        observationHalfLife: Number(event.target.value)
                      })
                    }
                    className="mt-2 w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200"
                  />
                </label>
                <label className="text-xs text-slate-400">
                  Max Staleness (min)
                  <input
                    type="number"
                    value={configDraft.maxStalenessMinutes}
                    onChange={(event) =>
                      setConfigDraft({
                        ...configDraft,
                        maxStalenessMinutes: Number(event.target.value)
                      })
                    }
                    className="mt-2 w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200"
                  />
                </label>
                <label className="text-xs text-slate-400">
                  Tenor Weight
                  <input
                    type="number"
                    step="0.1"
                    value={configDraft.tenorWeight}
                    onChange={(event) =>
                      setConfigDraft({
                        ...configDraft,
                        tenorWeight: Number(event.target.value)
                      })
                    }
                    className="mt-2 w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200"
                  />
                </label>
                <label className="text-xs text-slate-400">
                  Expiry Weight
                  <input
                    type="number"
                    step="0.1"
                    value={configDraft.expiryWeight}
                    onChange={(event) =>
                      setConfigDraft({
                        ...configDraft,
                        expiryWeight: Number(event.target.value)
                      })
                    }
                    className="mt-2 w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200"
                  />
                </label>
              </div>
              <div className="mt-4 flex gap-3">
                <button
                  onClick={handleApplyConfig}
                  className="rounded-lg bg-amber-400 px-4 py-2 text-xs font-semibold text-slate-900"
                >
                  Apply
                </button>
                <button
                  onClick={handleResetConfig}
                  className="rounded-lg border border-slate-700 px-4 py-2 text-xs text-slate-200"
                >
                  Reset to Preset
                </button>
              </div>
            </div>
          )}
        </div>

        {isGridView ? (
          <div className={`grid gap-4 ${feedOpen ? 'xl:grid-cols-[minmax(0,1fr)_290px]' : 'grid-cols-1'}`}>
            <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-3">
              <div className="overflow-x-auto">
                <div
                  className="grid gap-[2px]"
                  style={{
                    minWidth: `${58 + GRID_DEFINITION.tenors.length * 82}px`,
                    gridTemplateColumns: `58px repeat(${GRID_DEFINITION.tenors.length}, minmax(82px, 1fr))`
                  }}
                >
                  <div className="bg-slate-900 px-2 py-1.5 text-[10px] uppercase leading-tight text-slate-400">
                    Expiry \ Tenor
                  </div>
                  {GRID_DEFINITION.tenors.map((tenor) => (
                    <div
                      key={tenor}
                      className="bg-slate-900 px-2 py-1.5 text-center text-[10px] font-semibold uppercase tracking-wide text-slate-400"
                    >
                      {tenor}
                    </div>
                  ))}
                  {GRID_DEFINITION.expiries.map((expiry) => (
                    <div key={expiry} className="contents">
                      <div className="bg-slate-900 px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                        {expiry}
                      </div>
                      {GRID_DEFINITION.tenors.map((tenor) => {
                        const nodeKey = `${expiry.toLowerCase()}_${tenor.toLowerCase()}`
                        const cell = cellMap.get(nodeKey)
                        if (!cell) {
                          return (
                            <div
                              key={`${expiry}-${tenor}`}
                              className="min-h-[90px] bg-slate-900/40 p-2 text-center text-xs text-slate-500"
                            >
                              --
                            </div>
                          )
                        }
                        return (
                          <UnifiedGridCell
                            key={`${expiry}-${tenor}`}
                            cell={cell}
                            isSelected={selectedNodeKey === cell.nodeKey}
                            visibleFields={displayConfig.visibleFields}
                            lastTradedLevelFields={displayConfig.lastTradedLevelFields}
                            heatmap={displayConfig.heatmap}
                            heatmapRange={heatmapRange}
                            highlightedNodeKeys={highlightedNodeKeys}
                            onClick={() => setSelectedNodeKey(cell.nodeKey)}
                          />
                        )
                      })}
                    </div>
                  ))}
                </div>
              </div>
              <div className="mt-3 text-xs text-slate-500">{heatmapSummary}</div>
              <div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-400">
                <span className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-emerald-400" /> live (&lt;15m)
                </span>
                <span className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-amber-400" /> recent (&lt;1h)
                </span>
                <span className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-rose-500" /> stale (&lt;4h)
                </span>
                <span className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-slate-500" /> very stale
                </span>
              </div>
              <SummaryBar
                cells={gridCells}
                lastUpdate={surface?.meta.lastUpdate ?? null}
                session={session}
                hasData={surface?.meta.hasData ?? false}
                comparisonActive={false}
                comparisonLabel={null}
              />
            </div>

            <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-slate-200">{feedTitle}</h2>
                  <div className="mt-1 text-[11px] text-slate-500">
                    {feed.length} mapped trade{feed.length === 1 ? '' : 's'} shown
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setFeedOpen((open) => !open)}
                  className="rounded-lg border border-slate-700 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-200 transition hover:border-slate-500 hover:bg-slate-900"
                >
                  {feedOpen ? 'Collapse' : 'Expand'}
                </button>
              </div>
              {feedOpen ? (
                <>
                  <div className="mt-3 max-h-[46rem] space-y-2 overflow-y-auto pr-1 text-xs text-slate-300">
                {feed.length === 0 && (
                  <div className="text-slate-500">{feedEmptyMessage}</div>
                )}
                {feed.map((trade) => (
                  <div
                    key={`${trade.packageId}-${trade.executionTimestamp}`}
                    className="rounded-xl border border-slate-800/70 bg-slate-900/60 px-3 py-2"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-[11px] font-semibold text-slate-100">
                          {formatDateTime(trade.executionTimestamp)}
                        </div>
                        <div className="truncate text-sm font-semibold text-white">
                          {trade.tradeLabel}
                        </div>
                        <div className="mt-1 text-[11px] text-slate-400">
                          {trade.platform ?? '--'} · {trade.expiry ?? '--'}x{trade.tenor ?? '--'} ·{' '}
                          {formatNotional(trade.notional)}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-lg font-semibold text-white">
                          {formatNumber(trade.bpvolYr, 2)}
                        </div>
                        <div className="text-[11px] text-slate-400">bpvol</div>
                      </div>
                    </div>
                  </div>
                ))}
                  </div>
                  <div className="mt-4 text-xs text-slate-500">
                    Filtered out: {filteredOutCount} trades
                  </div>
                </>
              ) : (
                <div className="mt-3 text-[11px] text-slate-500">
                  Feed hidden by default. Expand to inspect mapped trades.
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
              <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-slate-200">
                    Vol Plotter
                  </h2>
                <div className="mt-1 text-[11px] text-slate-500">
                  Rotatable 3D surface for {surface?.meta.session.effectiveDate ?? 'the current snapshot'}.
                </div>
                </div>
                <div className="text-[11px] text-slate-500">dVol and dPrem remain visible in the grid view.</div>
            </div>
            <VolGridSurface3D
              cells={gridCells}
              expiries={GRID_DEFINITION.expiries}
              tenors={GRID_DEFINITION.tenors}
              asOfDate={surface?.meta.session.effectiveDate ?? null}
            />
          </div>
        )}
      </div>

      <CellAnalyticsModal
        cell={selectedCell}
        detail={detail.data}
        loading={detail.loading}
        error={detail.error}
        session={session}
        onClose={() => setSelectedNodeKey(null)}
      />
    </>
  )
}
