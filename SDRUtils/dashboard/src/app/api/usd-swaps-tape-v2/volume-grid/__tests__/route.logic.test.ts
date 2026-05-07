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
import {
  resolveForwardSchema,
  resolveTenorSchema,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

describe('parseVolumeGridParams', () => {
  it('applies defaults', () => {
    const out = parseVolumeGridParams(new URLSearchParams())
    expect(out).toEqual({
      ok: true,
      value: {
        metric: 'notional', period: 'today', lookbackDays: 90,
        forwardSchema: 'default', tenorSchema: 'default', packageType: 'outright',
        viewMode: 'volume',
      },
    })
  })
  it('rejects invalid viewMode', () => {
    expect(parseVolumeGridParams(new URLSearchParams('viewMode=foo')).ok).toBe(false)
  })
  it('accepts idb_custy viewMode', () => {
    const out = parseVolumeGridParams(new URLSearchParams('viewMode=idb_custy'))
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.viewMode).toBe('idb_custy')
  })
  it('accepts fomc forward schema', () => {
    const out = parseVolumeGridParams(new URLSearchParams('forwardSchema=fomc'))
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.forwardSchema).toBe('fomc')
  })
  it('rejects invalid metric', () => {
    expect(parseVolumeGridParams(new URLSearchParams('metric=foo')).ok).toBe(false)
  })
  it('rejects invalid period', () => {
    expect(parseVolumeGridParams(new URLSearchParams('period=foo')).ok).toBe(false)
  })
  it('accepts extended rolling periods', () => {
    for (const period of ['2w', '3w', '1m', '3m']) {
      const out = parseVolumeGridParams(new URLSearchParams(`period=${period}`))
      expect(out.ok).toBe(true)
      if (out.ok) expect(out.value.period).toBe(period)
    }
  })
  it('rejects invalid forwardSchema', () => {
    expect(parseVolumeGridParams(new URLSearchParams('forwardSchema=foo')).ok).toBe(false)
  })
  it('rejects invalid packageType', () => {
    expect(parseVolumeGridParams(new URLSearchParams('packageType=foo')).ok).toBe(false)
  })
  it('accepts lookbackDays up to 730 (2y baseline)', () => {
    const out = parseVolumeGridParams(new URLSearchParams('lookbackDays=730'))
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.lookbackDays).toBe(730)
  })
  it('rejects lookbackDays above 730', () => {
    expect(parseVolumeGridParams(new URLSearchParams('lookbackDays=731')).ok).toBe(false)
  })
  it('accepts imm16 + spreadover', () => {
    const out = parseVolumeGridParams(
      new URLSearchParams('forwardSchema=imm16&packageType=spreadover_curve'),
    )
    expect(out.ok).toBe(true)
    if (out.ok) {
      expect(out.value.forwardSchema).toBe('imm16')
      expect(out.value.packageType).toBe('spreadover_curve')
    }
  })
})

describe('timeOfDayInEt', () => {
  it('converts UTC to ET seconds-of-day during EDT', () => {
    const out = timeOfDayInEt(new Date('2026-05-05T14:32:15Z'))
    expect(out.dateEt).toBe('2026-05-05')
    expect(out.todSeconds).toBe(10 * 3600 + 32 * 60 + 15)
  })
})

describe('computeWindowBounds', () => {
  const now = new Date('2026-05-05T14:32:15Z')

  it('today: kind=time_of_day with tod=[0, tod_now]', () => {
    const out = computeWindowBounds('today', 90, now)
    expect(out.kind).toBe('time_of_day')
    if (out.kind === 'time_of_day') {
      expect(out.todSecondsLo).toBe(0)
      expect(out.todSecondsHi).toBe(10 * 3600 + 32 * 60 + 15)
    }
  })

  it('1h: tod_lo = tod_now - 3600', () => {
    const out = computeWindowBounds('1h', 90, now)
    if (out.kind === 'time_of_day') {
      expect(out.todSecondsHi - out.todSecondsLo).toBe(3600)
    }
  })

  it('24h: kind=rolling', () => {
    const out = computeWindowBounds('24h', 90, now)
    expect(out.kind).toBe('rolling')
  })

  it('3m: kind=rolling with a quarter baseline and extended lookback', () => {
    const out = computeWindowBounds('3m', 90, now)
    expect(out.kind).toBe('rolling')
    if (out.kind === 'rolling') {
      expect(out.windowIdSql).toContain("date_trunc('quarter'")
      expect(now.getTime() - out.lookbackStart.getTime()).toBeGreaterThan(300 * 86_400_000)
    }
  })
})

