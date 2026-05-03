import type {
  ExtremeRow,
  LevelsPlatformFilter,
  LevelsScopeFilter,
  LevelsSortKey,
  PlatformKind,
  RecentSimilarRow,
} from './analytics-types'

function platformMatches(platform: PlatformKind, filter: LevelsPlatformFilter): boolean {
  if (filter === 'all') return true
  return platform.toLowerCase() === filter
}

function scopeMatches(scope: ExtremeRow['scope'], filter: LevelsScopeFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'all-time') return scope === 'All-time'
  if (filter === '52w') return scope === '52 weeks'
  return scope === '30 days'
}

function scopePriority(scope: ExtremeRow['scope']): number {
  if (scope === '30 days') return 0
  if (scope === '52 weeks') return 1
  return 2
}

function labelPriority(label: string): number {
  const normalized = label.toLowerCase()
  if (normalized.includes('largest dv01')) return 0
  if (normalized.includes('largest notional')) return 1
  return 2
}

export function parsePositiveNumberInput(value: string, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

export function formatSignedBpsDelta(delta: number): string {
  if (!Number.isFinite(delta)) return '-'
  if (delta === 0) return '0.0'
  return `${delta > 0 ? '+' : '-'}${Math.abs(delta).toFixed(1)}`
}

export function filterAndSortExtremes(
  rows: ExtremeRow[],
  opts: {
    platform: LevelsPlatformFilter
    scope: LevelsScopeFilter
    sortBy: LevelsSortKey
    focusedRate: number
  },
): ExtremeRow[] {
  const filtered = rows.filter(
    (row) => platformMatches(row.platform, opts.platform) && scopeMatches(row.scope, opts.scope),
  )
  return [...filtered].sort((a, b) => {
    if (opts.sortBy === 'closest') {
      return Math.abs(a.rate - opts.focusedRate) - Math.abs(b.rate - opts.focusedRate)
    }
    if (opts.sortBy === 'rate') return b.rate - a.rate
    if (opts.sortBy === 'dv01') return b.dv01 - a.dv01
    if (opts.sortBy === 'notional') return b.notional - a.notional
    if (opts.sortBy === 'time') {
      return new Date(b.ts).getTime() - new Date(a.ts).getTime()
    }
    return (
      scopePriority(a.scope) - scopePriority(b.scope) ||
      labelPriority(a.label) - labelPriority(b.label) ||
      Math.abs(a.rate - opts.focusedRate) - Math.abs(b.rate - opts.focusedRate)
    )
  })
}

export function filterAndSortRecentSimilar(
  rows: RecentSimilarRow[],
  opts: {
    platform: LevelsPlatformFilter
    sortBy: 'newest' | 'closest' | 'largest'
    focusedRate: number
  },
): RecentSimilarRow[] {
  const filtered = rows.filter((row) => platformMatches(row.platform, opts.platform))
  return [...filtered].sort((a, b) => {
    if (opts.sortBy === 'closest') {
      return Math.abs(a.rate - opts.focusedRate) - Math.abs(b.rate - opts.focusedRate)
    }
    if (opts.sortBy === 'largest') {
      return b.dv01 - a.dv01 || b.notional - a.notional
    }
    return a.daysAgo - b.daysAgo
  })
}

export type RecentLevelSummary = {
  count: number
  vwap: number | null
  low: number | null
  high: number | null
  totalDv01: number
  totalNotional: number
  idbCount: number
  custyCount: number
  latestDate: string | null
  focusDelta: number | null
}

export function summarizeRecentLevels(
  rows: RecentSimilarRow[],
  focusedRate: number,
): RecentLevelSummary {
  if (rows.length === 0) {
    return {
      count: 0,
      vwap: null,
      low: null,
      high: null,
      totalDv01: 0,
      totalNotional: 0,
      idbCount: 0,
      custyCount: 0,
      latestDate: null,
      focusDelta: null,
    }
  }
  const totalDv01 = rows.reduce((sum, row) => sum + Math.abs(row.dv01), 0)
  const totalNotional = rows.reduce((sum, row) => sum + Math.abs(row.notional), 0)
  const weightedRate = totalDv01 > 0
    ? rows.reduce((sum, row) => sum + row.rate * Math.abs(row.dv01), 0) / totalDv01
    : rows.reduce((sum, row) => sum + row.rate, 0) / rows.length
  const rates = rows.map((row) => row.rate)
  const latest = [...rows].sort((a, b) => a.daysAgo - b.daysAgo)[0]
  return {
    count: rows.length,
    vwap: weightedRate,
    low: Math.min(...rates),
    high: Math.max(...rates),
    totalDv01,
    totalNotional,
    idbCount: rows.filter((row) => row.platform === 'IDB').length,
    custyCount: rows.filter((row) => row.platform === 'CUSTY').length,
    latestDate: latest.date,
    focusDelta: focusedRate - weightedRate,
  }
}
