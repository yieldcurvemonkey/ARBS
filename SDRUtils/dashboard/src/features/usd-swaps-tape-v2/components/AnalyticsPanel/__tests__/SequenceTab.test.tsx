// ABOUTME: Tests for the SequenceTab assembly. Verifies the tab
// renders all five sub-surfaces: aggregate summary card, timeline,
// inter-trade gaps, chain detector, and lifecycle context strip,
// plus the allocation-chain stub empty state.
import { describe, expect, it } from '@jest/globals'
import { renderToStaticMarkup } from 'react-dom/server'
import { SequenceTab } from '../SequenceTab'
import type {
  FocusedTrade,
  SequenceAggregate,
} from '../analytics-types'
import type { UsdSwapTapeRow } from '../../../types'

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

function row(overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow {
  return {
    package_id: 'PKG-A',
    package_type: 'OUTRIGHT',
    legs_json: [],
    ...overrides,
  } as unknown as UsdSwapTapeRow
}

const aggFixture: SequenceAggregate = {
  count: 2,
  totalDv01Usd: 50_000,
  weightedFixedRateBps: 382.5,
  totalNotionalUsd: 100_000_000,
  timeSpanMs: 30 * 60_000,
  startTs: '2026-04-23T09:00:00Z',
  endTs: '2026-04-23T09:30:00Z',
  sideMix: { pay: 1, rcv: 1 },
  venueMix: { BBSF: 1, TWSF: 1 },
}

describe('SequenceTab', () => {
  const seq: FocusedTrade[] = [
    focused({ id: 'PKG-A', execution_start: '2026-04-23T09:00:00Z' }),
    focused({ id: 'PKG-B', execution_start: '2026-04-23T09:30:00Z', side: 'RCV', venue: 'TWSF' }),
  ]
  const rows: UsdSwapTapeRow[] = [
    row({ package_id: 'PKG-A' }),
    row({ package_id: 'PKG-B' }),
  ]

  it('renders the aggregate summary card with sequence headline metrics', () => {
    const html = renderToStaticMarkup(
      <SequenceTab sequence={seq} rows={rows} aggregate={aggFixture} />,
    )
    expect(html).toContain('Sequence summary')
    // Count
    expect(html).toMatch(/2/)
    // Weighted rate (bps)
    expect(html).toMatch(/382\.5/)
  })

  it('renders the SequenceTimeline marker strip', () => {
    const html = renderToStaticMarkup(
      <SequenceTab sequence={seq} rows={rows} aggregate={aggFixture} />,
    )
    expect(html).toContain('data-testid="sequence-timeline"')
  })

  it('renders the InterTradeGaps table', () => {
    const html = renderToStaticMarkup(
      <SequenceTab sequence={seq} rows={rows} aggregate={aggFixture} />,
    )
    expect(html).toContain('data-testid="inter-trade-gaps"')
  })

  it('renders the SequenceChainDetector (or its empty state)', () => {
    const html = renderToStaticMarkup(
      <SequenceTab sequence={seq} rows={rows} aggregate={aggFixture} />,
    )
    // Either the populated detector or the empty-state node.
    expect(html).toMatch(/data-testid="sequence-chain-detector(?:-empty)?"/)
  })

  it('renders the lifecycle context strip', () => {
    const html = renderToStaticMarkup(
      <SequenceTab sequence={seq} rows={rows} aggregate={aggFixture} />,
    )
    expect(html).toContain('data-testid="lifecycle-context-strip"')
  })

  it('renders the allocation-chain stub empty state', () => {
    const html = renderToStaticMarkup(
      <SequenceTab sequence={seq} rows={rows} aggregate={aggFixture} />,
    )
    expect(html).toContain('data-testid="allocation-chain-stub"')
    expect(html).toMatch(/Allocation chain|prior_uti/i)
  })
})
