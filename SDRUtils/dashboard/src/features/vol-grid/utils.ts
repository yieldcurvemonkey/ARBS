import { EXPIRY_POINTS, TENOR_POINTS } from './constants'

export function normalizeDateKey(value: string | Date | null | undefined): string | null {
  if (value === null || value === undefined) return null
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.toISOString().slice(0, 10)
  }

  const text = String(value).trim()
  if (!text) return null
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return text
  }

  const parsed = new Date(text)
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString().slice(0, 10)
}

export function parseTenorLabelToYears(label: string | null | undefined): number | null {
  if (!label) return null
  const match = String(label).trim().toUpperCase().match(/^(\d+(?:\.\d+)?)([DWMY])$/)
  if (!match) return null
  const value = Number(match[1])
  if (!Number.isFinite(value)) return null
  const unit = match[2]
  switch (unit) {
    case 'D':
      return value / 365
    case 'W':
      return value / 52
    case 'M':
      return value / 12
    case 'Y':
      return value
    default:
      return null
  }
}

export function resolveGridIndex(
  expiryYears: number,
  tenorYears: number
): { expiryIndex: number; tenorIndex: number } | null {
  const expiryIndex = EXPIRY_POINTS.findIndex(
    (point) => point.years === expiryYears
  )
  const tenorIndex = TENOR_POINTS.findIndex(
    (point) => point.years === tenorYears
  )
  if (expiryIndex < 0 || tenorIndex < 0) return null
  return { expiryIndex, tenorIndex }
}

export function formatLabel(expiry: string, tenor: string) {
  return `${expiry}x${tenor}`
}

export function normalizeGridLabel(label: string | null | undefined) {
  return String(label ?? '').trim().toLowerCase()
}

export function buildNodeKey(expiry: string, tenor: string) {
  return `${normalizeGridLabel(expiry)}_${normalizeGridLabel(tenor)}`
}

export function toEasternDateKey(value: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(value)
}

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

// ── Formatting utilities ──

export function formatNumber(value: number | null, digits = 1) {
  if (value === null || !Number.isFinite(value)) return '--'
  return value.toFixed(digits)
}

export function formatChange(value: number | null, digits = 1) {
  if (value === null || !Number.isFinite(value)) return '--'
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}${Math.abs(value).toFixed(digits)}`
}

export function formatPremiumBps(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '--'
  return `${value.toFixed(2)} bp`
}

export function formatNotional(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '--'
  return `${(Math.abs(value) / 1_000_000).toFixed(0)}mm`
}

export function formatTime(value: number | null) {
  if (!value) return '--'
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(new Date(value))
}

export function formatDate(value: number | null) {
  if (!value) return '--'
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: 'short',
    day: '2-digit'
  }).format(new Date(value))
}

export function formatDateTime(value: number | null) {
  if (!value) return '--'
  return `${formatDate(value)} ${formatTime(value)} ET`
}

export function formatStaleness(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '--'
  if (value < 60) return `${Math.round(value)}m`
  return `${(value / 60).toFixed(1)}h`
}

export function formatConfidence(value: number) {
  if (!Number.isFinite(value)) return '--'
  return `${(value * 100).toFixed(0)}%`
}

export function formatTimestamp(value: number | null) {
  if (!value) return '--'
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date(value))
}

// ── Color utilities ──

export const STALENESS_COLORS: Record<string, string> = {
  live: '#22c55e',
  recent: '#f59e0b',
  stale: '#ef4444',
  very_stale: '#6b7280',
  no_data: '#475569'
}

export function interpolateColor(low: number[], high: number[], t: number) {
  const mix = (a: number, b: number) => Math.round(a + (b - a) * t)
  return `rgb(${mix(low[0], high[0])}, ${mix(low[1], high[1])}, ${mix(low[2], high[2])})`
}

export function getHeatColor(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return 'rgba(15, 23, 42, 0.8)'
  const ratio = max > min ? (value - min) / (max - min) : 0.5
  return interpolateColor([30, 64, 175], [245, 158, 11], clamp(ratio, 0, 1))
}

export function getChangeColor(value: number, maxAbs: number) {
  if (!Number.isFinite(value)) return 'rgba(15, 23, 42, 0.8)'
  const ratio = maxAbs > 0 ? Math.abs(value) / maxAbs : 0
  const base = value >= 0 ? [239, 68, 68] : [34, 197, 94]
  return interpolateColor([30, 41, 59], base, clamp(ratio, 0, 1))
}

export function getConfidenceColor(value: number) {
  if (!Number.isFinite(value)) return 'rgba(15, 23, 42, 0.8)'
  return interpolateColor([30, 41, 59], [14, 165, 233], clamp(value / 100, 0, 1))
}

export function getUnifiedCellBackground(value: number | null, min: number, max: number) {
  if (value === null || !Number.isFinite(value)) return 'rgba(15, 23, 42, 0.6)'
  const ratio = max > min ? (value - min) / (max - min) : 0.5
  const t = clamp(ratio, 0, 1)
  const r = Math.round(17 + (74 - 17) * t)
  const g = Math.round(24 + (56 - 24) * t)
  const b = Math.round(39 + (32 - 39) * t)
  return `rgba(${r}, ${g}, ${b}, 0.96)`
}
