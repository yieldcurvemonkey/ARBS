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
