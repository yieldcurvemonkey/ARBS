import { buildGridMatrix, computeStats, filterByRange } from '../analytics'
import type { ListedVolGridCell, ListedVolSeriesPoint } from '../types'

function buildPoint(date: string, listedNvolBps: number): ListedVolSeriesPoint {
  return {
    date,
    timestamp: new Date(`${date}T00:00:00Z`).getTime(),
    listedNvolBps,
    swaptionNvolBps: null,
    volRatio: null,
    volDiffBps: null,
    realizedNvolBps: null,
    impliedRealizedRatio: null
  }
}

function buildCell(product: ListedVolGridCell['product'], expiryLabel: ListedVolGridCell['expiryLabel']): ListedVolGridCell {
  return {
    asOfDate: '2026-03-09',
    product,
    productClass: product === 'SFR' ? 'STIR' : 'UST',
    expiryLabel,
    atmNvolBps: 55,
    atmNvolPrice: 0.55,
    dailyChange: 1.2,
    zScore: 0.8,
    percentile: 70,
    historyMean: 54,
    historyStd: 1.25,
    forwardPrice: 95.5,
    forwardYield: 4.5,
    fv01: product === 'SFR' ? null : 0.08,
    underlyingContract: 'TYM26',
    source: 'test'
  }
}

describe('listed-vol analytics', () => {
  test('filterByRange keeps only points inside the selected range', () => {
    const points = [
      buildPoint('2025-12-01', 72),
      buildPoint('2026-01-15', 73),
      buildPoint('2026-02-12', 74),
      buildPoint('2026-03-09', 75)
    ]

    const filtered = filterByRange(points, '1M')

    expect(filtered.map((point) => point.date)).toEqual(['2026-02-12', '2026-03-09'])
  })

  test('computeStats returns mean, z-score, percentile, and change', () => {
    const stats = computeStats([72, 73, 75, 74])

    expect(stats.latest).toBe(74)
    expect(stats.mean).toBe(73.5)
    expect(stats.std).not.toBeNull()
    expect(stats.percentile).toBe(75)
    expect(stats.dailyChange).toBe(-1)
  })

  test('buildGridMatrix maps cells into product and expiry order', () => {
    const matrix = buildGridMatrix(
      [buildCell('TY', '1M'), buildCell('SFR', '3M')],
      ['TY', 'SFR'],
      ['1M', '3M']
    )

    expect(matrix[0][0]?.product).toBe('TY')
    expect(matrix[0][1]).toBeNull()
    expect(matrix[1][1]?.product).toBe('SFR')
  })
})
