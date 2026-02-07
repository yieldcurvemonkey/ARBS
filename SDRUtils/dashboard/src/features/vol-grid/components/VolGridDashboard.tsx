'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import type {
  CalibrationFilterConfig,
  CalibrationObservation,
  CalibrationPresetKey,
  VolGridSurfaceResponse,
  VolGridViewMode
} from '../types'
import { CALIBRATION_PRESETS, GRID_DEFINITION, IDB_STRADDLES_PRESET } from '../constants'
import { clamp } from '../utils'

const MODE_OPTIONS: Array<{ key: VolGridViewMode; label: string }> = [
  { key: 'vol', label: 'VOL' },
  { key: 'premium', label: 'PREMIUM' },
  { key: 'change', label: 'CHANGE' },
  { key: 'staleness', label: 'STALENESS' }
]

const STALENESS_COLORS: Record<string, string> = {
  live: '#22c55e',
  recent: '#f59e0b',
  stale: '#ef4444',
  very_stale: '#6b7280',
  no_data: '#475569'
}

const DEFAULT_PRESET: CalibrationPresetKey = 'idb_straddles'

function formatNumber(value: number | null, digits = 1) {
  if (value === null || !Number.isFinite(value)) return '--'
  return value.toFixed(digits)
}

function formatChange(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '--'
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}${Math.abs(value).toFixed(1)}`
}

function formatPremiumBps(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '--'
  return `${value.toFixed(2)} bp`
}

function formatNotional(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '--'
  return `${(Math.abs(value) / 1_000_000).toFixed(0)}mm`
}

function formatTime(value: number | null) {
  if (!value) return '--'
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(new Date(value))
}

function formatDate(value: number | null) {
  if (!value) return '--'
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: 'short',
    day: '2-digit'
  }).format(new Date(value))
}

function interpolateColor(low: number[], high: number[], t: number) {
  const mix = (a: number, b: number) => Math.round(a + (b - a) * t)
  return `rgb(${mix(low[0], high[0])}, ${mix(low[1], high[1])}, ${mix(low[2], high[2])})`
}

function getHeatColor(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return 'rgba(15, 23, 42, 0.8)'
  const ratio = max > min ? (value - min) / (max - min) : 0.5
  const t = clamp(ratio, 0, 1)
  return interpolateColor([30, 64, 175], [245, 158, 11], t)
}

function getChangeColor(value: number, maxAbs: number) {
  if (!Number.isFinite(value)) return 'rgba(15, 23, 42, 0.8)'
  const ratio = maxAbs > 0 ? Math.abs(value) / maxAbs : 0
  const t = clamp(ratio, 0, 1)
  const base = value >= 0 ? [239, 68, 68] : [34, 197, 94]
  return interpolateColor([30, 41, 59], base, t)
}

function formatStaleness(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '--'
  if (value < 60) return `${Math.round(value)}m`
  return `${(value / 60).toFixed(1)}h`
}

export default function VolGridDashboard() {
  const [surface, setSurface] = useState<VolGridSurfaceResponse | null>(null)
  const [mode, setMode] = useState<VolGridViewMode>('vol')
  const [preset, setPreset] = useState<CalibrationPresetKey>(DEFAULT_PRESET)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [feed, setFeed] = useState<CalibrationObservation[]>([])
  const [filteredOutCount, setFilteredOutCount] = useState(0)
  const [configOpen, setConfigOpen] = useState(false)
  const [configDraft, setConfigDraft] = useState<CalibrationFilterConfig>(IDB_STRADDLES_PRESET)
  const [specificPlatforms, setSpecificPlatforms] = useState('')

  const includePremium = mode === 'premium'

  const viewStats = useMemo(() => {
    if (!surface) return { min: 0, max: 0, maxAbsChange: 0 }
    const values = surface.cells
      .map((cell) => {
        switch (mode) {
          case 'premium':
            return cell.atmfPremiumBps
          case 'change':
            return cell.atmfVolChange
          case 'staleness':
            return cell.staleness
          default:
            return cell.atmfVol
        }
      })
      .filter((val): val is number => val !== null && Number.isFinite(val))

    const min = values.length ? Math.min(...values) : 0
    const max = values.length ? Math.max(...values) : 0
    const maxAbsChange = values.length
      ? Math.max(...values.map((v) => Math.abs(v)))
      : 0

    return { min, max, maxAbsChange }
  }, [surface, mode])

  const loadConfig = useCallback(async () => {
    try {
      const res = await fetch('/api/vol-grid/calibration-config')
      if (!res.ok) return
      const data = await res.json()
      if (data?.config) {
        setConfigDraft(data.config)
        setSpecificPlatforms((data.config.platforms?.specificPlatforms ?? []).join(', '))
      }
      if (data?.preset) setPreset(data.preset)
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
        include_premium: includePremium ? 'true' : 'false'
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
  }, [preset, includePremium])

  const loadFeed = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        calibration_preset: preset
      })
      const res = await fetch(`/api/vol-grid/calibration-trades?${params.toString()}`)
      if (!res.ok) return
      const data = await res.json()
      if (Array.isArray(data?.trades)) {
        setFeed(data.trades.slice().reverse())
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
        body: JSON.stringify({ config: nextConfig })
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
  const packageTypeEntries = Object.entries(
    configDraft.packageTypes
  ) as Array<[keyof CalibrationFilterConfig['packageTypes'], boolean]>
  const curveLabel = surface?.curve
    ? `Curve: ${surface.curve.curveName} (${surface.curve.source}) ${surface.curve.timestamp ?? ''}`
    : 'Curve: --'

  const lastUpdateLabel = useMemo(() => {
    if (!surface?.meta.lastUpdate) return 'Last update: -- ET'
    const time = formatTime(surface.meta.lastUpdate)
    const date = formatDate(surface.meta.lastUpdate)
    if (surface.meta.calibrationTradeCount > 0) {
      return `Last update: ${time} ET`
    }
    return `Prior close: ${date} ${time} ET`
  }, [surface])

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-white">
              Live ATMF Vol Grid
            </h1>
            <p className="text-sm text-slate-400">
              {curveLabel}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <select
              value={preset}
              onChange={(e) =>
                handlePresetChange(e.target.value as CalibrationPresetKey)
              }
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
            >
              <option value="idb_straddles">IDB Straddles</option>
              <option value="all_idb">All IDB</option>
              <option value="custy_and_idb">Custy + IDB</option>
              <option value="straddles_only">Straddles Only</option>
            </select>
            <button
              onClick={() => setConfigOpen((open) => !open)}
              className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:border-slate-500"
            >
              Configure
            </button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            {MODE_OPTIONS.map((option) => (
              <button
                key={option.key}
                onClick={() => setMode(option.key)}
                className={`rounded-full px-4 py-1 text-xs font-semibold uppercase tracking-wide ${
                  mode === option.key
                    ? 'bg-amber-400 text-slate-900'
                    : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="text-xs text-slate-400">
            {lastUpdateLabel}
          </div>
          {loading && <div className="text-xs text-slate-500">Refreshing...</div>}
          {error && <div className="text-xs text-rose-400">{error}</div>}
        </div>

        {surface?.meta.calibrationTradeCount === 0 && (
          <div className="mt-2 text-xs text-slate-500">
            No trades today - showing prior close surface.
          </div>
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
                      onChange={(e) =>
                        setConfigDraft({
                          ...configDraft,
                          platforms: {
                            ...configDraft.platforms,
                            idb: e.target.checked
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
                      onChange={(e) =>
                        setConfigDraft({
                          ...configDraft,
                          platforms: {
                            ...configDraft.platforms,
                            custy: e.target.checked
                          }
                        })
                      }
                    />
                    Custy
                  </label>
                </div>
                <input
                  value={specificPlatforms}
                  onChange={(e) => setSpecificPlatforms(e.target.value)}
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
                        onChange={(e) =>
                          setConfigDraft({
                            ...configDraft,
                            packageTypes: {
                              ...configDraft.packageTypes,
                              [key]: e.target.checked
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
                  Actions
                  <div className="mt-2 flex flex-wrap gap-3 text-sm">
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={configDraft.actions.newTrade}
                        onChange={(e) =>
                          setConfigDraft({
                            ...configDraft,
                            actions: {
                              ...configDraft.actions,
                              newTrade: e.target.checked
                            }
                          })
                        }
                      />
                      New trade
                    </label>
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={configDraft.actions.amendment}
                        onChange={(e) =>
                          setConfigDraft({
                            ...configDraft,
                            actions: {
                              ...configDraft.actions,
                              amendment: e.target.checked
                            }
                          })
                        }
                      />
                      Amendment
                    </label>
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={configDraft.actions.termination}
                        onChange={(e) =>
                          setConfigDraft({
                            ...configDraft,
                            actions: {
                              ...configDraft.actions,
                              termination: e.target.checked
                            }
                          })
                        }
                      />
                      Termination
                    </label>
                  </div>
                </label>
                <label className="text-xs text-slate-400">
                  ATMF Only
                  <div className="mt-2 flex items-center gap-3 text-sm">
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={configDraft.requireATMF}
                        onChange={(e) =>
                          setConfigDraft({
                            ...configDraft,
                            requireATMF: e.target.checked
                          })
                        }
                      />
                      Require ATMF
                    </label>
                  </div>
                  <input
                    type="number"
                    value={configDraft.maxStrikeOffsetBps ?? ''}
                    onChange={(e) =>
                      setConfigDraft({
                        ...configDraft,
                        maxStrikeOffsetBps: e.target.value
                          ? Number(e.target.value)
                          : null
                      })
                    }
                    placeholder="Max strike offset (bps)"
                    className="mt-2 w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200"
                  />
                </label>
              <label className="text-xs text-slate-400">
                Min Notional
                <input
                  type="number"
                  value={configDraft.minimumNotional ?? ''}
                  onChange={(e) =>
                    setConfigDraft({
                      ...configDraft,
                      minimumNotional: e.target.value
                        ? Number(e.target.value)
                        : null
                    })
                  }
                  className="mt-2 w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200"
                />
              </label>
              <label className="text-xs text-slate-400">
                Max Notional
                <input
                  type="number"
                  value={configDraft.maximumNotional ?? ''}
                  onChange={(e) =>
                    setConfigDraft({
                      ...configDraft,
                      maximumNotional: e.target.value
                        ? Number(e.target.value)
                        : null
                    })
                  }
                  className="mt-2 w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200"
                />
              </label>
              <label className="text-xs text-slate-400">
                Observation Half-life (min)
                <input
                  type="number"
                  value={configDraft.observationHalfLife}
                  onChange={(e) =>
                    setConfigDraft({
                      ...configDraft,
                      observationHalfLife: Number(e.target.value)
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
                  onChange={(e) =>
                    setConfigDraft({
                      ...configDraft,
                      maxStalenessMinutes: Number(e.target.value)
                    })
                  }
                  className="mt-2 w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200"
                />
              </label>
              <label className="text-xs text-slate-400">
                Propagation Length Scale
                <input
                  type="number"
                  step="0.1"
                  value={configDraft.propagationLengthScale}
                  onChange={(e) =>
                    setConfigDraft({
                      ...configDraft,
                      propagationLengthScale: Number(e.target.value)
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
                  onChange={(e) =>
                    setConfigDraft({
                      ...configDraft,
                      tenorWeight: Number(e.target.value)
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
                  onChange={(e) =>
                    setConfigDraft({
                      ...configDraft,
                      expiryWeight: Number(e.target.value)
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
              gridTemplateColumns: `120px repeat(${GRID_DEFINITION.tenors.length}, minmax(70px, 1fr))`
            }}
          >
            <div className="bg-slate-900 p-2 text-xs uppercase text-slate-400">Expiry \ Tenor</div>
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
                  const cell = gridCells.find(
                    (entry) => entry.expiry === expiry && entry.tenor === tenor
                  )
                  if (!cell) {
                    return (
                      <div
                        key={`${expiry}-${tenor}`}
                        className="bg-slate-900/40 p-2 text-center text-xs text-slate-500"
                      >
                        --
                      </div>
                    )
                  }

                  const value =
                    mode === 'premium'
                      ? cell.atmfPremiumBps
                      : mode === 'change'
                        ? cell.atmfVolChange
                        : mode === 'staleness'
                          ? cell.staleness
                          : cell.atmfVol

                  const background =
                    mode === 'change'
                      ? getChangeColor(value ?? 0, viewStats.maxAbsChange)
                      : mode === 'staleness'
                        ? STALENESS_COLORS[cell.stalenessCategory]
                        : getHeatColor(value ?? 0, viewStats.min, viewStats.max)

                  const dotColor = STALENESS_COLORS[cell.stalenessCategory]
                  const changeLabel = formatChange(cell.atmfVolChange)
                  const isFresh =
                    cell.atmfVolSource === 'direct_observation' &&
                    cell.staleness !== null &&
                    cell.staleness <= 5

                  const tooltip = [
                    `${cell.expiry}x${cell.tenor}`,
                    `ATMF Vol: ${formatNumber(cell.atmfVol, 1)} bpvol/yr`,
                    `Change: ${formatChange(cell.atmfVolChange)} from prior`,
                    `Premium: ${formatPremiumBps(cell.atmfPremiumBps)}`,
                    cell.atmfPremium !== null
                      ? `Premium $: ${(cell.atmfPremium / 1_000_000).toFixed(2)}mm`
                      : 'Premium $: --',
                    `Source: ${cell.atmfVolSource}`,
                    `Last print: ${formatTime(cell.atmfVolChangeTime)} ET`,
                    `Observations: ${cell.observationCount}`,
                    `Confidence: ${cell.atmfVolConfidence.toFixed(2)}`,
                    `Quadrant: ${cell.quadrant}`
                  ].join('\n')

                  return (
                    <div
                      key={`${expiry}-${tenor}`}
                      title={tooltip}
                      className={`relative min-h-[56px] p-2 text-center text-xs text-white ${
                        isFresh ? 'ring-2 ring-amber-300 animate-pulse' : ''
                      }`}
                      style={{ backgroundColor: background }}
                    >
                      <div className="text-sm font-semibold">
                        {mode === 'premium'
                          ? formatPremiumBps(cell.atmfPremiumBps)
                          : mode === 'change'
                            ? formatChange(cell.atmfVolChange)
                            : mode === 'staleness'
                              ? formatStaleness(cell.staleness)
                              : formatNumber(cell.atmfVol, 1)}
                      </div>
                      <div className="flex items-center justify-center gap-2 text-[10px] text-slate-200">
                        <span>{changeLabel}</span>
                        <span
                          className="inline-block h-2 w-2 rounded-full"
                          style={{ backgroundColor: dotColor }}
                        />
                      </div>
                    </div>
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
            <span className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-slate-600" /> no data
            </span>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
          <h2 className="text-sm font-semibold text-slate-200">
            Calibration Feed
          </h2>
          <div className="mt-2 space-y-2 text-xs text-slate-300">
            {feed.length === 0 && (
              <div className="text-slate-500">No calibration trades yet.</div>
            )}
            {feed.slice(0, 12).map((trade) => (
              <div
                key={`${trade.packageId}-${trade.executionTimestamp}`}
                className="flex items-center justify-between gap-2 rounded-md bg-slate-900/60 p-2"
              >
                <div>
                  <div className="font-semibold text-slate-200">
                    {formatTime(trade.executionTimestamp)} {trade.tradeLabel}
                  </div>
                  <div className="text-[11px] text-slate-400">
                    {trade.packageType} - {trade.platform ?? '--'} - {formatNotional(trade.notional)}
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
  )
}
