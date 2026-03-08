import {
  buildSurfaceMatrix,
  filterTradeHistoryByRange,
  filterTimeseriesByRange,
  getHistoryMetricValue,
  getTradeTimelineMetricValue
} from '../analytics'
import type {
  CalibrationObservation,
  VolGridCell,
  VolGridTimeseriesPoint
} from '../types'

function buildPoint(date: string, nvol: number, dailyChange: number | null): VolGridTimeseriesPoint {
  return {
    date,
    timestamp: new Date(`${date}T00:00:00Z`).getTime(),
    nvol,
    dailyChange
  }
}

function buildCell(nodeKey: string, atmfVol: number): VolGridCell {
  return {
    nodeKey,
    expiry: '1M',
    tenor: '1Y',
    expiryYears: 1 / 12,
    tenorYears: 1,
    atmfVol,
    eodVol: atmfVol - 1,
    atmfVolSource: 'direct_observation',
    atmfVolConfidence: 0.9,
    atmfVolChange: 1,
    atmfVolChangeTime: 1,
    atmfPremium: 1000,
    atmfPremiumBps: 12.5,
    atmfPremiumBpsChange: 0.25,
    lastObservation: null,
    observationCount: 1,
    staleness: 1,
    stalenessCategory: 'live',
    lastPropagatedFrom: null,
    propagationFactor: 0,
    quadrant: 'ULC',
    regimeLabel: 'trending',
    comparisonVol: null,
    comparisonDiff: null
  }
}

function buildTrade(
  executionTimestamp: number,
  overrides: Partial<CalibrationObservation> = {}
): CalibrationObservation {
  return {
    packageId: `pkg-${executionTimestamp}`,
    executionTimestamp,
    platform: 'IDB',
    packageType: 'STRADDLE',
    bpvolYr: 82.5,
    premium: 125000,
    notional: 250_000_000,
    tradeLabel: '1Mx1Y',
    isCalibrationTrade: true,
    ...overrides
  }
}

describe('vol-grid analytics helpers', () => {
  test('filterTimeseriesByRange keeps only points inside the selected window', () => {
    const points = [
      buildPoint('2025-12-01', 80, null),
      buildPoint('2026-01-15', 81, 1),
      buildPoint('2026-02-10', 82, 1),
      buildPoint('2026-03-01', 83, 1)
    ]

    const filtered = filterTimeseriesByRange(points, '1M')

    expect(filtered.map((point) => point.date)).toEqual(['2026-02-10', '2026-03-01'])
  })

  test('getHistoryMetricValue resolves nvol and day-over-day change', () => {
    const point = buildPoint('2026-03-01', 83, 1.2)

    expect(getHistoryMetricValue(point, 'nvol')).toBe(83)
    expect(getHistoryMetricValue(point, 'dailyChange')).toBe(1.2)
  })

  test('filterTradeHistoryByRange keeps only trades inside the selected window', () => {
    const trades = [
      buildTrade(new Date('2025-12-01T15:00:00Z').getTime()),
      buildTrade(new Date('2026-01-15T15:00:00Z').getTime()),
      buildTrade(new Date('2026-02-10T15:00:00Z').getTime()),
      buildTrade(new Date('2026-03-01T15:00:00Z').getTime())
    ]

    const filtered = filterTradeHistoryByRange(trades.slice().reverse(), '1M')

    expect(filtered.map((trade) => trade.executionTimestamp)).toEqual([
      new Date('2026-03-01T15:00:00Z').getTime(),
      new Date('2026-02-10T15:00:00Z').getTime()
    ])
  })

  test('getTradeTimelineMetricValue resolves bpvol, premium, and notional', () => {
    const trade = buildTrade(new Date('2026-03-01T15:00:00Z').getTime(), {
      bpvolYr: 84.1,
      premium: 225000,
      notional: 500_000_000
    })

    expect(getTradeTimelineMetricValue(trade, 'bpvol')).toBe(84.1)
    expect(getTradeTimelineMetricValue(trade, 'premium')).toBe(225000)
    expect(getTradeTimelineMetricValue(trade, 'notional')).toBe(500_000_000)
  })

  test('buildSurfaceMatrix maps cells into expiry-tenor order', () => {
    const cells = [buildCell('1m_1y', 72.1), buildCell('3m_2y', 84.4)]

    const matrix = buildSurfaceMatrix(cells, ['1M', '3M'], ['1Y', '2Y'])

    expect(matrix.z).toEqual([
      [72.1, null],
      [null, 84.4]
    ])
    expect(matrix.hoverText[1][1]).toBe('3Mx2Y')
  })
})
