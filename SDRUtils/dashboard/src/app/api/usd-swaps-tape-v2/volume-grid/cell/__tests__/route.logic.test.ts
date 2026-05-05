import { describe, expect, it } from '@jest/globals'
import {
  parseVolumeGridCellParams,
  buildIntradaySeasonalitySql,
  buildTimeseriesSql,
  buildRecentTradesSql,
  easternDateKey,
  rangeToStartDate,
  shapeIntradaySeasonalityResponse,
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
  it('accepts FOMC schema with a meeting label fwd id', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=APR26&tenor=5y&forwardSchema=fomc&packageType=fomc'),
    )
    expect(out.ok).toBe(true)
  })
  it('rejects malformed FOMC label under fomc schema', () => {
    expect(
      parseVolumeGridCellParams(
        new URLSearchParams('fwd=garbage&tenor=5y&forwardSchema=fomc'),
      ).ok,
    ).toBe(false)
  })
  it('accepts venue MIC code as tenor under venue schema', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=spot&tenor=BBSF&tenorSchema=venue'),
    )
    expect(out.ok).toBe(true)
  })
  it('rejects malformed MIC under venue schema', () => {
    expect(
      parseVolumeGridCellParams(
        new URLSearchParams('fwd=spot&tenor=oops!&tenorSchema=venue'),
      ).ok,
    ).toBe(false)
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

describe('buildIntradaySeasonalitySql', () => {
  it('builds a current-vs-baseline cumulative intraday profile query', () => {
    const sql = buildIntradaySeasonalitySql({
      metric: 'dv01',
      bucketPredicateSql: 'l.forward_start_years < $4',
      packageFilterSql: 'p.package_type IN ($5)',
    })
    expect(sql).toContain('generate_series')
    expect(sql).toContain('JOIN arbs_usd_swap_tape_packages_v2 p ON p.package_id = l.package_id')
    expect(sql).toContain('baseline_cumulative')
    expect(sql).toContain('current_cumulative')
    expect(sql).toContain('SUM(dv01)')
  })
})

describe('shapeIntradaySeasonalityResponse', () => {
  it('nulls current points after the current as-of bucket and keeps the average line', () => {
    const out = shapeIntradaySeasonalityResponse([
      {
        bucket_index: 0,
        minute_of_day: 30,
        current_value: 10,
        average_value: 8,
        observed_days: 5,
        as_of_ts: '2026-05-05T13:05:00Z',
      },
      {
        bucket_index: 30,
        minute_of_day: 930,
        current_value: 20,
        average_value: 18,
        observed_days: 5,
        as_of_ts: '2026-05-05T13:05:00Z',
      },
    ])
    expect(out.bucketMinutes).toBe(1)
    expect(out.observedDays).toBe(5)
    expect(out.asOf).toBe('2026-05-05T13:05:00.000Z')
    expect(out.points[0]).toMatchObject({ minuteOfDay: 30, current: 10, average: 8 })
    expect(out.points[1]).toMatchObject({ minuteOfDay: 930, current: null, average: 18 })
  })
})

describe('easternDateKey', () => {
  it('formats dates in America/New_York', () => {
    expect(easternDateKey(new Date('2026-05-05T03:30:00Z'))).toBe('2026-05-04')
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
