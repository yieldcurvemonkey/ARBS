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
  opts: { signed?: boolean; signNegativeOnly?: boolean } = {},
): string {
  if (isNullish(n)) return EMPTY_VALUE
  const value = Number(n)
  const abs = Math.abs(value)
  const formatted = formatNotional(abs, { compact: true })
  if (opts.signNegativeOnly) {
    if (value < 0) return `\u2212${formatted}`
    return formatted
  }
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

export function formatDate(ts: string | null | undefined): string {
  if (!ts) return EMPTY_VALUE
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return EMPTY_VALUE
  return d.toLocaleDateString('en-US')
}

// All tape timestamps are rendered in the NYC trading-desk timezone, regardless
// of the viewer's browser locale, to match how desk traders read the tape.
const NYC_TIMEZONE = 'America/New_York'

export function formatExecutionWindow(
  start: string | null | undefined,
  end: string | null | undefined,
): string {
  if (!start) return EMPTY_VALUE
  const startDate = new Date(start)
  if (Number.isNaN(startDate.getTime())) return EMPTY_VALUE
  const endDate = end ? new Date(end) : startDate
  if (Number.isNaN(endDate.getTime())) return EMPTY_VALUE
  const startStr = `${startDate.toLocaleDateString('en-US', {
    timeZone: NYC_TIMEZONE,
  })} ${startDate.toLocaleTimeString('en-US', {
    timeZone: NYC_TIMEZONE,
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })}`
  const endStr = endDate.toLocaleTimeString('en-US', {
    timeZone: NYC_TIMEZONE,
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
  if (startDate.getTime() === endDate.getTime()) return startStr
  return `${startStr} / ${endStr}`
}

export function formatClusterSuffix(size: number | null | undefined): string {
  if (isNullish(size)) return ''
  if (size < 2) return ''
  return ` (+${size - 1})`
}

// Compact, signed, lowercase-suffix formatter for OPA / PTP cells. Distinct
// from formatNotional which uses uppercase suffixes and a >=1K threshold —
// trader readout here needs "2.1k" for -2100, not "-2,100".
function formatSignedCompact(n: number): string {
  const sign = n < 0 ? '-' : ''
  const abs = Math.abs(n)
  if (abs >= 1e9) {
    const scaled = abs / 1e9
    const precision = scaled >= 100 ? 0 : 1
    return `${sign}${scaled.toFixed(precision)}b`
  }
  if (abs >= 1e6) {
    const scaled = abs / 1e6
    const precision = scaled >= 100 ? 0 : 1
    return `${sign}${scaled.toFixed(precision)}m`
  }
  const scaled = abs / 1e3
  const precision = scaled >= 100 ? 1 : 1
  return `${sign}${scaled.toFixed(precision)}k`
}

export function formatOtherLvl(input: {
  legOpa: Array<number | null | undefined>
  ptp: number | null | undefined
  opaCurrency?: Array<string | null | undefined>
  ptpCurrency?: string | null | undefined
}): { opaLine: string; ptpLine: string } {
  const opaParts: string[] = []
  input.legOpa.forEach((v, i) => {
    if (v === null || v === undefined || Number.isNaN(v)) return
    const ccy = input.opaCurrency?.[i]
    const formatted = formatSignedCompact(Number(v))
    opaParts.push(ccy && ccy !== 'USD' ? `${formatted} ${ccy}` : formatted)
  })
  const opaLine = opaParts.length ? `OPA: ${opaParts.join(', ')}` : `OPA: ${EMPTY_VALUE}`

  let ptpLine: string
  if (input.ptp === null || input.ptp === undefined || Number.isNaN(input.ptp)) {
    ptpLine = `PTP: ${EMPTY_VALUE}`
  } else {
    const formatted = formatSignedCompact(Number(input.ptp))
    ptpLine =
      input.ptpCurrency && input.ptpCurrency !== 'USD'
        ? `PTP: ${formatted} ${input.ptpCurrency}`
        : `PTP: ${formatted}`
  }

  return { opaLine, ptpLine }
}
