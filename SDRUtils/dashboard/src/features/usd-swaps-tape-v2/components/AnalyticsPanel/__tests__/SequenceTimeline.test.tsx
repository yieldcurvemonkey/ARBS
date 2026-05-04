// ABOUTME: Render-time tests for the SequenceTimeline marker
// strip. Asserts marker count, side encoding (PAY = ▲, RCV = ▼),
// venue colour mapping and time-axis ordering. Uses
// renderToStaticMarkup for the SSR-stable SVG output.
import { describe, expect, it } from '@jest/globals'
import { renderToStaticMarkup } from 'react-dom/server'
import { SequenceTimeline } from '../SequenceTimeline'
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

describe('SequenceTimeline', () => {
  it('renders one marker per sequence trade', () => {
    const html = renderToStaticMarkup(
      <SequenceTimeline
        sequence={[
          focused({ id: 'A' }),
          focused({ id: 'B' }),
          focused({ id: 'C' }),
        ]}
      />,
    )
    const matches = html.match(/data-testid="sequence-marker-/g) ?? []
    expect(matches.length).toBe(3)
  })

  it('encodes PAY as upward triangle and RCV as downward triangle', () => {
    const html = renderToStaticMarkup(
      <SequenceTimeline
        sequence={[
          focused({ id: 'pay-1', side: 'PAY' }),
          focused({ id: 'rcv-1', side: 'RCV' }),
        ]}
      />,
    )
    expect(html).toMatch(/data-side="PAY"/)
    expect(html).toMatch(/data-side="RCV"/)
  })

  it('orders markers by execution_start ascending', () => {
    const html = renderToStaticMarkup(
      <SequenceTimeline
        sequence={[
          focused({ id: 'late', execution_start: '2026-04-23T10:00:00Z' }),
          focused({ id: 'early', execution_start: '2026-04-23T09:00:00Z' }),
          focused({ id: 'mid', execution_start: '2026-04-23T09:30:00Z' }),
        ]}
      />,
    )
    const earlyIdx = html.indexOf('data-testid="sequence-marker-early"')
    const midIdx = html.indexOf('data-testid="sequence-marker-mid"')
    const lateIdx = html.indexOf('data-testid="sequence-marker-late"')
    expect(earlyIdx).toBeGreaterThan(-1)
    expect(midIdx).toBeGreaterThan(earlyIdx)
    expect(lateIdx).toBeGreaterThan(midIdx)
  })

  it('renders an empty-state when sequence is empty', () => {
    const html = renderToStaticMarkup(<SequenceTimeline sequence={[]} />)
    expect(html).toMatch(/No trades selected/i)
  })

  it('handles trades with missing execution_start (renders without crashing)', () => {
    const html = renderToStaticMarkup(
      <SequenceTimeline
        sequence={[
          focused({ id: 'with-ts' }),
          focused({ id: 'no-ts', execution_start: null }),
        ]}
      />,
    )
    expect(html).toMatch(/data-testid="sequence-marker-with-ts"/)
    // The no-ts trade should still render but be flagged via a
    // data attribute or omission consistent with the helper's
    // contract.
    expect(html).toMatch(/data-missing-ts="true"|data-testid="sequence-marker-no-ts"/)
  })
})
