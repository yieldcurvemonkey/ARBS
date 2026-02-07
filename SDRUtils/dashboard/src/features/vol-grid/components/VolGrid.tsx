// ABOUTME: Main VolGrid component that orchestrates the heatmap, controls, calibration feed, and config.
'use client'

import { useState, useCallback } from 'react'
import {
  ViewMode,
  PropagationConfig,
  DEFAULT_PROPAGATION_CONFIG,
  VolGridCell,
} from '../types'
import { useVolGridData } from '../hooks/useVolGridData'
import { VolGridHeatmap } from './VolGridHeatmap'
import { CalibrationFeed } from './CalibrationFeed'
import { CalibrationConfig } from './CalibrationConfig'

const VIEW_MODES: { key: ViewMode; label: string; description: string }[] = [
  { key: 'vol', label: 'VOL', description: 'ATMF vol in bpvol/yr' },
  { key: 'premium', label: 'PREMIUM', description: 'Straddle premium per 100mm' },
  { key: 'change', label: 'CHANGE', description: 'Vol change from prior' },
  { key: 'staleness', label: 'STALENESS', description: 'Minutes since last observation' },
]

export function VolGrid() {
  const [viewMode, setViewMode] = useState<ViewMode>('vol')
  const [presetName, setPresetName] = useState('IDB Straddles')
  const [propagationConfig, setPropagationConfig] = useState<PropagationConfig>(DEFAULT_PROPAGATION_CONFIG)
  const [configOpen, setConfigOpen] = useState(false)
  const [pollEnabled, setPollEnabled] = useState(true)
  const [selectedCell, setSelectedCell] = useState<VolGridCell | null>(null)

  const { gridState, calibrationTrades, isLoading, error, lastFetchTime, refetch } = useVolGridData({
    presetName,
    includePremium: viewMode === 'premium',
    pollEnabled,
    lengthScale: propagationConfig.lengthScale,
    expiryWeight: propagationConfig.expiryWeight,
    tenorWeight: propagationConfig.tenorWeight,
  })

  const handlePresetChange = useCallback((name: string) => {
    setPresetName(name)
  }, [])

  const handlePropagationChange = useCallback((partial: Partial<PropagationConfig>) => {
    setPropagationConfig(prev => ({ ...prev, ...partial }))
  }, [])

  const handleCellClick = useCallback((cell: VolGridCell) => {
    setSelectedCell(prev => (prev?.expiry === cell.expiry && prev?.tenor === cell.tenor) ? null : cell)
  }, [])

  const lastUpdateStr = lastFetchTime
    ? new Date(lastFetchTime).toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        timeZone: 'America/New_York',
      }) + ' ET'
    : '—'

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-white tracking-tight">
            Live ATMF Vol Grid
          </h2>
          <span className="text-xs text-slate-500">
            Calibration: {presetName}
          </span>
          {gridState?.curveInfo && (
            <span className="text-xs text-slate-500">
              Curve: {gridState.curveInfo.source} {gridState.curveInfo.timestamp}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Polling toggle */}
          <button
            onClick={() => setPollEnabled(p => !p)}
            className={`px-2 py-1 text-[10px] rounded border transition-colors ${
              pollEnabled
                ? 'border-green-700 bg-green-900/30 text-green-400'
                : 'border-slate-700 bg-slate-800/50 text-slate-500'
            }`}
          >
            {pollEnabled ? 'LIVE' : 'PAUSED'}
          </button>

          {/* Refresh */}
          <button
            onClick={refetch}
            className="px-2 py-1 text-[10px] text-slate-400 hover:text-white rounded border border-slate-700 hover:border-slate-600 transition-colors"
          >
            Refresh
          </button>

          <span className="text-[10px] text-slate-600">
            Last: {lastUpdateStr}
          </span>
        </div>
      </div>

      {/* View mode toggle */}
      <div className="flex items-center gap-1">
        {VIEW_MODES.map(mode => (
          <button
            key={mode.key}
            onClick={() => setViewMode(mode.key)}
            className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
              viewMode === mode.key
                ? 'bg-blue-600 text-white'
                : 'bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700'
            }`}
            title={mode.description}
          >
            {mode.label}
          </button>
        ))}

        {/* Legend */}
        <div className="ml-4 flex items-center gap-3 text-[10px] text-slate-500">
          <span className="flex items-center gap-1"><span className="text-green-400">{'\u25CF'}</span> live (&lt;15m)</span>
          <span className="flex items-center gap-1"><span className="text-emerald-500">{'\u25CF'}</span> recent (&lt;1h)</span>
          <span className="flex items-center gap-1"><span className="text-amber-500">{'\u25CF'}</span> stale (&lt;4h)</span>
          <span className="flex items-center gap-1"><span className="text-red-500">{'\u25CF'}</span> very stale</span>
          <span className="flex items-center gap-1"><span className="text-slate-600">{'\u25CB'}</span> no data</span>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="bg-red-900/20 border border-red-800 rounded-lg px-3 py-2 text-xs text-red-400">
          {error}
        </div>
      )}

      {/* Loading state */}
      {isLoading && !gridState && (
        <div className="flex items-center justify-center py-20">
          <div className="text-sm text-slate-500">Loading vol surface...</div>
        </div>
      )}

      {/* Main content */}
      {gridState && (
        <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-4">
          {/* Heatmap grid */}
          <div>
            <VolGridHeatmap
              gridState={gridState}
              viewMode={viewMode}
              onCellClick={handleCellClick}
            />

            {/* Grid summary */}
            <div className="mt-2 flex items-center gap-4 text-[10px] text-slate-500">
              <span>{gridState.calibrationTradeCount} calibration trades</span>
              <span>{gridState.filteredOutCount} filtered out</span>
              <span>Prior: {gridState.priorSource}</span>
              {gridState.curveInfo && (
                <span>Curve: {gridState.curveInfo.source} {gridState.curveInfo.timestamp}</span>
              )}
            </div>

            {/* Selected cell detail */}
            {selectedCell && (
              <div className="mt-3 bg-slate-900/70 border border-slate-800 rounded-lg p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-semibold text-white">
                    {selectedCell.expiry}x{selectedCell.tenor}
                  </span>
                  <button
                    onClick={() => setSelectedCell(null)}
                    className="text-slate-500 hover:text-white text-xs"
                  >
                    Close
                  </button>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                  <Stat label="Vol" value={selectedCell.atmfVol !== null ? `${selectedCell.atmfVol.toFixed(1)} bp` : '—'} />
                  <Stat label="Change" value={selectedCell.atmfVolChange !== null ? `${selectedCell.atmfVolChange >= 0 ? '+' : ''}${selectedCell.atmfVolChange.toFixed(1)} bp` : '—'} />
                  <Stat label="Premium" value={selectedCell.atmfPremiumBps !== null ? `${selectedCell.atmfPremiumBps.toFixed(1)} bps` : '—'} />
                  <Stat label="Source" value={selectedCell.atmfVolSource} />
                  <Stat label="Confidence" value={selectedCell.atmfVolConfidence.toFixed(2)} />
                  <Stat label="Obs today" value={String(selectedCell.observationCount)} />
                  <Stat label="Staleness" value={selectedCell.stalenessCategory} />
                  <Stat label="Quadrant" value={selectedCell.quadrant} />
                </div>
              </div>
            )}
          </div>

          {/* Right sidebar: Calibration feed + config */}
          <div className="space-y-4">
            <CalibrationConfig
              currentPreset={presetName}
              propagationConfig={propagationConfig}
              onPresetChange={handlePresetChange}
              onPropagationChange={handlePropagationChange}
              isOpen={configOpen}
              onToggle={() => setConfigOpen(o => !o)}
            />
            <CalibrationFeed
              trades={calibrationTrades}
              filteredOutCount={gridState.filteredOutCount}
            />
          </div>
        </div>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] text-slate-500 uppercase">{label}</div>
      <div className="text-slate-200 font-mono">{value}</div>
    </div>
  )
}