describe('buildVolumeGridSqlTimeOfDay', () => {
  const fwd = resolveForwardSchema('default')
  const tenor = resolveTenorSchema('default')
  const bounds = computeWindowBounds('today', 90, new Date('2026-05-05T14:32:00Z'))

  it('joins arbs_usd_swap_tape_packages_v2 to filter by package_type', () => {
    const built = buildVolumeGridSqlTimeOfDay({
      metric: 'notional', forwardSchema: fwd, tenorSchema: tenor,
      packageType: 'outright', bounds,
    })
    expect(built.sql).toContain('JOIN arbs_usd_swap_tape_packages_v2 p ON p.package_id = l.package_id')
    expect(built.sql).toContain('p.package_type IN ($6)')
    expect(built.params[5]).toBe('OUTRIGHT')
  })

  it('emits SQL with no package_type filter when packageType=all', () => {
    const built = buildVolumeGridSqlTimeOfDay({
      metric: 'notional', forwardSchema: fwd, tenorSchema: tenor,
      packageType: 'all', bounds,
    })
    expect(built.sql).toContain('AND TRUE')
    expect(built.params.length).toBe(5)
  })

  it('expands spreadover_curve to two package types', () => {
    const built = buildVolumeGridSqlTimeOfDay({
      metric: 'notional', forwardSchema: fwd, tenorSchema: tenor,
      packageType: 'spreadover_curve', bounds,
    })
    expect(built.sql).toContain('p.package_type IN ($6, $7)')
    expect(built.params[5]).toBe('SPREADOVER_CURVE')
    expect(built.params[6]).toBe('MATCHED_MATURITY_CURVE')
  })

  it('uses gross_notional for metric=notional', () => {
    const built = buildVolumeGridSqlTimeOfDay({
      metric: 'notional', forwardSchema: fwd, tenorSchema: tenor,
      packageType: 'outright', bounds,
    })
    expect(built.sql).toContain('gross_notional')
  })

  it('drops fwd_other / tenor_other rows', () => {
    const built = buildVolumeGridSqlTimeOfDay({
      metric: 'notional', forwardSchema: fwd, tenorSchema: tenor,
      packageType: 'outright', bounds,
    })
    expect(built.sql).toContain("fwd_bucket <> 'other'")
    expect(built.sql).toContain("tenor_bucket <> 'other'")
  })

  it('emits per-platform IDB / CUSTY aggregates in current_agg', () => {
    const built = buildVolumeGridSqlTimeOfDay({
      metric: 'notional', forwardSchema: fwd, tenorSchema: tenor,
      packageType: 'outright', bounds,
    })
    expect(built.sql).toContain("FILTER (WHERE platform = 'IDB')")
    expect(built.sql).toContain("FILTER (WHERE platform = 'CUSTY')")
    expect(built.sql).toContain('idb_current')
    expect(built.sql).toContain('custy_current')
  })

  it('uses fomc_meeting_label as bucket id for the fomc schema (and only label-not-null filter)', () => {
    const fomc = resolveForwardSchema('fomc')
    const built = buildVolumeGridSqlTimeOfDay({
      metric: 'notional', forwardSchema: fomc, tenorSchema: tenor,
      packageType: 'outright', bounds,
    })
    expect(built.sql).toContain('l.fomc_meeting_label AS fwd_bucket')
    expect(built.sql).toContain('l.fomc_meeting_label IS NOT NULL')
    expect(built.sql).not.toContain('l.is_fomc_dated = TRUE')
  })

  it('uses platform_identifier as col bucket for venue tenor schema', () => {
    const venue = resolveTenorSchema('venue')
    const built = buildVolumeGridSqlTimeOfDay({
      metric: 'notional', forwardSchema: fwd, tenorSchema: venue,
      packageType: 'outright', bounds,
    })
    expect(built.sql).toContain('l.platform_identifier AS tenor_bucket')
    expect(built.sql).toContain('l.platform_identifier IS NOT NULL')
  })
})

describe('buildVolumeGridSqlRolling', () => {
  const fwd = resolveForwardSchema('default')
  const tenor = resolveTenorSchema('default')
  const bounds = computeWindowBounds('1w', 90, new Date('2026-05-05T14:32:00Z'))

  it('inlines the windowIdSql expression for week truncation', () => {
    const built = buildVolumeGridSqlRolling({
      metric: 'notional', forwardSchema: fwd, tenorSchema: tenor,
      packageType: 'outright', bounds,
    })
    expect(built.sql).toContain("date_trunc('week'")
    expect(built.sql).toContain('p.package_type IN ($4)')
    expect(built.params[3]).toBe('OUTRIGHT')
  })
})

describe('buildVolumeGridSql dispatch', () => {
  const fwd = resolveForwardSchema('default')
  const tenor = resolveTenorSchema('default')
  it('dispatches by bounds.kind', () => {
    const tod = buildVolumeGridSql({
      metric: 'notional', forwardSchema: fwd, tenorSchema: tenor,
      packageType: 'outright',
      bounds: computeWindowBounds('today', 90, new Date()),
    })
    expect(tod.sql).toContain('day_et = $3')

    const rolling = buildVolumeGridSql({
      metric: 'notional', forwardSchema: fwd, tenorSchema: tenor,
      packageType: 'outright',
      bounds: computeWindowBounds('1w', 90, new Date()),
    })
    expect(rolling.sql).not.toContain('day_et = $3')
  })
})

