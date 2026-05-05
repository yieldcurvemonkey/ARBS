import { describe, expect, it } from '@jest/globals'
import {
  buildVolumeGridSql,
  computeWindowBounds,
  computePercentile,
  summariseCells,
  parseVolumeGridParams,
  shapeVolumeGridResponse,
} from '../route.logic'

describe('parseVolumeGridParams', () => {
  it('applies defaults for missing params', () => {
    const out = parseVolumeGridParams(new URLSearchParams())
    expect(out).toEqual({
      ok: true,
      value: { metric: 'notional', period: 'today', lookbackDays: 90 },
    })
  })
  it('rejects invalid metric', () => {
    const out = parseVolumeGridParams(new URLSearchParams('metric=foo'))
    expect(out.ok).toBe(false)
  })
  it('rejects invalid period', () => {
    const out = parseVolumeGridParams(new URLSearchParams('period=foo'))
    expect(out.ok).toBe(false)
  })
  it('rejects out-of-range lookbackDays', () => {
    expect(parseVolumeGridParams(new URLSearchParams('lookbackDays=0')).ok).toBe(false)
    expect(parseVolumeGridParams(new URLSearchParams('lookbackDays=999')).ok).toBe(false)
  })
})

describe('computeWindowBounds', () => {
  const now = new Date('2026-05-05T14:32:00Z')
  it('today: current=since 00:00 ET, baseline=last 90 trading days', () => {
    const out = computeWindowBounds('today', 90, now)
    expect(out.currentStart.getTime()).toBeLessThan(now.getTime())
    expect(out.baselineStart.getTime()).toBeLessThan(out.currentStart.getTime())
    expect(out.windowIdSql).toContain('date_trunc')
  })
  it('1h: current is now-1h..now', () => {
    const out = computeWindowBounds('1h', 90, now)
    expect(now.getTime() - out.currentStart.getTime()).toBe(60 * 60 * 1000)
  })
  it('24h: current is now-24h..now', () => {
    const out = computeWindowBounds('24h', 90, now)
    expect(now.getTime() - out.currentStart.getTime()).toBe(24 * 60 * 60 * 1000)
  })
  it('1w: current is now-7d..now, baseline is 52 weeks', () => {
    const out = computeWindowBounds('1w', 90, now)
    expect(now.getTime() - out.currentStart.getTime()).toBe(7 * 24 * 60 * 60 * 1000)
    expect(now.getTime() - out.baselineStart.getTime()).toBeGreaterThanOrEqual(
      52 * 7 * 24 * 60 * 60 * 1000,
    )
  })
})

describe('buildVolumeGridSql', () => {
  it('uses gross_notional for metric=notional', () => {
    const sql = buildVolumeGridSql('notional', 'today')
    expect(sql).toContain('gross_notional')
    expect(sql).not.toContain('SUM(gross_dv01)')
  })
  it('uses gross_dv01 for metric=dv01', () => {
    const sql = buildVolumeGridSql('dv01', 'today')
    expect(sql).toContain('gross_dv01')
  })
  it('filters on contributes_to_flow=TRUE', () => {
    const sql = buildVolumeGridSql('notional', 'today')
    expect(sql).toContain('contributes_to_flow')
    expect(sql).toContain('TRUE')
  })
  it('excludes fwd_other rows', () => {
    const sql = buildVolumeGridSql('notional', 'today')
    expect(sql).toContain("<> 'fwd_other'")
  })
})

describe('computePercentile', () => {
  it('returns 0 when current is below all prior values', () => {
    expect(computePercentile(0, [10, 20, 30])).toBe(0)
  })
  it('returns 100 when current exceeds all prior values', () => {
    expect(computePercentile(100, [10, 20, 30])).toBe(100)
  })
  it('returns ~67 when current is at the median', () => {
    expect(computePercentile(20, [10, 20, 30])).toBeCloseTo(66.67, 1)
  })
  it('returns null when prior is empty', () => {
    expect(computePercentile(5, [])).toBeNull()
  })
})

describe('summariseCells', () => {
  it('aggregates row + col + grand totals', () => {
    const cells = [
      { fwd: 'spot', tenor: '5y', current: 10, tradeCount: 3, baseline: { p25: 0, p50: 0, p75: 0, min: 0, max: 0, n: 0 }, percentile: null },
      { fwd: 'spot', tenor: '10y', current: 20, tradeCount: 5, baseline: { p25: 0, p50: 0, p75: 0, min: 0, max: 0, n: 0 }, percentile: null },
      { fwd: '6m_1y', tenor: '5y', current: 5, tradeCount: 1, baseline: { p25: 0, p50: 0, p75: 0, min: 0, max: 0, n: 0 }, percentile: null },
    ] as never
    const totals = summariseCells(cells)
    expect(totals.rowTotals.spot.current).toBe(30)
    expect(totals.rowTotals['6m_1y'].current).toBe(5)
    expect(totals.colTotals['5y'].current).toBe(15)
    expect(totals.colTotals['10y'].current).toBe(20)
    expect(totals.grand.current).toBe(35)
  })
})

describe('shapeVolumeGridResponse', () => {
  it('drops fwd_other and null tenor cells', () => {
    const out = shapeVolumeGridResponse(
      [
        { fwd: 'fwd_other', tenor: '5y', current_value: 1, trade_count: 1, prior_array: [], p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0, as_of_ts: null },
        { fwd: 'spot', tenor: '', current_value: 1, trade_count: 1, prior_array: [], p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0, as_of_ts: null },
        { fwd: 'spot', tenor: '5y', current_value: 1, trade_count: 1, prior_array: [], p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0, as_of_ts: null },
      ],
      { metric: 'notional', period: 'today', lookbackDays: 90 },
    )
    expect(out.cells.length).toBe(1)
    expect(out.cells[0].fwd).toBe('spot')
  })
})
