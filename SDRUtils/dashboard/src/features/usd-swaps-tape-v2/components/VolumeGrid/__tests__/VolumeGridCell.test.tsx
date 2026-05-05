import { describe, expect, it } from '@jest/globals'
import { renderToStaticMarkup } from 'react-dom/server'
import { VolumeGridCell, fmtCompact } from '../VolumeGridCell'
import type { VolumeGridCell as Cell } from '../../../types/volume-grid.types'

const baseCell: Cell = {
  fwd: 'spot',
  tenor: '5y',
  current: 1_200_000_000,
  tradeCount: 12,
  baseline: { p25: 0, p50: 5e8, p75: 1e9, min: 0, max: 2e9, n: 90 },
  percentile: 88,
}

describe('fmtCompact', () => {
  it('formats billions', () => expect(fmtCompact(1_200_000_000, 'notional')).toBe('1.2B'))
  it('formats millions', () => expect(fmtCompact(45_000_000, 'notional')).toBe('45.0M'))
  it('formats thousands', () => expect(fmtCompact(48_000, 'dv01')).toBe('48k'))
  it('formats negatives', () => expect(fmtCompact(-1.5e9, 'notional')).toBe('-1.5B'))
})

describe('<VolumeGridCell>', () => {
  it('renders the formatted current value and percentile badge', () => {
    const html = renderToStaticMarkup(
      <VolumeGridCell cell={baseCell} metric="notional" period="today" onClick={() => {}} />,
    )
    expect(html).toMatch(/1\.2B/)
    expect(html).toMatch(/P88/)
  })

  it('disables itself when tradeCount is zero', () => {
    const html = renderToStaticMarkup(
      <VolumeGridCell
        cell={{ ...baseCell, tradeCount: 0, percentile: null, current: 0 }}
        metric="notional" period="today" onClick={() => {}}
      />,
    )
    expect(html).toMatch(/disabled/)
    expect(html).toMatch(/aria-disabled="true"/)
  })

  it('exposes a descriptive aria-label', () => {
    const html = renderToStaticMarkup(
      <VolumeGridCell cell={baseCell} metric="notional" period="today" onClick={() => {}} />,
    )
    expect(html).toMatch(/aria-label="[^"]*spot[^"]*5y[^"]*88th percentile/i)
  })

  it('aria-label cites the period-specific comparison phrasing', () => {
    const todayHtml = renderToStaticMarkup(
      <VolumeGridCell cell={baseCell} metric="notional" period="today" onClick={() => {}} />,
    )
    expect(todayHtml).toMatch(/same time-of-day/i)

    const hourHtml = renderToStaticMarkup(
      <VolumeGridCell cell={baseCell} metric="notional" period="1h" onClick={() => {}} />,
    )
    expect(hourHtml).toMatch(/same 1h slot/i)

    const weekHtml = renderToStaticMarkup(
      <VolumeGridCell cell={baseCell} metric="notional" period="1w" onClick={() => {}} />,
    )
    expect(weekHtml).toMatch(/prior weeks/i)
  })

  it('renders a dash glyph for empty cells', () => {
    const html = renderToStaticMarkup(
      <VolumeGridCell
        cell={{ ...baseCell, tradeCount: 0, percentile: null, current: 0 }}
        metric="notional" period="today" onClick={() => {}}
      />,
    )
    expect(html).toMatch(/—/)
  })
})
