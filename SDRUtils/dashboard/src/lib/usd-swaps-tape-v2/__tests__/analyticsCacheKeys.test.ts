import { describe, expect, it } from '@jest/globals'
import {
  timeseriesKey,
  rarityKey,
  extremesKey,
  type AnalyticsCacheKey,
} from '../analyticsCacheKeys'

describe('analyticsCacheKeys', () => {
  it('timeseriesKey is stable across runs for identical input', () => {
    const a = timeseriesKey({
      bucket: 'canonical:USD/SOFR-OIS/COMPOUND',
      view: 'DAILY_CLOSE',
      range: '1M',
      groupBy: 'canonical',
      groupValueOverride: 'USD/SOFR-OIS/COMPOUND',
      options: { tolerance: 0.5 },
    })
    const b = timeseriesKey({
      bucket: 'canonical:USD/SOFR-OIS/COMPOUND',
      view: 'DAILY_CLOSE',
      range: '1M',
      groupBy: 'canonical',
      groupValueOverride: 'USD/SOFR-OIS/COMPOUND',
      options: { tolerance: 0.5 },
    })
    expect(a).toEqual(b)
  })

  it('does NOT include orthogonal display options in key', () => {
    const a = timeseriesKey({
      bucket: 'x',
      view: 'DAILY_CLOSE',
      range: '1M',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { useGrossDv01: true, excludeLargeCusty: true },
    })
    const b = timeseriesKey({
      bucket: 'x',
      view: 'DAILY_CLOSE',
      range: '1M',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { useGrossDv01: false, excludeLargeCusty: false },
    })
    expect(a).toEqual(b)
  })

  it('option ordering does not affect the optionsHash', () => {
    const a = timeseriesKey({
      bucket: 'x',
      view: 'DAILY_CLOSE',
      range: '1M',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { tolerance: 0.5, lookback: 90 },
    })
    const b = timeseriesKey({
      bucket: 'x',
      view: 'DAILY_CLOSE',
      range: '1M',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { lookback: 90, tolerance: 0.5 },
    })
    expect(a).toEqual(b)
  })

  it('different buckets produce different keys', () => {
    const a = timeseriesKey({
      bucket: 'a',
      view: 'DAILY_CLOSE',
      range: '1M',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: {},
    })
    const b = timeseriesKey({
      bucket: 'b',
      view: 'DAILY_CLOSE',
      range: '1M',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: {},
    })
    expect(a).not.toEqual(b)
  })

  it('rarityKey and extremesKey have stable shapes', () => {
    const r: AnalyticsCacheKey = rarityKey({
      bucket: 'x',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { lookback: 90, primaryTol: 0.5, sizeTol: 0.2, binMetric: 'fixed_rate' },
    })
    expect(r[0]).toBe('usd-swaps-tape-v2')
    expect(r[1]).toBe('rarity')
    expect(r[3]).toBeNull() // view slot is null for rarity

    const e: AnalyticsCacheKey = extremesKey({
      bucket: 'x',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { primaryTol: 0.5, sizeTol: 0.2 },
    })
    expect(e[1]).toBe('extremes')
  })

  it('rarityKey hashes options into the optionsHash slot', () => {
    const a = rarityKey({
      bucket: 'x',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { lookback: 90 },
    })
    const b = rarityKey({
      bucket: 'x',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { lookback: 180 },
    })
    expect(a).not.toEqual(b)
  })
})
