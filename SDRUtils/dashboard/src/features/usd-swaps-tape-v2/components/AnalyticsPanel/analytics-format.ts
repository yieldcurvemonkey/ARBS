// Small formatters + color tokens that are analytics-dock-specific.
// Wraps the existing feature-level format helpers so callers still go
// through utils/format.ts for row-level rendering.
import { formatDv01, formatNotional } from '../../utils/format'

export const ANALYTICS_COLORS = {
  custy: '#f59e0b',
  custyTint: 'rgba(245, 158, 11, 0.18)',
  custyRing: 'rgba(245, 158, 11, 0.42)',
  idb: '#38bdf8',
  idbTint: 'rgba(56, 189, 248, 0.18)',
  idbRing: 'rgba(56, 189, 248, 0.42)',
  iqr: 'rgba(34, 211, 238, 0.10)',
  iqrRing: 'rgba(34, 211, 238, 0.30)',
  sigma1: 'rgba(56, 189, 248, 0.05)',
  sigma2: 'rgba(56, 189, 248, 0.03)',
  focused: '#e879f9',
  cumulative: '#c084fc',
  grid: '#1e293b',
  axis: '#64748b',
  slate100: '#f1f5f9',
  slate200: '#e2e8f0',
  slate300: '#cbd5e1',
  slate400: '#94a3b8',
  slate500: '#64748b',
  slate700: '#334155',
  slate800: '#1e293b',
  slate900: '#0f172a',
  slate950: '#020617',
} as const

export function fmtBps(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return Number(n).toFixed(digits)
}

// DV01 in USD/bp, compact with K / MM suffix. Delegates to the feature's
// headline-snapping formatter so numbers match the tape column.
export function fmtDv01Compact(
  n: number | null | undefined,
  opts: { signed?: boolean; signNegativeOnly?: boolean } = {},
): string {
  return formatDv01(n, opts)
}

// Notional in USD millions — "173.4" for 173,410,000. No suffix: callers
// pair it with an explicit "MM" unit label so the strip reads cleanly.
export function fmtNotionalMM(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  const mm = Number(n) / 1e6
  return mm >= 100 ? mm.toFixed(0) : mm.toFixed(1)
}

export function fmtCompactUSD(n: number | null | undefined): string {
  return formatNotional(n, { compact: true, headline: false })
}

export function fmtDaysAgo(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  if (n === 0) return 'today'
  if (n === 1) return '1 day ago'
  return `${n} days ago`
}

const NY_TZ = 'America/New_York'

export function fmtTs(
  ts: string | null | undefined,
  opts: { dateOnly?: boolean; timeOnly?: boolean; seconds?: boolean } = {},
): string {
  if (!ts) return '—'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return '—'
  if (opts.dateOnly) {
    return d.toLocaleDateString('en-US', {
      year: 'numeric', month: 'short', day: '2-digit', timeZone: NY_TZ,
    })
  }
  if (opts.timeOnly) {
    return d.toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit',
      second: opts.seconds ? '2-digit' : undefined,
      hour12: false, timeZone: NY_TZ,
    })
  }
  return `${d.toLocaleDateString('en-US', {
    month: 'short', day: '2-digit', timeZone: NY_TZ,
  })} ${d.toLocaleTimeString('en-US', {
    hour: '2-digit', minute: '2-digit', hour12: false, timeZone: NY_TZ,
  })}`
}

export function fmtTickTs(ts: string, viewKey: string): string {
  const d = new Date(ts)
  if (viewKey === 'INTRADAY') {
    return d.toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', hour12: false, timeZone: NY_TZ,
    })
  }
  return d.toLocaleDateString('en-US', {
    month: 'short', day: '2-digit', timeZone: NY_TZ,
  })
}
