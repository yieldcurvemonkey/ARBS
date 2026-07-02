// ABOUTME: Tests for the InterTradeGaps Δt + Δrate table. Verifies
// computation against fixtures + sort order + empty/single-element
// handling.
import { describe, expect, it } from '@jest/globals'
import { renderToStaticMarkup } from 'react-dom/server'
import { computeInterTradeGaps, InterTradeGaps } from '../InterTradeGaps'
import type { FocusedTrade } from '../analytics-types'

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

describe('computeInterTradeGaps', () => {
  it('returns an empty array for an empty sequence', () => {
    expect(computeInterTradeGaps([])).toEqual([])
  })

  it('returns an empty array for a single-trade sequence (no consecutive pairs)', () => {
    expect(computeInterTradeGaps([focused({ id: 'A' })])).toEqual([])
  })

  it('computes Δt (ms) and Δrate (bps) between consecutive executions', () => {
    const gaps = computeInterTradeGaps([
      focused({ id: 'A', execution_start: '2026-04-23T09:00:00Z', fixed_rate_bps: 380 }),
      focused({ id: 'B', execution_start: '2026-04-23T09:30:00Z', fixed_rate_bps: 385 }),
      focused({ id: 'C', execution_start: '2026-04-23T10:00:00Z', fixed_rate_bps: 388 }),
    ])
    expect(gaps).toHaveLength(2)
    expect(gaps[0]).toMatchObject({ fromId: 'A', toId: 'B', deltaMs: 30 * 60_000, deltaRateBps: 5 })
    expect(gaps[1]).toMatchObject({ fromId: 'B', toId: 'C', deltaMs: 30 * 60_000, deltaRateBps: 3 })
  })

  it('sorts the input by execution_start ascending before pairing', () => {
    const gaps = computeInterTradeGaps([
      focused({ id: 'late', execution_start: '2026-04-23T10:00:00Z', fixed_rate_bps: 388 }),
      focused({ id: 'early', execution_start: '2026-04-23T09:00:00Z', fixed_rate_bps: 380 }),
    ])
    expect(gaps).toHaveLength(1)
    expect(gaps[0].fromId).toBe('early')
    expect(gaps[0].toId).toBe('late')
  })

  it('drops trades with a missing execution_start from the pairing', () => {
    const gaps = computeInterTradeGaps([
      focused({ id: 'A', execution_start: '2026-04-23T09:00:00Z' }),
      focused({ id: 'no-ts', execution_start: null }),
      focused({ id: 'B', execution_start: '2026-04-23T09:30:00Z' }),
    ])
    expect(gaps).toHaveLength(1)
    expect(gaps[0].fromId).toBe('A')
    expect(gaps[0].toId).toBe('B')
  })
})

describe('InterTradeGaps render', () => {
  it('renders a row per gap with from/to id, Δt, and Δrate', () => {
    const html = renderToStaticMarkup(
      <InterTradeGaps
        sequence={[
          focused({ id: 'A', execution_start: '2026-04-23T09:00:00Z', fixed_rate_bps: 380 }),
          focused({ id: 'B', execution_start: '2026-04-23T09:30:00Z', fixed_rate_bps: 385 }),
        ]}
      />,
    )
    expect(html).toContain('From')
    expect(html).toContain('To')
    expect(html).toMatch(/Δt|Delta\s*t|Time gap/i)
    expect(html).toMatch(/Δrate|Delta\s*rate|Rate gap/i)
    // Two row fields rendered.
    expect(html).toContain('A')
    expect(html).toContain('B')
  })

  it('renders an empty-state for sequences with no gaps', () => {
    const html = renderToStaticMarkup(
      <InterTradeGaps sequence={[focused({ id: 'A' })]} />,
    )
    expect(html).toMatch(/No gaps|need at least 2/i)
  })
})
