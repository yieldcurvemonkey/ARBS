import {
  computeTechnicalSignalsFromSeries,
  getInterpolationCorners,
  interpolateGridValue
} from '../engine'

describe('vol grid engine', () => {
  test('getInterpolationCorners returns a single corner for a core node', () => {
    const corners = getInterpolationCorners('1M', '10Y')

    expect(corners).toEqual([{ key: '1m_10y', weight: 1 }])
  })

  test('interpolateGridValue uses log-space tenor interpolation', () => {
    const gridData = {
      '1m_2y': 100,
      '1m_5y': 130
    }
    const expectedWeight =
      (Math.log(3) - Math.log(2)) / (Math.log(5) - Math.log(2))

    const interpolated = interpolateGridValue(gridData, '1M', '3Y')

    expect(interpolated).toBeCloseTo(100 * (1 - expectedWeight) + 130 * expectedWeight)
  })

  test('interpolateGridValue extrapolates beyond the max expiry instead of clamping to 10Y', () => {
    const gridData = {
      '5y_1y': 80,
      '10y_1y': 84
    }

    const interpolated = interpolateGridValue(gridData, '20Y', '1Y')

    expect(interpolated).toBeCloseTo(88)
    expect(interpolated).not.toBeCloseTo(84)
  })

  test('computeTechnicalSignalsFromSeries identifies a breakout regime', () => {
    const timeseries = Array.from({ length: 25 }, (_, index) => ({
      date: `2026-02-${String(index + 1).padStart(2, '0')}`,
      nvol: index < 20 ? 100 + index * 0.1 : 110 + index
    }))

    const signals = computeTechnicalSignalsFromSeries(timeseries)

    expect(signals.regimeLabel).toBe('breakout')
    expect(signals.maShortVsLong).toBe('above')
  })
})
