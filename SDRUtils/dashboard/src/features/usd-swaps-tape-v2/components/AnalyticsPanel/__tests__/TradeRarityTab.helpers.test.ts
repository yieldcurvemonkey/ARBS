import { describe, expect, it } from '@jest/globals'
import type { FocusedTrade, HistogramBin } from '../analytics-types'
import { RARITY_DEFAULT_STATE } from '../constants'
import {
  findFocusedHistogramBin,
  focusedHistogramValue,
  formatHistogramValue,
} from '../TradeRarityTab.helpers'

const focused = {
  fixed_rate_bps: 387.5,
  dv01_usd_per_bp: 50_000,
  notional_usd: 60_000_000,
} as FocusedTrade

describe('TradeRarityTab histogram helpers', () => {
  it('uses the selected histogram metric for the focused reference marker', () => {
    expect(focusedHistogramValue(focused, 'fixed_rate')).toBe(387.5)
    expect(focusedHistogramValue(focused, 'dv01')).toBe(50_000)
    expect(focusedHistogramValue(focused, 'notional')).toBe(60)
  })

  it('finds a focused value on the inclusive upper edge of the last bin', () => {
    const bins: HistogramBin[] = [
      { binStart: 0, binEnd: 50, mid: 25, custy: 1, idb: 0, total: 1, cumPct: 50, kdeScaled: 1 },
      { binStart: 50, binEnd: 100, mid: 75, custy: 0, idb: 1, total: 1, cumPct: 100, kdeScaled: 1 },
    ]

    expect(findFocusedHistogramBin(bins, 100)).toBe(bins[1])
  })

  it('formats DV01 and notional bins in their selected units', () => {
    expect(formatHistogramValue(50_000, 'dv01')).toBe('50K')
    expect(formatHistogramValue(60, 'notional')).toBe('60.0')
    expect(formatHistogramValue(387.5, 'fixed_rate')).toBe('387.5')
  })

  it('defaults the rarity histogram to DV01 as the primary desk metric', () => {
    expect(RARITY_DEFAULT_STATE.histogramMetric).toBe('dv01')
  })
})
