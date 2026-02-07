import { EXPIRY_POINTS, TENOR_POINTS } from './constants'

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
