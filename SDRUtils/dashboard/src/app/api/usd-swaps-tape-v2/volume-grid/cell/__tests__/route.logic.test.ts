import { describe, expect, it } from '@jest/globals'
import {
  parseVolumeGridCellParams,
  buildTimeseriesSql,
  buildRecentTradesSql,
  rangeToStartDate,
} from '../route.logic'

describe('parseVolumeGridCellParams', () => {
  it('rejects missing fwd', () => {
    const out = parseVolumeGridCellParams(new URLSearchParams('tenor=5y'))
    expect(out.ok).toBe(false)
  })
  it('rejects missing tenor', () => {
    const out = parseVolumeGridCellParams(new URLSearchParams('fwd=spot'))
    expect(out.ok).toBe(false)
  })
  it('applies defaults', () => {
    const out = parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=5y'))
    expect(out.ok).toBe(true)
    if (out.ok) {
      expect(out.value).toMatchObject({ metric: 'notional', range: '3M', recentLimit: 50 })
    }
  })
  it('rejects bogus bucket ids', () => {
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=foo&tenor=5y')).ok).toBe(false)
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=foo')).ok).toBe(false)
  })
  it('clamps recentLimit', () => {
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=5y&recentLimit=0')).ok).toBe(false)
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=5y&recentLimit=999')).ok).toBe(false)
  })
})

describe('rangeToStartDate', () => {
  it('subtracts approximately the right interval', () => {
    const now = new Date('2026-05-05T00:00:00Z')
    const out = rangeToStartDate('1M', now)
    const days = (now.getTime() - out.getTime()) / 86_400_000
    expect(days).toBeGreaterThanOrEqual(28)
    expect(days).toBeLessThanOrEqual(32)
  })
  it('1Y subtracts a year', () => {
    const now = new Date('2026-05-05T00:00:00Z')
    const out = rangeToStartDate('1Y', now)
    expect(out.getUTCFullYear()).toBe(2025)
    expect(out.getUTCMonth()).toBe(4)
  })
})

describe('buildTimeseriesSql / buildRecentTradesSql', () => {
  it('timeseries SQL filters on contributes_to_flow and groups by day', () => {
    const sql = buildTimeseriesSql()
    expect(sql).toContain('contributes_to_flow')
    expect(sql).toContain('GROUP BY day')
  })
  it('recentTrades SQL orders by execution_start DESC and limits', () => {
    const sql = buildRecentTradesSql()
    expect(sql).toContain('ORDER BY')
    expect(sql).toContain('execution_start DESC')
    expect(sql).toContain('LIMIT')
  })
})
