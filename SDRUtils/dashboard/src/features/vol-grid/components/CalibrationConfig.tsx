// ABOUTME: Calibration configuration panel with preset selector and parameter controls.
'use client'

import { useState, useCallback } from 'react'
import {
  CalibrationFilterConfig,
  CALIBRATION_PRESETS,
  PropagationConfig,
  DEFAULT_PROPAGATION_CONFIG,
} from '../types'

type Props = {
  currentPreset: string
  propagationConfig: PropagationConfig
  onPresetChange: (name: string) => void
  onPropagationChange: (config: Partial<PropagationConfig>) => void
  isOpen: boolean
  onToggle: () => void
}

export function CalibrationConfig({
  currentPreset,
  propagationConfig,
  onPresetChange,
  onPropagationChange,
  isOpen,
  onToggle,
}: Props) {
  const preset = CALIBRATION_PRESETS[currentPreset]

  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full px-3 py-2 flex items-center justify-between hover:bg-slate-800/30 transition-colors"
      >
        <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wide">
          Calibration Settings
        </h3>
        <span className="text-[10px] text-slate-500">{isOpen ? '\u25B2' : '\u25BC'}</span>
      </button>

      {isOpen && (
        <div className="px-3 pb-3 space-y-3 border-t border-slate-800">
          {/* Preset selector */}
          <div className="pt-2">
            <label className="block text-[10px] text-slate-500 uppercase mb-1">Preset</label>
            <select
              value={currentPreset}
              onChange={(e) => onPresetChange(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {Object.keys(CALIBRATION_PRESETS).map(name => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </div>

          {/* Active filter summary */}
          {preset && (
            <div className="text-[10px] text-slate-400 space-y-0.5">
              <div>
                Platforms: {preset.platforms.idb ? 'IDB' : ''}{preset.platforms.idb && preset.platforms.custy ? ' + ' : ''}{preset.platforms.custy ? 'Custy' : ''}
              </div>
              <div>
                Structures: {Object.entries(preset.packageTypes).filter(([, v]) => v).map(([k]) => k).join(', ')}
              </div>
              <div>
                Min notional: {preset.minimumNotional ? `${(preset.minimumNotional / 1e6).toFixed(0)}mm` : 'none'}
              </div>
              <div>
                Actions: {Object.entries(preset.actions).filter(([, v]) => v).map(([k]) => k).join(', ')}
              </div>
            </div>
          )}

          <div className="border-t border-slate-700/50 pt-2">
            <label className="block text-[10px] text-slate-500 uppercase mb-1.5">Propagation</label>
            <div className="space-y-2">
              <SliderRow
                label="Length scale"
                value={propagationConfig.lengthScale}
                min={0.1}
                max={2.0}
                step={0.1}
                onChange={(v) => onPropagationChange({ lengthScale: v })}
              />
              <SliderRow
                label="Tenor weight"
                value={propagationConfig.tenorWeight}
                min={0.1}
                max={2.0}
                step={0.1}
                onChange={(v) => onPropagationChange({ tenorWeight: v })}
              />
              <SliderRow
                label="Expiry weight"
                value={propagationConfig.expiryWeight}
                min={0.1}
                max={2.0}
                step={0.1}
                onChange={(v) => onPropagationChange({ expiryWeight: v })}
              />
            </div>
          </div>

          <button
            onClick={() => onPropagationChange(DEFAULT_PROPAGATION_CONFIG)}
            className="w-full text-[10px] text-slate-500 hover:text-slate-300 py-1 transition-colors"
          >
            Reset to defaults
          </button>
        </div>
      )}
    </div>
  )
}

function SliderRow({ label, value, min, max, step, onChange }: {
  label: string
  value: number
  min: number
  max: number
  step: number
  onChange: (v: number) => void
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-slate-500 w-20 shrink-0">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="flex-1 h-1 accent-blue-500 bg-slate-700 rounded-lg appearance-none cursor-pointer"
      />
      <span className="text-[10px] text-slate-300 w-8 text-right font-mono">{value.toFixed(1)}</span>
    </div>
  )
}
