// ABOUTME: Unit tests for the pure computeSequenceAggregate helper
// that drives SequenceBar, the SequenceTab summary card, and the
// useAnalyticsSequence wrapper. Covers the math (DV01-weighted rate,
// time-span bounds, venue/side counts) and edge cases (empty input,
// missing execution_start, zero DV01 fallback).
import { describe, expect, it } from '@jest/globals'
import type { FocusedTrade } from '../analytics-types'
import { computeSequenceAggregate } from '../sequence-aggregate'

function focused(overrides: Partial<FocusedTrade> = {}): FocusedTrade {
  return {
    id: 'PKG-A',
    tape_label: 'USD-SOFR 5Y Outright',
    package_structure: 'OUTRIGHT',
    package_tenors: '5Y',
    trade_type: 'OUTRIGHT',
    tenor_years: 5,
    fixed_rate_bps: 380,
    weighted_fixed_rate: 0.038,
    dv01_usd_per_bp: 25_000,
    notional_usd: 50_000_000,
    pts: null,
    side: 'PAY',
    platform: 'CUSTY',
    venue: 'BBSF',
    execution_start: '2026-04-23T09:00:00Z',
    execution_session: 'AM',
    lifecycle_type: 'NEW_RISK',
    is_block: false,
    ...overrides,
  }
}

describe('computeSequenceAggregate', () => {
  it('returns a zero shape for an empty sequence', () => {
    const agg = computeSequenceAggregate([])
    expect(agg.count).toBe(0)
    expect(agg.totalDv01Usd).toBe(0)
    expect(agg.totalNotionalUsd).toBe(0)
    expect(agg.weightedFixedRateBps).toBe(0)
    expect(agg.timeSpanMs).toBeNull()
    expect(agg.startTs).toBeNull()
    expect(agg.endTs).toBeNull()
    expect(agg.sideMix).toEqual({ pay: 0, rcv: 0 })
    expect(agg.venueMix).toEqual({})
  })

  it('sums absolute DV01 + notional across the sequence', () => {
    const agg = computeSequenceAggregate([
      focused({ dv01_usd_per_bp: 20_000, notional_usd: 50_000_000 }),
      focused({ dv01_usd_per_bp: -30_000, notional_usd: 75_000_000 }),
      focused({ dv01_usd_per_bp: 10_000, notional_usd: 25_000_000 }),
    ])
    expect(agg.count).toBe(3)
    // DV01 sums absolute values: 20 + 30 + 10 = 60K.
    expect(agg.totalDv01Usd).toBe(60_000)
    expect(agg.totalNotionalUsd).toBe(150_000_000)
  })

  it('computes a DV01-weighted fixed rate (bps)', () => {
    const agg = computeSequenceAggregate([
      focused({ fixed_rate_bps: 380, dv01_usd_per_bp: 30_000 }),
      focused({ fixed_rate_bps: 400, dv01_usd_per_bp: 10_000 }),
    ])
    // (380*30 + 400*10) / 40 = 385.
    expect(agg.weightedFixedRateBps).toBeCloseTo(385, 4)
  })

  it('falls back to notional weighting when DV01 is zero', () => {
    const agg = computeSequenceAggregate([
      focused({ fixed_rate_bps: 380, dv01_usd_per_bp: 0, notional_usd: 100_000_000 }),
      focused({ fixed_rate_bps: 400, dv01_usd_per_bp: 0, notional_usd: 100_000_000 }),
    ])
    expect(agg.weightedFixedRateBps).toBeCloseTo(390, 4)
  })

  it('counts side mix across PAY / RCV', () => {
    const agg = computeSequenceAggregate([
      focused({ side: 'PAY' }),
      focused({ side: 'PAY' }),
      focused({ side: 'RCV' }),
    ])
    expect(agg.sideMix).toEqual({ pay: 2, rcv: 1 })
  })

  it('builds a venueMix histogram', () => {
    const agg = computeSequenceAggregate([
      focused({ venue: 'TWSF' }),
      focused({ venue: 'BBSF' }),
      focused({ venue: 'BBSF' }),
    ])
    expect(agg.venueMix).toEqual({ TWSF: 1, BBSF: 2 })
  })

  it('finds the earliest + latest execution_start and the span', () => {
    const agg = computeSequenceAggregate([
      focused({ execution_start: '2026-04-23T09:30:00Z' }),
      focused({ execution_start: '2026-04-23T09:00:00Z' }),
      focused({ execution_start: '2026-04-23T10:00:00Z' }),
    ])
    expect(agg.startTs).toBe('2026-04-23T09:00:00Z')
    expect(agg.endTs).toBe('2026-04-23T10:00:00Z')
    expect(agg.timeSpanMs).toBe(60 * 60_000) // 1 hour
  })

  it('returns null span when no trade has an execution_start', () => {
    const agg = computeSequenceAggregate([
      focused({ execution_start: null }),
      focused({ execution_start: null }),
    ])
    expect(agg.startTs).toBeNull()
    expect(agg.endTs).toBeNull()
    expect(agg.timeSpanMs).toBeNull()
  })

  it('handles a partial-execution-start sequence (some null) without crashing', () => {
    const agg = computeSequenceAggregate([
      focused({ execution_start: '2026-04-23T09:00:00Z' }),
      focused({ execution_start: null }),
      focused({ execution_start: '2026-04-23T10:00:00Z' }),
    ])
    expect(agg.startTs).toBe('2026-04-23T09:00:00Z')
    expect(agg.endTs).toBe('2026-04-23T10:00:00Z')
    expect(agg.timeSpanMs).toBe(60 * 60_000)
  })
})
