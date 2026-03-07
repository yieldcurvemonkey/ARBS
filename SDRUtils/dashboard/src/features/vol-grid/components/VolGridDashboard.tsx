'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import type {
  CalibrationFilterConfig,
  CalibrationObservation,
  CalibrationPresetKey,
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
  formatChange,
  formatDateTime,
  formatNotional,
  formatNumber,
  formatTime
} from '../utils'
import { UnifiedGridCell } from './UnifiedGridCell'
import { CellAnalyticsModal } from './CellAnalyticsModal'
import { CellSettingsPopover } from './CellSettingsPopover'
import { SummaryBar } from './SummaryBar'
import { useCellDetail } from '../hooks/useCellDetail'
import { useCellDisplayConfig } from '../hooks/useCellDisplayConfig'

const DEFAULT_PRESET: CalibrationPresetKey = 'idb_straddles'

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

export default function VolGridDashboard() {
  const [surface, setSurface] = useState<VolGridSurfaceResponse | null>(null)
  const [preset, setPreset] = useState<CalibrationPresetKey>(DEFAULT_PRESET)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [feed, setFeed] = useState<CalibrationObservation[]>([])
  const [filteredOutCount, setFilteredOutCount] = useState(0)
  const [configOpen, setConfigOpen] = useState(false)
  const [cellSettingsOpen, setCellSettingsOpen] = useState(false)
  const [configDraft, setConfigDraft] =
    useState<CalibrationFilterConfig>(IDB_STRADDLES_PRESET)
  const [specificPlatforms, setSpecificPlatforms] = useState('')
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null)

  const { config: displayConfig, toggleField, resetToDefaults } = useCellDisplayConfig()

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

  const volRange = useMemo(() => {
    if (!surface) return { min: 0, max: 0 }
    const values = surface.cells
      .map((cell) => cell.atmfVol)
      .filter((v): v is number => v !== null && Number.isFinite(v))
    return {
      min: values.length ? Math.min(...values) : 0,
      max: values.length ? Math.max(...values) : 0
    }
  }, [surface])

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
    } catch (err) {
      console.error(err)
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
      const res = await fetch(`/api/vol-grid/surface?${params.toString()}`)
      if (!res.ok) throw new Error('Surface fetch failed')
      const data = (await res.json()) as VolGridSurfaceResponse
      setSurface(data)
      setFilteredOutCount(data.meta.filteredOutCount)
    } catch (err: any) {
      setError(err?.message || 'Unable to load vol grid')
    } finally {
      setLoading(false)
    }
  }, [preset])

  const loadFeed = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        calibration_preset: preset
      })
      const res = await fetch(`/api/vol-grid/calibration-trades?${params.toString()}`)
      if (!res.ok) return
      const data = await res.json()
      if (Array.isArray(data?.trades)) {
        setFeed(data.trades)
      }
      if (typeof data?.filteredOutCount === 'number') {
        setFilteredOutCount(data.filteredOutCount)
      }
    } catch (err) {
      console.error(err)
    }
  }, [preset])

  useEffect(() => {
    loadConfig()
  }, [loadConfig])

  useEffect(() => {
    loadSurface()
    loadFeed()
    const interval = setInterval(() => {
      loadSurface()
      loadFeed()
    }, 5000)
    return () => clearInterval(interval)
  }, [loadSurface, loadFeed])

  const handlePresetChange = async (value: CalibrationPresetKey) => {
    setPreset(value)
    try {
      await fetch('/api/vol-grid/calibration-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preset: value })
      })
      loadConfig()
    } catch (err) {
      console.error(err)
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
      loadFeed()
    } catch (err) {
      console.error(err)
    }
  }

  const handleResetConfig = () => {
    const presetConfig = CALIBRATION_PRESETS[preset]
    setConfigDraft(presetConfig)
    setSpecificPlatforms((presetConfig.platforms.specificPlatforms ?? []).join(', '))
  }

  const gridCells = surface?.cells ?? []
  const cellMap = useMemo(
    () => new Map(gridCells.map((cell) => [cell.nodeKey, cell])),
    [gridCells]
  )
  const packageTypeEntries = Object.entries(
    configDraft.packageTypes
  ) as Array<[keyof CalibrationFilterConfig['packageTypes'], boolean]>
  const curveLabel = surface?.curve
    ? `Curve: ${surface.curve.curveName} (${surface.curve.source}) ${surface.curve.referenceDate ?? ''}`
    : 'Curve: --'
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

  const feedTitle = !surface?.meta.hasData
    ? 'Observation Feed'
    : session?.isClosingView
      ? 'Closing Observation Feed'
      : 'Calibration Feed'
  const feedEmptyMessage = !surface?.meta.hasData
    ? 'No stored live snapshot or EOD close history is available yet.'
    : session?.isClosingView
      ? 'No mapped observations for this closing snapshot.'
      : 'No calibration trades yet.'
  const comparisonBanner = comparisonMeta
    ? `Comparing ${formatSnapshotKindLabel(surface?.meta.snapshotKind ?? null)} against ${formatSnapshotKindLabel(comparisonMeta.snapshotKind)}.`
    : null

  return (
    <>
      <div className="space-y-6 xl:[zoom:0.8]">
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-white">
                ATMF Vol Grid
              </h1>
              <p className="text-sm text-slate-400">{curveLabel}</p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
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
              <button
                onClick={() => setCellSettingsOpen((open) => !open)}
                className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:border-slate-500"
              >
                Cell Fields
              </button>
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
          </div>

          {comparisonBanner && (
            <div className="mt-2 text-xs text-slate-500">{comparisonBanner}</div>
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
            <div className="mt-2 text-xs text-slate-500">
              {observationMessage}
            </div>
          )}

          {cellSettingsOpen && (
            <CellSettingsPopover
              config={displayConfig}
              onToggle={toggleField}
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

        <div className="grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,1.2fr)]">
          <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
            <div
              className="grid gap-[2px]"
              style={{
                gridTemplateColumns: `100px repeat(${GRID_DEFINITION.tenors.length}, minmax(120px, 1fr))`
              }}
            >
              <div className="bg-slate-900 p-2 text-xs uppercase text-slate-400">
                Expiry \ Tenor
              </div>
              {GRID_DEFINITION.tenors.map((tenor) => (
                <div
                  key={tenor}
                  className="bg-slate-900 p-2 text-center text-xs uppercase text-slate-400"
                >
                  {tenor}
                </div>
              ))}
              {GRID_DEFINITION.expiries.map((expiry) => (
                <div key={expiry} className="contents">
                  <div className="bg-slate-900 p-2 text-xs uppercase text-slate-400">
                    {expiry}
                  </div>
                  {GRID_DEFINITION.tenors.map((tenor) => {
                    const nodeKey = `${expiry.toLowerCase()}_${tenor.toLowerCase()}`
                    const cell = cellMap.get(nodeKey)
                    if (!cell) {
                      return (
                        <div
                          key={`${expiry}-${tenor}`}
                          className="min-h-[110px] bg-slate-900/40 p-2 text-center text-xs text-slate-500"
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
                        volMin={volRange.min}
                        volMax={volRange.max}
                        onClick={() => setSelectedNodeKey(cell.nodeKey)}
                      />
                    )
                  })}
                </div>
              ))}
            </div>
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
            <h2 className="text-sm font-semibold text-slate-200">
              {feedTitle}
            </h2>
            <div className="mt-1 text-[11px] text-slate-500">
              {feed.length} mapped trade{feed.length === 1 ? '' : 's'} shown
            </div>
            <div className="mt-2 max-h-[38rem] space-y-2 overflow-y-auto pr-1 text-xs text-slate-300">
              {feed.length === 0 && (
                <div className="text-slate-500">{feedEmptyMessage}</div>
              )}
              {feed.map((trade) => (
                <div
                  key={`${trade.packageId}-${trade.executionTimestamp}`}
                  className="flex items-center justify-between gap-2 rounded-md bg-slate-900/60 p-2"
                >
                  <div>
                    <div className="font-semibold text-slate-200">
                      {formatTime(trade.executionTimestamp)} {trade.tradeLabel}
                    </div>
                    <div className="text-[11px] text-slate-400">
                      {trade.platform ?? '--'} · {trade.expiry ?? '--'}x{trade.tenor ?? '--'} ·{' '}
                      {formatNotional(trade.notional)}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-semibold">
                      {formatNumber(trade.bpvolYr, 1)}
                    </div>
                    <div className="text-[11px] text-slate-400">bpvol</div>
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 text-xs text-slate-500">
              Filtered out: {filteredOutCount} trades
            </div>
          </div>
        </div>
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
