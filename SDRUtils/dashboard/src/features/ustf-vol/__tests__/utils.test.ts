import { describe, expect, it } from '@jest/globals'

import type { TimeseriesResponse, UstfTimeseriesMultiResponse, UstfTimeseriesSeries } from '../types'
import {
  buildTimeseriesSeriesSearchOptions,
  buildComparisonSnapshotRow,
  buildFormulaSeries,
  buildTechnicalStudySeries,
  computeSeriesStats,
  computeTimeseriesHeadlineStats,
  findLatestComparablePoint,
  formatSeriesConfigLabel,
  formatSignedNumber,
  formatSnapshotDate,
  formatTechnicalStudyShortLabel,
  getTimeseriesHistoricalWindow,
  getSeriesConfigKey,
  getTimeseriesTechnicalStudyAxisMode,
  getLatestSnapshotDate,
  mergeTimeseriesCollection,
  normalizeFormulaLegs,
  parseTimeseriesFormulaCommand,
  searchTimeseriesSeriesOptions,
  shouldPrefetchHistoricalTimeseries,
} from '../utils'

const SAMPLE_RESPONSE: TimeseriesResponse = {
  series1Label: '1M TY ATM',
  series2Label: '1Mx7Y Swpn',
  points: [
    { date: '2026-03-03', series1: 125.2, series2: 129.8, spread: -4.6 },
    { date: '2026-03-04', series1: 126.1, series2: null, spread: null },
    { date: '2026-03-05', series1: 127.3, series2: 130.1, spread: -2.8 },
  ],
  stats: {
    series1: {
      latest: 127.3,
      mean: 126.2,
      min: 125.2,
      max: 127.3,
      stdev: 0.86,
      zScore: 1.27,
      count: 3,
    },
    series2: {
      latest: 130.1,
      mean: 129.95,
      min: 129.8,
      max: 130.1,
      stdev: 0.15,
      zScore: 1,
      count: 2,
    },
    spread: {
      latest: -2.8,
      mean: -3.7,
      min: -4.6,
      max: -2.8,
      stdev: 0.9,
      zScore: 1,
      count: 2,
    },
  },
}

const TREND_SERIES: UstfTimeseriesSeries = {
  id: 'ustf:TY:1M',
  label: '1M TY ATM',
  config: { type: 'ustf', product: 'TY', expiry: '1M' },
  stats: {
    latest: 120,
    mean: 110,
    min: 100,
    max: 120,
    stdev: 6,
    zScore: 1.6,
    count: 21,
  },
  points: Array.from({ length: 21 }, (_, index) => ({
    asOf: `2026-01-${String(index + 1).padStart(2, '0')}`,
    value: 100 + index,
  })),
}

const CHOPPY_SERIES: UstfTimeseriesSeries = {
  id: 'swaption:7Y:1M',
  label: '1Mx7Y Swpn',
  config: { type: 'swaption', tail: '7Y', expiry: '1M' },
  stats: {
    latest: 104,
    mean: 102,
    min: 100,
    max: 104,
    stdev: 1.5,
    zScore: 1,
    count: 5,
  },
  points: [
    { asOf: '2026-02-01', value: 100 },
    { asOf: '2026-02-02', value: 102 },
    { asOf: '2026-02-03', value: 101 },
    { asOf: '2026-02-04', value: 103 },
    { asOf: '2026-02-05', value: 104 },
  ],
}

