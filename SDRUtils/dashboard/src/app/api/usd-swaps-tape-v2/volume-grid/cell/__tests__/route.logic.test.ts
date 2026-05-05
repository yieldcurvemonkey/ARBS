import { describe, expect, it } from '@jest/globals'
import {
  parseVolumeGridCellParams,
  buildTimeseriesSql,
  buildRecentTradesSql,
  rangeToStartDate,
} from '../route.logic'

describe('parseVolumeGridCellParams', () => {
  it('rejects missing fwd', () => {
    expect(parseVolumeGridCellParams(new URLSearchParams('tenor=5y')).ok).toBe(false)
  })
  it('rejects missing tenor', () => {
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=spot')).ok).toBe(false)
  })
  it('applies defaults — outright + default schemas', () => {
    const out = parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=5y'))
    expect(out.ok).toBe(true)
    if (out.ok) {
      expect(out.value).toMatchObject({
        metric: 'notional', range: '3M', recentLimit: 50,
        forwardSchema: 'default', tenorSchema: 'default', packageType: 'outright',
      })
    }
  })
  it('rejects bucket ids absent from the requested schema', () => {
    // 5_10y is a legacy tenor id, not in default schema
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=5_10y')).ok).toBe(false)
    // works under legacy schema
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=5_10y&tenorSchema=legacy')).ok).toBe(true)
  })
  it('rejects bogus packageType', () => {
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=5y&packageType=bogus')).ok).toBe(false)
  })
  it('rejects unknown forwardSchema', () => {
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=5y&forwardSchema=foo')).ok).toBe(false)
  })
})

describe('rangeToStartDate', () => {
  it('1M subtracts ~30 days', () => {
    const now = new Date('2026-05-05T00:00:00Z')
    const out = rangeToStartDate('1M', now)
    const days = (now.getTime() - out.getTime()) / 86_400_000
    expect(days).toBeGreaterThanOrEqual(28)
    expect(days).toBeLessThanOrEqual(32)
  })
})

describe('buildTimeseriesSql', () => {
  it('joins packages and applies bucket + package filters', () => {
    const sql = buildTimeseriesSql({
      bucketPredicateSql: 'l.forward_start_years < 1',
      packageFilterSql: 'p.package_type IN ($2)',
    })
    expect(sql).toContain('JOIN arbs_usd_swap_tape_packages_v2 p ON p.package_id = l.package_id')
    expect(sql).toContain('AND l.forward_start_years < 1')
    expect(sql).toContain('AND p.package_type IN ($2)')
    expect(sql).toContain('GROUP BY day')
  })
})

describe('buildRecentTradesSql', () => {
  it('orders by execution_start DESC and uses the supplied limit param', () => {
    const sql = buildRecentTradesSql({
      bucketPredicateSql: 'TRUE',
      packageFilterSql: 'p.package_type IN ($2)',
      limitParam: '$3',
    })
    expect(sql).toContain('ORDER BY p.execution_start DESC')
    expect(sql).toContain('LIMIT $3')
  })
})
