import { DEFAULT_CELL_DISPLAY_CONFIG, type VolGridCell, type VolGridHeatmapRange } from '../types'
import { getUnifiedCellBackground } from '../utils'

const HEATMAP_RANGE: VolGridHeatmapRange = {
  volMin: 70,
  volMax: 90,
  premiumMin: 10,
  premiumMax: 20,
  volChangeMaxAbs: 5,
  premiumChangeMaxAbs: 2
}

function buildCell(overrides: Partial<VolGridCell> = {}): VolGridCell {
  return {
    nodeKey: '1m_1y',
    expiry: '1M',
    tenor: '1Y',
    expiryYears: 1 / 12,
    tenorYears: 1,
    atmfVol: 80,
    eodVol: 79,
    atmfVolSource: 'direct_observation',
    atmfVolConfidence: 0.85,
    atmfVolChange: 0.5,
    atmfVolChangeTime: 1,
    atmfPremium: 1000,
    atmfPremiumBps: 15,
    atmfPremiumBpsChange: 0.2,
    lastObservation: null,
    observationCount: 1,
    staleness: 1,
    stalenessCategory: 'live',
    lastPropagatedFrom: null,
    propagationFactor: 0,
    quadrant: 'ULC',
    regimeLabel: 'trending',
    comparisonVol: null,
    comparisonDiff: null,
    ...overrides
  }
}

function parseRgba(value: string) {
  const match = value.match(/^rgba\((\d+), (\d+), (\d+), ([0-9.]+)\)$/)
  if (!match) {
    throw new Error(`Unexpected rgba value: ${value}`)
  }

  return {
    red: Number(match[1]),
    green: Number(match[2]),
    blue: Number(match[3]),
    alpha: Number(match[4])
  }
}

describe('vol-grid display defaults', () => {
  test('starts with heatmap coloring disabled', () => {
    expect(DEFAULT_CELL_DISPLAY_CONFIG.heatmap.strategy).toBe('none')
    expect(DEFAULT_CELL_DISPLAY_CONFIG.heatmap.palette).toBe('icefire')
  })

  test('returns the neutral background when heatmap coloring is disabled', () => {
    expect(
      getUnifiedCellBackground(
        buildCell(),
        {
          strategy: 'none',
          metric: 'vol',
          palette: 'icefire',
          inverted: false,
          customTargets: ''
        },
        HEATMAP_RANGE
      )
    ).toBe('rgba(15, 23, 42, 0.72)')
  })

  test('absolute heatmap uses a blue-to-red icefire-style ramp', () => {
    const lowColor = parseRgba(
      getUnifiedCellBackground(
        buildCell({ atmfVol: HEATMAP_RANGE.volMin }),
        {
          strategy: 'absolute',
          metric: 'vol',
          palette: 'icefire',
          inverted: false,
          customTargets: ''
        },
        HEATMAP_RANGE
      )
    )
    const highColor = parseRgba(
      getUnifiedCellBackground(
        buildCell({ atmfVol: HEATMAP_RANGE.volMax }),
        {
          strategy: 'absolute',
          metric: 'vol',
          palette: 'icefire',
          inverted: false,
          customTargets: ''
        },
        HEATMAP_RANGE
      )
    )

    expect(lowColor.blue).toBeGreaterThan(lowColor.red)
    expect(highColor.red).toBeGreaterThan(highColor.blue)
    expect(lowColor.alpha).toBeCloseTo(0.96)
    expect(highColor.alpha).toBeCloseTo(0.96)
  })

  test('different palettes produce different heatmap colors for the same value', () => {
    const icefireColor = getUnifiedCellBackground(
      buildCell({ atmfVol: HEATMAP_RANGE.volMax }),
      {
        strategy: 'absolute',
        metric: 'vol',
        palette: 'icefire',
        inverted: false,
        customTargets: ''
      },
      HEATMAP_RANGE
    )
    const viridisColor = getUnifiedCellBackground(
      buildCell({ atmfVol: HEATMAP_RANGE.volMax }),
      {
        strategy: 'absolute',
        metric: 'vol',
        palette: 'viridis',
        inverted: false,
        customTargets: ''
      },
      HEATMAP_RANGE
    )

    expect(icefireColor).not.toBe(viridisColor)
    expect(parseRgba(viridisColor).green).toBeGreaterThan(parseRgba(icefireColor).green)
  })

  test('blue palette stays blue-based at the high end', () => {
    const blueColor = parseRgba(
      getUnifiedCellBackground(
        buildCell({ atmfVol: HEATMAP_RANGE.volMax }),
        {
          strategy: 'absolute',
          metric: 'vol',
          palette: 'blue',
          inverted: false,
          customTargets: ''
        },
        HEATMAP_RANGE
      )
    )

    expect(blueColor.blue).toBeGreaterThan(blueColor.red)
    expect(blueColor.blue).toBeGreaterThan(blueColor.green)
  })
})
