import { describe, expect, it } from '@jest/globals'
import type { FocusedTrade, TimeseriesPointAug } from '../analytics-types'
import {
  effectiveTimeseriesMetric,
  focusedTimeseriesValue,
  formatTimeseriesTickParts,
  formatTimeseriesTooltipTime,
  interpolateIntradayMinutely,
  projectTimeseriesPoint,
} from '../TimeseriesTab.helpers'

const focused = {
  fixed_rate_bps: 387.5,
  dv01_usd_per_bp: 50_000,
  notional_usd: 60_000_000,
  tenor_years: 10,
} as FocusedTrade

const point: TimeseriesPointAug = {
  ts: '2026-04-23T00:00:00Z',
  idbClose: 388,
  custyClose: 387,
  idbDv01: -25_000,
  custyDv01: 50_000,
  idbNotional: 55_000_000,
  custyNotional: 60_000_000,
}

describe('TimeseriesTab projection helpers', () => {
  it('uses real notional from the analytics-timeseries route, not a DV01 ratio', () => {
    const projected = projectTimeseriesPoint(point, 0, 'notional', focused)

    expect(projected.idbClose).toBe(55)
    expect(projected.custyClose).toBe(60)
  })

  it('keeps DV01 in raw USD/bp units and preserves signs for net risk', () => {
    const projected = projectTimeseriesPoint(point, 0, 'dv01', focused)

    expect(projected.idbClose).toBe(-25_000)
    expect(projected.custyClose).toBe(50_000)
  })

  it('maps VOLUME to DV01 unless the trader explicitly selects notional', () => {
    expect(effectiveTimeseriesMetric('fixed_rate', 'VOLUME')).toBe('dv01')
    expect(effectiveTimeseriesMetric('notional', 'VOLUME')).toBe('notional')
  })

  it('returns focused DV01 in raw USD/bp units', () => {
    expect(focusedTimeseriesValue(focused, 'dv01')).toBe(50_000)
  })

  it('formats intraday axis ticks with both date and NY timestamp', () => {
    expect(formatTimeseriesTickParts('2026-04-23T14:30:00Z', 'INTRADAY')).toEqual({
      primary: 'Apr 23',
      secondary: '10:30',
    })
  })

  it('formats tooltip time as explicit date and timestamp rows', () => {
    expect(formatTimeseriesTooltipTime('2026-04-23T14:30:15Z')).toEqual({
      date: 'Thu, Apr 23, 2026',
      timestamp: '10:30:15',
      timezone: 'NY',
    })
  })
})

describe('interpolateIntradayMinutely — LOCF rate fill', () => {
  it('returns [] for empty input without throwing', () => {
    expect(interpolateIntradayMinutely([])).toEqual([])
  })

  it('forward-fills IDB and CUSTY rates onto a uniform per-minute grid', () => {
    const ticks: TimeseriesPointAug[] = [
      { ts: '2026-04-23T14:00:30Z', idbClose: 388.0, custyClose: null, idbDv01: 1, custyDv01: 0, idbNotional: 1, custyNotional: 0, idbPrints: 1, custyPrints: 0 },
      { ts: '2026-04-23T14:02:10Z', idbClose: null, custyClose: 387.5, idbDv01: 0, custyDv01: 2, idbNotional: 0, custyNotional: 2, idbPrints: 0, custyPrints: 1 },
      { ts: '2026-04-23T14:04:55Z', idbClose: 388.4, custyClose: null, idbDv01: 3, custyDv01: 0, idbNotional: 3, custyNotional: 0, idbPrints: 1, custyPrints: 0 },
    ]
    const filled = interpolateIntradayMinutely(ticks)
    // Span is 14:00 → 14:04 inclusive at 1-minute steps → 5 buckets.
    expect(filled).toHaveLength(5)
    expect(filled.map((p) => p.ts)).toEqual([
      '2026-04-23T14:00:00.000Z',
      '2026-04-23T14:01:00.000Z',
      '2026-04-23T14:02:00.000Z',
      '2026-04-23T14:03:00.000Z',
      '2026-04-23T14:04:00.000Z',
    ])
    // IDB sees a print at 14:00 → carries 388.0 forward through 14:01,
    // then no new print until 14:04 → still 388.0 at 14:02 / 14:03 →
    // 388.4 at 14:04.
    expect(filled.map((p) => p.idbClose)).toEqual([388.0, 388.0, 388.0, 388.0, 388.4])
    // CUSTY had no prior print at 14:00 / 14:01 → null until 14:02
    // (387.5), then carried forward.
    expect(filled.map((p) => p.custyClose)).toEqual([null, null, 387.5, 387.5, 387.5])
  })

  it('keeps DV01 / notional / prints attached to their originating minute (does not forward-fill volume)', () => {
    const ticks: TimeseriesPointAug[] = [
      { ts: '2026-04-23T14:00:30Z', idbClose: 388.0, custyClose: null, idbDv01: 10, custyDv01: 0, idbNotional: 100, custyNotional: 0, idbPrints: 1, custyPrints: 0 },
      { ts: '2026-04-23T14:02:10Z', idbClose: null, custyClose: 387.5, idbDv01: 0, custyDv01: 20, idbNotional: 0, custyNotional: 200, idbPrints: 0, custyPrints: 1 },
    ]
    const filled = interpolateIntradayMinutely(ticks)
    expect(filled.map((p) => p.idbDv01)).toEqual([10, 0, 0])
    expect(filled.map((p) => p.custyDv01)).toEqual([0, 0, 20])
    expect(filled.map((p) => p.idbPrints)).toEqual([1, 0, 0])
    expect(filled.map((p) => p.custyPrints)).toEqual([0, 0, 1])
  })

  it('sums multiple ticks falling within the same minute bucket', () => {
    const ticks: TimeseriesPointAug[] = [
      { ts: '2026-04-23T14:00:05Z', idbClose: 388.0, custyClose: null, idbDv01: 5, custyDv01: 0, idbNotional: 50, custyNotional: 0, idbPrints: 1, custyPrints: 0 },
      { ts: '2026-04-23T14:00:45Z', idbClose: 388.2, custyClose: null, idbDv01: 7, custyDv01: 0, idbNotional: 70, custyNotional: 0, idbPrints: 1, custyPrints: 0 },
    ]
    const filled = interpolateIntradayMinutely(ticks)
    expect(filled).toHaveLength(1)
    expect(filled[0].idbDv01).toBe(12)
    expect(filled[0].idbPrints).toBe(2)
    // Last tick within the minute wins for the LOCF rate.
    expect(filled[0].idbClose).toBe(388.2)
  })
})
