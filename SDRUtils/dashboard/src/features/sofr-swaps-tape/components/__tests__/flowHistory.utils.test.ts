import { describe, expect, it } from '@jest/globals'
import {
  buildFlowGridRows,
  flattenFlowHistory,
  formatUsdMillions,
  getLatestFlowDay
} from '../flowHistory.utils'
import type { FlowHistoryDay } from '../../types'

function buildDay(date: string): FlowHistoryDay {
  const stats = {
    tradeCount: 1,
    grossNotional: 100_000_000,
    grossRisk: 25_000,
    avgFixedRate: 0.0425,
    idbTradeCount: 1,
    custyTradeCount: 0
  }
  return {
    date,
    quadrants: {
      frontShort: { ...stats },
      frontLong: { ...stats },
      forwardShort: { ...stats },
      forwardLong: { ...stats }
    },
    boundary: { ...stats },
    unknown: { ...stats },
    gridTotal: { ...stats }
  }
}

describe('flowHistory utils', () => {
  it('returns latest day by date key', () => {
    const latest = getLatestFlowDay([buildDay('2026-02-01'), buildDay('2026-02-05')])
    expect(latest?.date).toBe('2026-02-05')
  })

  it('flattens daily data for charting', () => {
    const flattened = flattenFlowHistory([buildDay('2026-02-05')])
    expect(flattened).toHaveLength(1)
    expect(flattened[0].frontShortNotional).toBe(100_000_000)
    expect(flattened[0].forwardLongRisk).toBe(25_000)
  })

  it('builds four flow grid rows', () => {
    const rows = buildFlowGridRows(buildDay('2026-02-05'))
    expect(rows).toHaveLength(4)
    expect(rows.map((row) => row.bucket)).toEqual([
      'frontShort',
      'frontLong',
      'forwardShort',
      'forwardLong'
    ])
  })

  it('formats USD millions helper', () => {
    expect(formatUsdMillions(123_400_000)).toBe('123.4m')
    expect(formatUsdMillions(null)).toBe('--')
  })
})
