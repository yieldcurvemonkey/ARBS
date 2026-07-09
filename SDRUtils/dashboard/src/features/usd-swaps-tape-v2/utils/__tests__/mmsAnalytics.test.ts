import { describe, expect, it } from '@jest/globals'
import type { UsdSwapTapeRow, UsdSwapTapeLeg } from '../../types'
import {
  isMmsRow,
  computeMmsSummary,
  computeMmsDailyVolume,
  computeMmsMaturityDistribution,
  computeMmsTopCusips,
} from '../mmsAnalytics'

function mockRow(overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow {
  return {
    package_type: 'OUTRIGHT',
    is_matched_maturity_all: false,
    total_risk: 50000,
    total_notional: 10_000_000,
    execution_start: '2026-07-08T16:00:00Z',
    tape_label_ust_alias: '',
    legs_json: [],
    ...overrides,
  } as UsdSwapTapeRow
}

function mmsRow(overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow {
  return mockRow({
    package_type: 'MATCHED_MATURITY_CURVE',
    is_matched_maturity_all: true,
    total_risk: 80000,
    total_notional: 20_000_000,
    tape_label_ust_alias: 'USD-SOFR Spot 0536/0546 CURVE MMS PHYS',
    legs_json: [
      { matched_ust_maturity: true, ust_cusip: '91282CQQ7', tape_label_ust_alias: '0536' } as UsdSwapTapeLeg,
      { matched_ust_maturity: true, ust_cusip: '912810UV8', tape_label_ust_alias: '0546' } as UsdSwapTapeLeg,
    ],
    ...overrides,
  })
}

describe('isMmsRow', () => {
  it('returns true for MATCHED_MATURITY package_type', () => {
    expect(isMmsRow(mmsRow())).toBe(true)
  })
  it('returns true for is_matched_maturity_all', () => {
    expect(isMmsRow(mockRow({ is_matched_maturity_all: true, package_type: 'PKG-3' }))).toBe(true)
  })
  it('returns false for OUTRIGHT', () => {
    expect(isMmsRow(mockRow())).toBe(false)
  })
})

describe('computeMmsSummary', () => {
  it('computes count, share, and DV01', () => {
    const rows = [mmsRow(), mockRow(), mmsRow()]
    const summary = computeMmsSummary(rows)
    expect(summary.mmsCount).toBe(2)
    expect(summary.totalCount).toBe(3)
    expect(summary.mmsDv01).toBe(160000)
    expect(summary.dv01Share).toBeCloseTo(160000 / 210000)
  })
  it('handles empty rows', () => {
    const summary = computeMmsSummary([])
    expect(summary.mmsCount).toBe(0)
  })
})

describe('computeMmsDailyVolume', () => {
  it('buckets by date', () => {
    const rows = [
      mmsRow({ execution_start: '2026-07-08T10:00:00Z' }),
      mmsRow({ execution_start: '2026-07-08T14:00:00Z' }),
      mockRow({ execution_start: '2026-07-08T15:00:00Z' }),
      mmsRow({ execution_start: '2026-07-09T10:00:00Z' }),
    ]
    const daily = computeMmsDailyVolume(rows)
    expect(daily.length).toBe(2)
    const jul8 = daily.find((d) => d.date === '2026-07-08')
    expect(jul8?.mmsCount).toBe(2)
    expect(jul8?.totalCount).toBe(3)
  })
})

describe('computeMmsMaturityDistribution', () => {
  it('parses MMYY from tape_label_ust_alias', () => {
    const rows = [
      mmsRow({ tape_label_ust_alias: 'USD-SOFR Spot 0536/0546 CURVE MMS PHYS' }),
      mmsRow({ tape_label_ust_alias: 'USD-SOFR Spot 0536 MMS PHYS' }),
    ]
    const dist = computeMmsMaturityDistribution(rows)
    const m0536 = dist.find((d) => d.mmyy === '0536')
    expect(m0536?.count).toBe(2)
    const m0546 = dist.find((d) => d.mmyy === '0546')
    expect(m0546?.count).toBe(1)
  })
})

describe('computeMmsTopCusips', () => {
  it('aggregates by ust_cusip from legs_json', () => {
    const rows = [mmsRow(), mmsRow()]
    const top = computeMmsTopCusips(rows)
    const q = top.find((c) => c.cusip === '91282CQQ7')
    expect(q?.count).toBe(2)
  })
})
