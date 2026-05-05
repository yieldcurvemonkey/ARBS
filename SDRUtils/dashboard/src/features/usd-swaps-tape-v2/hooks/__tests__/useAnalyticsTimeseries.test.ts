import { describe, expect, it } from '@jest/globals'
import { __internal } from '../useAnalyticsTimeseries'
import { timeseriesKey } from '@/lib/usd-swaps-tape-v2/analyticsCacheKeys'

describe('useAnalyticsTimeseries query wiring', () => {
  it('sends Net/Gross DV01 and custy-outlier toggles to the analytics route', () => {
    const q = __internal.buildAnalyticsTimeseriesQuery(
      'USD-SOFR 10Y',
      'DAILY_CLOSE',
      '1M',
      { useGrossDv01: true, excludeLargeCusty: false },
    )

    expect(q.get('useGrossDv01')).toBe('true')
    expect(q.get('excludeLargeCusty')).toBe('false')
  })

  it('orthogonal display toggles do NOT change the SWR cache key', () => {
    // Phase B/C contract: useGrossDv01 + excludeLargeCusty are display
    // options that change which numbers the chart shows, not which
    // warehouse aggregation runs. They MUST not bust the cache.
    const netClean = timeseriesKey({
      bucket: 'bucket',
      view: 'DAILY_CLOSE',
      range: '1Y',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { useGrossDv01: false, excludeLargeCusty: true },
    })
    const grossRaw = timeseriesKey({
      bucket: 'bucket',
      view: 'DAILY_CLOSE',
      range: '1Y',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { useGrossDv01: true, excludeLargeCusty: false },
    })

    expect(netClean).toEqual(grossRaw)
  })

  it('range / view / groupBy DO change the SWR cache key', () => {
    const a = timeseriesKey({
      bucket: 'bucket',
      view: 'DAILY_CLOSE',
      range: '1M',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: {},
    })
    const b = timeseriesKey({
      bucket: 'bucket',
      view: 'DAILY_CLOSE',
      range: '1Y',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: {},
    })
    expect(a).not.toEqual(b)
  })

  it('view changes DO change the SWR cache key (DAILY_CLOSE vs INTRADAY)', () => {
    const a = timeseriesKey({
      bucket: 'bucket',
      view: 'DAILY_CLOSE',
      range: '1M',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: {},
    })
    const b = timeseriesKey({
      bucket: 'bucket',
      view: 'INTRADAY',
      range: '1D',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: {},
    })
    expect(a).not.toEqual(b)
  })

  it('groupValueOverride DOES change the SWR cache key', () => {
    const a = timeseriesKey({
      bucket: 'bucket',
      view: 'DAILY_CLOSE',
      range: '1M',
      groupBy: 'canonical',
      groupValueOverride: 'USD/SOFR-OIS/COMPOUND',
      options: {},
    })
    const b = timeseriesKey({
      bucket: 'bucket',
      view: 'DAILY_CLOSE',
      range: '1M',
      groupBy: 'canonical',
      groupValueOverride: 'USD/TERM-SOFR/QUARTERLY',
      options: {},
    })
    expect(a).not.toEqual(b)
  })
})
