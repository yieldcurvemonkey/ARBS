import { describe, expect, it } from '@jest/globals'
import { __internal } from '../useAnalyticsTimeseries'
import { timeseriesKey } from '@/lib/usd-swaps-tape-v2/analyticsCacheKeys'

describe('useAnalyticsTimeseries query wiring', () => {
  it('does NOT include orthogonal display toggles on the request URL', () => {
    // Post-Phase-C contract: server returns the full variant grid
    // regardless, so dropping these from the URL keeps the dock-hook
    // and hover-prefetch URLs identical and lets one in-flight fetch
    // satisfy both code paths.
    const q = __internal.buildAnalyticsTimeseriesQuery(
      'USD-SOFR 10Y',
      'DAILY_CLOSE',
      '1M',
      { useGrossDv01: true, excludeLargeCusty: false },
    )

    expect(q.get('useGrossDv01')).toBeNull()
    expect(q.get('excludeLargeCusty')).toBeNull()
    expect(q.get('value')).toBe('USD-SOFR 10Y')
    expect(q.get('view')).toBe('DAILY_CLOSE')
    expect(q.get('range')).toBe('1M')
  })

  it('omits removeZeroRates from the URL when the flag is left at the default (true)', () => {
    // Server defaults `removeZeroRates` to true. Keep the URL tidy
    // when the trader never touches the toggle so the canonical URL
    // matches the previous-cache hits during rollout.
    const q = __internal.buildAnalyticsTimeseriesQuery(
      'USD-SOFR 10Y',
      'DAILY_CLOSE',
      '1M',
      { removeZeroRates: true },
    )
    expect(q.get('removeZeroRates')).toBeNull()
  })

  it('writes removeZeroRates=false on the URL when the trader toggles 0-rate prints back in', () => {
    const q = __internal.buildAnalyticsTimeseriesQuery(
      'USD-SOFR 10Y',
      'DAILY_CLOSE',
      '1M',
      { removeZeroRates: false },
    )
    expect(q.get('removeZeroRates')).toBe('false')
  })

  it('removeZeroRates DOES change the SWR cache key (it changes the warehouse aggregation)', () => {
    const withZeros = timeseriesKey({
      bucket: 'bucket',
      view: 'DAILY_CLOSE',
      range: '1Y',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { removeZeroRates: false },
    })
    const withoutZeros = timeseriesKey({
      bucket: 'bucket',
      view: 'DAILY_CLOSE',
      range: '1Y',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { removeZeroRates: true },
    })
    expect(withZeros).not.toEqual(withoutZeros)
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