describe('ustf-vol utils', () => {
  it('finds the latest point with aligned listed and otc data', () => {
    expect(findLatestComparablePoint(SAMPLE_RESPONSE.points)).toEqual({
      date: '2026-03-05',
      series1: 127.3,
      series2: 130.1,
      spread: -2.8,
    })
  })

  it('builds a snapshot row from the latest aligned point', () => {
    expect(buildComparisonSnapshotRow('1M TY vs 1Mx7Y', SAMPLE_RESPONSE)).toEqual({
      pairLabel: '1M TY vs 1Mx7Y',
      asOfDate: '2026-03-05',
      updatedAt: null,
      listedLabel: '1M TY ATM',
      otcLabel: '1Mx7Y Swpn',
      listedVol: 127.3,
      otcVol: 130.1,
      spread: -2.8,
      spreadZScore: 1,
    })
  })

  it('formats signed numbers and snapshot dates for the pricer table', () => {
    expect(formatSignedNumber(2.4)).toBe('+2.4')
    expect(formatSignedNumber(-2.4)).toBe('-2.4')
    expect(formatSignedNumber(null)).toBe('--')
    expect(formatSnapshotDate('2026-03-05')).toBe('MAR 05 26')
    expect(formatSnapshotDate('2026-03-12T16:39:18.584Z')).toBe('MAR 12 26')
  })

  it('returns the latest non-null snapshot date across rows', () => {
    expect(
      getLatestSnapshotDate([
        {
          pairLabel: 'A',
          asOfDate: '2026-03-04',
          updatedAt: null,
          listedLabel: 'listed',
          otcLabel: 'otc',
          listedVol: 1,
          otcVol: 2,
          spread: -1,
          spreadZScore: 0.5,
        },
        {
          pairLabel: 'B',
          asOfDate: '2026-03-06',
          updatedAt: null,
          listedLabel: 'listed',
          otcLabel: 'otc',
          listedVol: 1,
          otcVol: 2,
          spread: -1,
          spreadZScore: -0.2,
        },
        {
          pairLabel: 'C',
          asOfDate: null,
          updatedAt: null,
          listedLabel: 'listed',
          otcLabel: 'otc',
          listedVol: null,
          otcVol: null,
          spread: null,
          spreadZScore: null,
        },
      ])
    ).toBe('2026-03-06')
  })

  it('formats series labels and stable keys for the monitor', () => {
    expect(formatSeriesConfigLabel({ type: 'ustf', product: 'TY', expiry: '1M' })).toBe(
      '1M TY ATM'
    )
    expect(formatSeriesConfigLabel({ type: 'swaption', tail: '7Y', expiry: '1M' })).toBe(
      '1Mx7Y Swpn'
    )
    expect(
      formatSeriesConfigLabel({
        type: 'ustf',
        product: 'TY',
        expiry: '1M',
        volMetric: { kind: 'delta_otm', side: 'call', delta: 10 },
      })
    ).toBe('1M TY 10D Call')
    expect(
      formatSeriesConfigLabel({
        type: 'swaption',
        tail: '7Y',
        expiry: '1M',
        volMetric: { kind: 'strike_offset_otm', side: 'payer', offsetBps: 25 },
      })
    ).toBe('1Mx7Y 25bp Payer Swpn')
    expect(getSeriesConfigKey({ type: 'ustf', product: 'TY', expiry: '1M' })).toBe(
      'ustf:TY:1M'
    )
    expect(getSeriesConfigKey({ type: 'swaption', tail: '7Y', expiry: '1M' })).toBe(
      'swaption:7Y:1M'
    )
    expect(
      getSeriesConfigKey({
        type: 'ustf',
        product: 'TY',
        expiry: '1M',
        volMetric: { kind: 'delta_otm', side: 'call', delta: 10 },
      })
    ).toBe('ustf:TY:1M:delta:call:10')
    expect(
      getSeriesConfigKey({
        type: 'swaption',
        tail: '7Y',
        expiry: '1M',
        volMetric: { kind: 'strike_offset_otm', side: 'receiver', offsetBps: 25 },
      })
    ).toBe('swaption:7Y:1M:offset:receiver:25')
  })

  it('normalizes formula legs and builds a derived spread series', () => {
    expect(
      normalizeFormulaLegs([
        { seriesId: 'ustf:TY:1M', weight: 1 },
        { seriesId: 'swaption:7Y:1M', weight: -1 },
        { seriesId: 'swaption:7Y:1M', weight: 0.5 },
      ])
    ).toEqual([
      { seriesId: 'ustf:TY:1M', weight: 1 },
      { seriesId: 'swaption:7Y:1M', weight: -0.5 },
    ])

    const seriesMap = new Map<string, UstfTimeseriesSeries>([
      [
        'ustf:TY:1M',
        {
          id: 'ustf:TY:1M',
          label: '1M TY ATM',
          config: { type: 'ustf', product: 'TY', expiry: '1M' },
          stats: SAMPLE_RESPONSE.stats.series1,
          points: [
            { asOf: '2026-03-03', value: 125.2 },
            { asOf: '2026-03-04', value: 126.1 },
            { asOf: '2026-03-05', value: 127.3 },
          ],
        },
      ],
      [
        'swaption:7Y:1M',
        {
          id: 'swaption:7Y:1M',
          label: '1Mx7Y Swpn',
          config: { type: 'swaption', tail: '7Y', expiry: '1M' },
          stats: SAMPLE_RESPONSE.stats.series2!,
          points: [
            { asOf: '2026-03-03', value: 129.8 },
            { asOf: '2026-03-04', value: 130.4 },
            { asOf: '2026-03-05', value: 130.1 },
          ],
        },
      ],
    ])

    expect(
      buildFormulaSeries(
        {
          id: 'spread',
          name: 'TY minus 7Y',
          yaxis: 'y2',
          scaleBy100: false,
          legs: [
            { seriesId: 'ustf:TY:1M', weight: 1 },
            { seriesId: 'swaption:7Y:1M', weight: -1 },
          ],
        },
        seriesMap
      )
    ).toEqual({
      id: 'spread',
      name: 'TY minus 7Y',
      yaxis: 'y2',
      scaleBy100: false,
      expression: '1 * ustf:TY:1M -1 * swaption:7Y:1M',
      nonNullCount: 3,
      points: [
        { asOf: '2026-03-03', value: -4.6000000000000085 },
        { asOf: '2026-03-04', value: -4.300000000000011 },
        { asOf: '2026-03-05', value: -2.799999999999997 },
      ],
    })
  })

  it('builds rolling technical studies for overlays and oscillators', () => {
    const smaStudy = buildTechnicalStudySeries(
      {
        id: 'sma-5',
        sourceSeriesId: TREND_SERIES.id,
        kind: 'sma',
        window: 5,
      },
      TREND_SERIES
    )

    expect(smaStudy.shortLabel).toBe('SMA 5')
    expect(smaStudy.axisMode).toBe('overlay')
    expect(smaStudy.points.at(-1)?.value).toBeCloseTo(118, 8)

    const emaStudy = buildTechnicalStudySeries(
      {
        id: 'ema-3',
        sourceSeriesId: CHOPPY_SERIES.id,
        kind: 'ema',
        window: 3,
      },
      CHOPPY_SERIES
    )

    expect(emaStudy.points.at(-1)?.value).toBeCloseTo(103, 8)

    const rvStudy = buildTechnicalStudySeries(
      {
        id: 'rv-3',
        sourceSeriesId: CHOPPY_SERIES.id,
        kind: 'realized_vol',
        window: 3,
      },
      CHOPPY_SERIES
    )

    expect(rvStudy.axisMode).toBe('oscillator')
    expect(rvStudy.points.at(-1)?.value).toBeCloseTo(19.79898987, 6)
  })

  it('computes headline stats and technical-study labels for the instrument list', () => {
    const stats = computeTimeseriesHeadlineStats(TREND_SERIES.points)

    expect(stats.latest).toBe(120)
    expect(stats.min).toBe(100)
    expect(stats.max).toBe(120)
    expect(stats.latestDate).toBe('2026-01-21')
    expect(stats.change1d).toBe(1)
    expect(stats.change5d).toBe(5)
    expect(stats.vsSma20).toBeCloseTo(9.5, 8)
    expect(stats.zScore20).toBeCloseTo(1.64750894, 6)
    expect(stats.realizedVol20).toBeCloseTo(0, 8)
    expect(stats.rangePercentile).toBe(100)

    expect(formatTechnicalStudyShortLabel('bollinger_upper', 20)).toBe('Boll +2σ 20')
    expect(getTimeseriesTechnicalStudyAxisMode('momentum')).toBe('oscillator')
  })

  it('builds historical backfill windows and pan prefetch thresholds', () => {
    expect(
      getTimeseriesHistoricalWindow({
        currentStartDate: '2026-03-15',
        range: '1M',
      })
    ).toEqual({
      startDate: '2026-02-12',
      endDate: '2026-03-14',
    })

    expect(
      getTimeseriesHistoricalWindow({
        currentStartDate: '2026-03-15',
        range: '1M',
        initialStartDate: '2026-03-01',
        initialEndDate: '2026-03-10',
      })
    ).toEqual({
      startDate: '2026-02-13',
      endDate: '2026-03-14',
    })

    expect(
      shouldPrefetchHistoricalTimeseries({
        loadedStartDate: '2026-01-01',
        viewportStartDate: '2026-01-05',
        viewportEndDate: '2026-02-04',
        hasMoreHistorical: true,
        loadingHistorical: false,
      })
    ).toBe(true)

    expect(
      shouldPrefetchHistoricalTimeseries({
        loadedStartDate: '2026-01-01',
        viewportStartDate: '2026-01-25',
        viewportEndDate: '2026-02-24',
        hasMoreHistorical: true,
        loadingHistorical: false,
      })
    ).toBe(false)
  })

  it('merges prepended timeseries batches and recomputes merged stats', () => {
    const current: UstfTimeseriesMultiResponse = {
      startDate: '2026-03-03',
      endDate: '2026-03-04',
      asOfDate: '2026-03-04',
      warnings: ['Initial warning'],
      series: [
        {
          id: 'ustf:TY:1M',
          label: '1M TY ATM',
          config: { type: 'ustf', product: 'TY', expiry: '1M' as const },
          points: [
            { asOf: '2026-03-03', value: 101 },
            { asOf: '2026-03-04', value: 103 },
          ],
          stats: computeSeriesStats([101, 103]),
        },
      ],
    }

    const incoming: UstfTimeseriesMultiResponse = {
      startDate: '2026-03-01',
      endDate: '2026-03-02',
      asOfDate: '2026-03-02',
      warnings: [],
      series: [
        {
          id: 'ustf:TY:1M',
          label: '1M TY ATM',
          config: { type: 'ustf', product: 'TY', expiry: '1M' as const },
          points: [
            { asOf: '2026-03-01', value: 99 },
            { asOf: '2026-03-02', value: 100 },
          ],
          stats: computeSeriesStats([99, 100]),
        },
      ],
    }

    const merged = mergeTimeseriesCollection(current, incoming)

    expect(merged.startDate).toBe('2026-03-01')
    expect(merged.endDate).toBe('2026-03-04')
    expect(merged.asOfDate).toBe('2026-03-04')
    expect(merged.warnings).toEqual(['Initial warning'])
    expect(merged.series[0]?.points).toEqual([
      { asOf: '2026-03-01', value: 99 },
      { asOf: '2026-03-02', value: 100 },
      { asOf: '2026-03-03', value: 101 },
      { asOf: '2026-03-04', value: 103 },
    ])
    expect(merged.series[0]?.stats).toEqual({
      latest: 103,
      mean: 100.75,
      min: 99,
      max: 103,
      stdev: 1.479019945774904,
      zScore: 1.52127765851133,
      count: 4,
    })
  })

  it('returns fuzzy-ranked series matches for the command bar', () => {
    const options = buildTimeseriesSeriesSearchOptions()
    const matches = searchTimeseriesSeriesOptions('ty1m', options, 3)

    expect(matches[0]?.label).toBe('1M TY ATM')
    expect(matches.some((match) => match.label === '1Mx7Y Swpn')).toBe(false)

    const otmMatches = searchTimeseriesSeriesOptions('ty1m 10d call', options, 3)
    expect(otmMatches[0]?.label).toBe('1M TY 10D Call')
  })

  it('parses spread and fly commands from the command bar query', () => {
    const options = buildTimeseriesSeriesSearchOptions()

    expect(parseTimeseriesFormulaCommand('spread TY1M vs 1Mx7Y', options)).toEqual({
      formulaKind: 'spread',
      name: '1M TY ATM vs 1Mx7Y Swpn',
      description: '1M TY ATM - 1Mx7Y Swpn',
      series: [
        { type: 'ustf', product: 'TY', expiry: '1M' },
        { type: 'swaption', tail: '7Y', expiry: '1M' },
      ],
      legs: [
        { seriesId: 'ustf:TY:1M', weight: 1 },
        { seriesId: 'swaption:7Y:1M', weight: -1 },
      ],
    })

    expect(parseTimeseriesFormulaCommand('fly TU1M / FV1M / TY1M', options)).toEqual({
      formulaKind: 'fly',
      name: '1M TU ATM / 1M FV ATM / 1M TY ATM fly',
      description: '1M TU ATM - 2 * 1M FV ATM + 1M TY ATM',
      series: [
        { type: 'ustf', product: 'TU', expiry: '1M' },
        { type: 'ustf', product: 'FV', expiry: '1M' },
        { type: 'ustf', product: 'TY', expiry: '1M' },
      ],
      legs: [
        { seriesId: 'ustf:TU:1M', weight: 1 },
        { seriesId: 'ustf:FV:1M', weight: -2 },
        { seriesId: 'ustf:TY:1M', weight: 1 },
      ],
    })

    expect(
      parseTimeseriesFormulaCommand(
        'spread TY1M 10D Call vs 1Mx7Y 10D Payer',
        options
      )
    ).toEqual({
      formulaKind: 'spread',
      name: '1M TY 10D Call vs 1Mx7Y 10D Payer Swpn',
      description: '1M TY 10D Call - 1Mx7Y 10D Payer Swpn',
      series: [
        {
          type: 'ustf',
          product: 'TY',
          expiry: '1M',
          volMetric: { kind: 'delta_otm', side: 'call', delta: 10 },
        },
        {
          type: 'swaption',
          tail: '7Y',
          expiry: '1M',
          volMetric: { kind: 'delta_otm', side: 'payer', delta: 10 },
        },
      ],
      legs: [
        { seriesId: 'ustf:TY:1M:delta:call:10', weight: 1 },
        { seriesId: 'swaption:7Y:1M:delta:payer:10', weight: -1 },
      ],
    })
  })
})
