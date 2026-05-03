import { describe, expect, it } from '@jest/globals'
import type { FocusedTrade, TimeseriesPointAug } from '../analytics-types'
import {
  effectiveTimeseriesMetric,
  focusedTimeseriesValue,
  formatTimeseriesTickParts,
  formatTimeseriesTooltipTime,
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