describe('computePercentile', () => {
  it('returns 0 / 100 / null on edge cases', () => {
    expect(computePercentile(0, [10, 20, 30])).toBe(0)
    expect(computePercentile(100, [10, 20, 30])).toBe(100)
    expect(computePercentile(5, [])).toBeNull()
  })
})

describe('summariseCells', () => {
  it('aggregates row + col + grand totals', () => {
    const cells = [
      { fwd: 'spot', tenor: '5y', current: 10, tradeCount: 3, baseline: { p25: 0, p50: 0, p75: 0, min: 0, max: 0, n: 0 }, percentile: null },
      { fwd: 'spot', tenor: '10y', current: 20, tradeCount: 5, baseline: { p25: 0, p50: 0, p75: 0, min: 0, max: 0, n: 0 }, percentile: null },
    ] as never
    const totals = summariseCells(cells)
    expect(totals.rowTotals.spot.current).toBe(30)
    expect(totals.colTotals['10y'].current).toBe(20)
    expect(totals.grand.current).toBe(30)
  })
})

describe('shapeVolumeGridResponse', () => {
  it('drops cells whose ids are not in the resolved schema and surfaces idb/custy splits', () => {
    const fwd = resolveForwardSchema('default')
    const tenor = resolveTenorSchema('default')
    const out = shapeVolumeGridResponse(
      [
        { fwd: 'fwd_other', tenor: '5y', current_value: 1, idb_current: 0, custy_current: 1, trade_count: 1, prior_array: [], p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0, as_of_ts: null },
        { fwd: 'spot', tenor: 'unknown_tenor', current_value: 1, idb_current: 0, custy_current: 1, trade_count: 1, prior_array: [], p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0, as_of_ts: null },
        { fwd: 'spot', tenor: '5y', current_value: 100, idb_current: 40, custy_current: 60, trade_count: 1, prior_array: [], p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0, as_of_ts: null },
      ],
      {
        metric: 'notional', period: 'today', lookbackDays: 90,
        forwardSchema: 'default', tenorSchema: 'default', packageType: 'outright',
        viewMode: 'volume',
      },
      fwd,
      tenor,
    )
    expect(out.cells.length).toBe(1)
    expect(out.cells[0].fwd).toBe('spot')
    expect(out.cells[0].idbCurrent).toBe(40)
    expect(out.cells[0].custyCurrent).toBe(60)
    expect(out.axes.forward.buckets.length).toBe(8)
    expect(out.axes.tenor.buckets.length).toBe(16)
    expect(out.viewMode).toBe('volume')
  })

  it('discovers venue MIC buckets for the venue tenor schema', () => {
    const fwd = resolveForwardSchema('default')
    const venue = resolveTenorSchema('venue')
    const out = shapeVolumeGridResponse(
      [
        { fwd: 'spot', tenor: 'BBSF', current_value: 1, idb_current: 0, custy_current: 1, trade_count: 1, prior_array: [], p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0, as_of_ts: null },
        { fwd: 'spot', tenor: 'BGCD', current_value: 1, idb_current: 1, custy_current: 0, trade_count: 1, prior_array: [], p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0, as_of_ts: null },
        { fwd: 'spot', tenor: 'TWSF', current_value: 1, idb_current: 0, custy_current: 1, trade_count: 1, prior_array: [], p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0, as_of_ts: null },
      ],
      {
        metric: 'notional', period: 'today', lookbackDays: 90,
        forwardSchema: 'default', tenorSchema: 'venue', packageType: 'all',
        viewMode: 'volume',
      },
      fwd,
      venue,
    )
    // IDB MICs first (BGCD), then CUSTY (BBSF, TWSF)
    expect(out.axes.tenor.buckets.map((b) => b.id)).toEqual(['BGCD', 'BBSF', 'TWSF'])
  })

  it('discovers fomc bucket labels from rows (filters to upcoming, max 16)', () => {
    const fwd = resolveForwardSchema('fomc')
    const tenor = resolveTenorSchema('default')
    const labels = ['JAN21', 'APR21', 'MAR2026', 'JUN26', 'APR26', 'DEC27']
    const out = shapeVolumeGridResponse(
      labels.map((l) => ({
        fwd: l, tenor: '5y',
        current_value: 1, idb_current: 0, custy_current: 1,
        trade_count: 1, prior_array: [],
        p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0, as_of_ts: null,
      })),
      {
        metric: 'notional', period: 'today', lookbackDays: 90,
        forwardSchema: 'fomc', tenorSchema: 'default', packageType: 'fomc',
        viewMode: 'volume',
      },
      fwd,
      tenor,
    )
    const ids = out.axes.forward.buckets.map((b) => b.id)
    // Historical labels (JAN21, APR21) and unparseable (MAR2026) are dropped
    expect(ids).not.toContain('JAN21')
    expect(ids).not.toContain('APR21')
    expect(ids).not.toContain('MAR2026')
    expect(ids.length).toBeLessThanOrEqual(16)
    // Chronological order maintained for the kept labels
    const kept = ids.filter((x) => ['APR26', 'JUN26', 'DEC27'].includes(x))
    expect(kept).toEqual(['APR26', 'JUN26', 'DEC27'])
  })
})
