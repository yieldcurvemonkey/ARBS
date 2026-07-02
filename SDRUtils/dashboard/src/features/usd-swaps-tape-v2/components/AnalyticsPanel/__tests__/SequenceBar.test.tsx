// ABOUTME: Render-time tests for SequenceBar — the multi-trade
// equivalent of FocusedTradeBar. Uses renderToStaticMarkup against
// a deterministic SequenceAggregate fixture so we can assert the
// count chip, aggregate DV01 / weighted rate / notional / time
// span / side mix / venue mix cells, and the clear button.
import { describe, expect, it } from '@jest/globals'
import { renderToStaticMarkup } from 'react-dom/server'
import { SequenceBar } from '../SequenceBar'
import type {
  FocusedTrade,
  SequenceAggregate,
} from '../analytics-types'

function focused(overrides: Partial<FocusedTrade> = {}): FocusedTrade {
  return {
    id: 'PKG-FIXTURE',
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
    execution_start: '2026-04-23T09:41:00Z',
    execution_session: 'AM',
    lifecycle_type: 'NEW_RISK',
    is_block: false,
    ...overrides,
  }
}

const aggFixture: SequenceAggregate = {
  count: 3,
  totalDv01Usd: 75_000,
  weightedFixedRateBps: 384.2,
  totalNotionalUsd: 150_000_000,
  timeSpanMs: 90 * 60_000, // 90 minutes
  startTs: '2026-04-23T09:00:00Z',
  endTs: '2026-04-23T10:30:00Z',
  sideMix: { pay: 2, rcv: 1 },
  venueMix: { TWSF: 1, BBSF: 2 },
}

describe('SequenceBar', () => {
  it('renders the count chip', () => {
    const html = renderToStaticMarkup(
      <SequenceBar
        sequence={[focused(), focused(), focused()]}
        aggregate={aggFixture}
        onClear={() => {}}
      />,
    )
    expect(html).toMatch(/Sequence \(3\)/)
  })

  it('renders aggregate DV01 / weighted rate / notional / time span', () => {
    const html = renderToStaticMarkup(
      <SequenceBar
        sequence={[focused(), focused(), focused()]}
        aggregate={aggFixture}
        onClear={() => {}}
      />,
    )
    // DV01 — fmtDv01Compact("75K"), permit either 75K or 75,000
    expect(html).toMatch(/(75K|75,000)/)
    // Weighted rate in bps — match "384.2" or "384.20"
    expect(html).toMatch(/384\.2/)
    // Total notional — 150 MM
    expect(html).toMatch(/150/)
    // Time span — 90 minutes
    expect(html).toMatch(/(90m|90\s*min|01:30|1h\s*30m)/)
  })

  it('renders side mix as PAY/RCV chip', () => {
    const html = renderToStaticMarkup(
      <SequenceBar
        sequence={[focused(), focused(), focused()]}
        aggregate={aggFixture}
        onClear={() => {}}
      />,
    )
    expect(html).toMatch(/2\s*PAY/)
    expect(html).toMatch(/1\s*RCV/)
  })

  it('renders venue mix chips for each unique venue', () => {
    const html = renderToStaticMarkup(
      <SequenceBar
        sequence={[focused(), focused(), focused()]}
        aggregate={aggFixture}
        onClear={() => {}}
      />,
    )
    expect(html).toMatch(/TWSF/)
    expect(html).toMatch(/BBSF/)
  })

  it('renders a clear button', () => {
    const html = renderToStaticMarkup(
      <SequenceBar
        sequence={[focused(), focused()]}
        aggregate={{ ...aggFixture, count: 2, sideMix: { pay: 1, rcv: 1 } }}
        onClear={() => {}}
      />,
    )
    // The button copy follows FocusedTradeBar's "Clear" cadence.
    expect(html).toMatch(/Clear/)
  })

  it('renders the soft-cap warning chip when warning prop is supplied', () => {
    const html = renderToStaticMarkup(
      <SequenceBar
        sequence={[focused()]}
        aggregate={{ ...aggFixture, count: 25 }}
        onClear={() => {}}
        warning="Selection capped at 20 (25 selected)"
      />,
    )
    expect(html).toMatch(/Selection capped at 20/)
    expect(html).toMatch(/⚠/)
  })

  it('omits the warning chip when warning prop is null', () => {
    const html = renderToStaticMarkup(
      <SequenceBar
        sequence={[focused(), focused()]}
        aggregate={{ ...aggFixture, count: 2 }}
        onClear={() => {}}
        warning={null}
      />,
    )
    expect(html).not.toMatch(/Selection capped at/)
  })

  it('handles a zero-time-span sequence (all execution_start equal)', () => {
    const html = renderToStaticMarkup(
      <SequenceBar
        sequence={[focused(), focused()]}
        aggregate={{
          ...aggFixture,
          count: 2,
          timeSpanMs: 0,
          startTs: '2026-04-23T09:00:00Z',
          endTs: '2026-04-23T09:00:00Z',
          sideMix: { pay: 2, rcv: 0 },
        }}
        onClear={() => {}}
      />,
    )
    // Zero span renders as "0m" or "—" — either is acceptable, just
    // assert it doesn't crash and the count is right.
    expect(html).toMatch(/Sequence \(2\)/)
  })
})
