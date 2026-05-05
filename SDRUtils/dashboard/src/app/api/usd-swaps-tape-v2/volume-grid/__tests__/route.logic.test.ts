import { describe, expect, it } from '@jest/globals'
import {
  buildVolumeGridSql,
  buildVolumeGridSqlTimeOfDay,
  buildVolumeGridSqlRolling,
  computeWindowBounds,
  computePercentile,
  summariseCells,
  parseVolumeGridParams,
  shapeVolumeGridResponse,
  timeOfDayInEt,
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

describe('timeOfDayInEt', () => {
  it('returns ET date and seconds-of-day for a UTC timestamp during EDT', () => {
    // 2026-05-05 14:32:15 UTC == 10:32:15 EDT
    const out = timeOfDayInEt(new Date('2026-05-05T14:32:15Z'))
    expect(out.dateEt).toBe('2026-05-05')
    expect(out.todSeconds).toBe(10 * 3600 + 32 * 60 + 15)
  })
  it('returns ET date and seconds-of-day for a UTC timestamp during EST', () => {
    // 2026-01-15 14:00:00 UTC == 09:00:00 EST
    const out = timeOfDayInEt(new Date('2026-01-15T14:00:00Z'))
    expect(out.dateEt).toBe('2026-01-15')
    expect(out.todSeconds).toBe(9 * 3600)
  })
})

describe('computeWindowBounds — time_of_day kind', () => {
  const now = new Date('2026-05-05T14:32:15Z') // 10:32:15 ET (EDT)

  it('today: kind=time_of_day, tod=[0, tod_now]', () => {
    const out = computeWindowBounds('today', 90, now)
    expect(out.kind).toBe('time_of_day')
    if (out.kind === 'time_of_day') {
      expect(out.todayDateEt).toBe('2026-05-05')
      expect(out.todSecondsLo).toBe(0)
      expect(out.todSecondsHi).toBe(10 * 3600 + 32 * 60 + 15)
      expect(out.lookbackEnd.getTime()).toBe(now.getTime())
      expect(now.getTime() - out.lookbackStart.getTime()).toBe(90 * 24 * 60 * 60 * 1000)
    }
  })

  it('1h: kind=time_of_day, tod=[tod_now-3600, tod_now]', () => {
    const out = computeWindowBounds('1h', 90, now)
    expect(out.kind).toBe('time_of_day')
    if (out.kind === 'time_of_day') {
      const todNow = 10 * 3600 + 32 * 60 + 15
      expect(out.todSecondsLo).toBe(todNow - 3600)
      expect(out.todSecondsHi).toBe(todNow)
    }
  })

  it('1h: clamps tod_lo to 0 if before midnight', () => {
    // 2026-05-05 04:30:00 UTC == 00:30:00 EDT — tod_now=1800
    const earlyMorning = new Date('2026-05-05T04:30:00Z')
    const out = computeWindowBounds('1h', 90, earlyMorning)
    expect(out.kind).toBe('time_of_day')
    if (out.kind === 'time_of_day') {
      expect(out.todSecondsLo).toBe(0)
      expect(out.todSecondsHi).toBe(1800)
    }
  })
})

describe('computeWindowBounds — rolling kind', () => {
  const now = new Date('2026-05-05T14:32:00Z')

  it('24h: kind=rolling, currentStart=now-24h', () => {
    const out = computeWindowBounds('24h', 90, now)
    expect(out.kind).toBe('rolling')
    if (out.kind === 'rolling') {
      expect(now.getTime() - out.currentStart.getTime()).toBe(24 * 60 * 60 * 1000)
      expect(out.windowIdSql).toContain('date_trunc')
    }
  })

  it('1w: kind=rolling, currentStart=now-7d, lookback=52w', () => {
    const out = computeWindowBounds('1w', 90, now)
    expect(out.kind).toBe('rolling')
    if (out.kind === 'rolling') {
      expect(now.getTime() - out.currentStart.getTime()).toBe(7 * 24 * 60 * 60 * 1000)
      expect(now.getTime() - out.lookbackStart.getTime()).toBeGreaterThanOrEqual(
        52 * 7 * 24 * 60 * 60 * 1000,
      )
    }
  })
})

describe('buildVolumeGridSqlTimeOfDay', () => {
  it('uses gross_notional for metric=notional', () => {
    const sql = buildVolumeGridSqlTimeOfDay('notional')
    expect(sql).toContain('gross_notional')
    expect(sql).not.toContain('SUM(gross_dv01)')
  })
  it('uses gross_dv01 for metric=dv01', () => {
    expect(buildVolumeGridSqlTimeOfDay('dv01')).toContain('gross_dv01')
  })
  it('filters on contributes_to_flow=TRUE', () => {
    expect(buildVolumeGridSqlTimeOfDay('notional')).toContain('contributes_to_flow')
  })
  it('excludes fwd_other rows', () => {
    expect(buildVolumeGridSqlTimeOfDay('notional')).toContain("<> 'fwd_other'")
  })
  it('filters by tod_seconds_et range', () => {
    const sql = buildVolumeGridSqlTimeOfDay('notional')
    expect(sql).toContain('tod_seconds_et >= $4')
    expect(sql).toContain('tod_seconds_et <= $5')
  })
  it('partitions current vs prior by day_et = $3 / day_et < $3', () => {
    const sql = buildVolumeGridSqlTimeOfDay('notional')
    expect(sql).toContain('day_et = $3')
    expect(sql).toContain('day_et < $3')
  })
  it('extracts ET seconds-of-day for the time-of-day filter', () => {
    expect(buildVolumeGridSqlTimeOfDay('notional')).toContain("AT TIME ZONE 'America/New_York'")
  })
})

describe('buildVolumeGridSqlRolling', () => {
  it('keeps the rolling window template (current via $3)', () => {
    const sql = buildVolumeGridSqlRolling('notional')
    expect(sql).toContain('ts >= $3::timestamptz')
    expect(sql).toContain('%WINDOW_ID_SQL%')
  })
})

describe('buildVolumeGridSql dispatch', () => {
  it('dispatches to time_of_day when bounds.kind=time_of_day', () => {
    const bounds = computeWindowBounds('today', 90, new Date('2026-05-05T14:32:00Z'))
    const sql = buildVolumeGridSql('notional', bounds)
    expect(sql).toContain('day_et = $3')
  })
  it('dispatches to rolling when bounds.kind=rolling', () => {
    const bounds = computeWindowBounds('24h', 90, new Date('2026-05-05T14:32:00Z'))
    const sql = buildVolumeGridSql('notional', bounds)
    expect(sql).toContain('%WINDOW_ID_SQL%')
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
