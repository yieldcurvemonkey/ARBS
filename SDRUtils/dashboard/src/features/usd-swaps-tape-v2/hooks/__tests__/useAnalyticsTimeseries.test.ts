import { describe, expect, it } from '@jest/globals'
import { __internal } from '../useAnalyticsTimeseries'

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

  it('keys the cache by risk basis and custy outlier mode', () => {
    const netClean = __internal.cacheKey('bucket', 'DAILY_CLOSE', '1Y', {
      useGrossDv01: false,
      excludeLargeCusty: true,
    })
    const grossRaw = __internal.cacheKey('bucket', 'DAILY_CLOSE', '1Y', {
      useGrossDv01: true,
      excludeLargeCusty: false,
    })

    expect(netClean).not.toBe(grossRaw)
  })
})
