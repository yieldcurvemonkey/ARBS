// Number / time / tenor formatters for the USD swap tape v2 UI.
import { EMPTY_VALUE } from '../constants'
import type { UsdSwapTapeRow } from '../types'

const COMPACT_UNITS: [number, string][] = [
  [1e9, 'B'],
  [1e6, 'M'],
  [1e3, 'K'],
]

function isNullish(n: number | null | undefined): n is null | undefined {
  return n === null || n === undefined || Number.isNaN(n)
}

export function formatNotional(
  n: number | null | undefined,
  opts: { compact?: boolean } = {},
): string {
  if (isNullish(n)) return EMPTY_VALUE
  const value = Number(n)
  if (!opts.compact) {
    return value.toLocaleString(undefined, { maximumFractionDigits: 0 })
  }
  for (const [threshold, suffix] of COMPACT_UNITS) {
    if (Math.abs(value) >= threshold) {
      const scaled = value / threshold
      const precision = Math.abs(scaled) >= 100 ? 0 : 1
      const formatted = scaled.toFixed(precision).replace(/\.0+$/, '')
      return `${formatted}${suffix}`
    }
  }
  return value.toFixed(0)
}

export function formatDv01(
  n: number | null | undefined,
  opts: { signed?: boolean } = {},
): string {
  if (isNullish(n)) return EMPTY_VALUE
  const value = Number(n)
  const abs = Math.abs(value)
  const formatted = formatNotional(abs, { compact: true })
  if (!opts.signed) return formatted
  if (value < 0) return `\u2212${formatted}`
  if (value > 0) return `+${formatted}`
  return formatted
}

export function formatRate(
  n: number | null | undefined,
  opts: { precision?: number } = {},
): string {
  if (isNullish(n)) return EMPTY_VALUE
  const value = Number(n)
  const precision = opts.precision ?? 3
  return `${(value * 100).toFixed(precision)}%`
}

export function formatRateRange(
  min: number | null | undefined,
  max: number | null | undefined,
): string {
  if (isNullish(min) && isNullish(max)) return EMPTY_VALUE
  if (isNullish(min)) return formatRate(max)
  if (isNullish(max)) return formatRate(min)
  if (Math.abs(Number(min) - Number(max)) < 1e-9) return formatRate(min)
  return `${formatRate(min)} – ${formatRate(max)}`
}

export function formatTenor(row: UsdSwapTapeRow): string {
  const leg = row.legs_json?.[0]
  return (
    leg?.tenor_display ||
    leg?.tenor_label ||
    row.tenor_label ||
    row.package_tenors ||
    EMPTY_VALUE
  )
}

export function formatTime(ts: string | null | undefined): string {
  if (!ts) return EMPTY_VALUE
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return EMPTY_VALUE
  return d.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export function formatClusterSuffix(size: number | null | undefined): string {
  if (isNullish(size)) return ''
  if (size < 2) return ''
  return ` (+${size - 1})`
}
