import type { ListedVolDisplayMode } from './types'

export function formatVol(value: number | null, digits = 1) {
  if (value === null || !Number.isFinite(value)) return '--'
  return value.toFixed(digits)
}

export function formatSigned(value: number | null, digits = 1) {
  if (value === null || !Number.isFinite(value)) return '--'
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}${Math.abs(value).toFixed(digits)}`
}

export function formatRatio(value: number | null, digits = 2) {
  if (value === null || !Number.isFinite(value)) return '--'
  return value.toFixed(digits)
}

export function formatPercentile(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '--'
  return `${Math.round(value)}%`
}

export function getZScoreTone(value: number | null) {
  if (value === null || !Number.isFinite(value)) return 'text-slate-300'
  if (value >= 1.5) return 'text-rose-300'
  if (value >= 0.5) return 'text-amber-300'
  if (value <= -1.5) return 'text-sky-300'
  if (value <= -0.5) return 'text-cyan-300'
  return 'text-slate-200'
}

export function getDisplayLabel(mode: ListedVolDisplayMode) {
  if (mode === 'dchg') return 'dChg'
  if (mode === 'zscore') return 'Z'
  return 'Vol'
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

export function interpolateHeatmap(value: number | null, maxAbs = 2.5) {
  if (value === null || !Number.isFinite(value)) {
    return 'rgba(15, 23, 42, 0.78)'
  }
  const ratio = clamp(Math.abs(value) / Math.max(maxAbs, 0.25), 0, 1)
  if (value >= 0) {
    return `rgba(${Math.round(120 + 100 * ratio)}, ${Math.round(45 + 30 * (1 - ratio))}, ${Math.round(45 + 35 * (1 - ratio))}, 0.94)`
  }
  return `rgba(${Math.round(28 + 20 * (1 - ratio))}, ${Math.round(96 + 70 * ratio)}, ${Math.round(180 + 50 * ratio)}, 0.94)`
}
