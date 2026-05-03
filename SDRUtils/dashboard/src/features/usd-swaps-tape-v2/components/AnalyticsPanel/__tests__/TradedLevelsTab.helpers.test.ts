import { describe, expect, it } from '@jest/globals'
import type { ExtremeRow, RecentSimilarRow } from '../analytics-types'
import {
  filterAndSortExtremes,
  filterAndSortRecentSimilar,
  formatSignedBpsDelta,
  parsePositiveNumberInput,
  summarizeRecentLevels,
} from '../TradedLevelsTab.helpers'

const extremes: ExtremeRow[] = [
  {
    label: 'All-time largest DV01',
    scope: 'All-time',
    rate: 390,
    dv01: 100_000,
    notional: 200_000_000,
    ts: '2025-01-01T10:00:00Z',
    venue: 'ISWV',
    platform: 'IDB',
  },
  {
    label: '30d high rate',
    scope: '30 days',
    rate: 388,
    dv01: 20_000,
    notional: 50_000_000,
    ts: '2026-04-20T10:00:00Z',
    venue: 'BBSF',
    platform: 'CUSTY',
  },
]

const recent: RecentSimilarRow[] = [
  { daysAgo: 3, date: '2026-04-20', rate: 388, dv01: 20_000, notional: 50_000_000, platform: 'CUSTY', venue: 'BBSF' },
  { daysAgo: 1, date: '2026-04-22', rate: 386, dv01: 60_000, notional: 150_000_000, platform: 'IDB', venue: 'ISWV' },
]

describe('TradedLevelsTab helpers', () => {
  it('parses positive number inputs with a fallback', () => {
    expect(parsePositiveNumberInput('2.5', 1)).toBe(2.5)
    expect(parsePositiveNumberInput('', 1)).toBe(1)
    expect(parsePositiveNumberInput('-1', 1)).toBe(1)
  })

  it('sorts relevance toward recent market-making levels', () => {
    const sorted = filterAndSortExtremes(extremes, {
      platform: 'all',
      scope: 'all',
      sortBy: 'relevance',
      focusedRate: 387,
    })

    expect(sorted[0].label).toBe('30d high rate')
  })

  it('filters recent similar trades by platform and sorts by size', () => {
    const sorted = filterAndSortRecentSimilar(recent, {
      platform: 'idb',
      sortBy: 'largest',
      focusedRate: 387,
    })

    expect(sorted).toHaveLength(1)
    expect(sorted[0].platform).toBe('IDB')
  })

  it('summarizes recent levels with DV01-weighted average', () => {
    const summary = summarizeRecentLevels(recent, 387)

    expect(summary.count).toBe(2)
    expect(summary.vwap).toBeCloseTo(386.5, 6)
    expect(summary.focusDelta).toBeCloseTo(0.5, 6)
    expect(summary.idbCount).toBe(1)
    expect(summary.custyCount).toBe(1)
  })

  it('formats signed bps deltas', () => {
    expect(formatSignedBpsDelta(1.25)).toBe('+1.3')
    expect(formatSignedBpsDelta(-1.25)).toBe('-1.3')
  })
})
