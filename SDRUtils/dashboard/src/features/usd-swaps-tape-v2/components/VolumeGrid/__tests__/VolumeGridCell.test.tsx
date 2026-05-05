import { describe, expect, it } from '@jest/globals'
import { renderToStaticMarkup } from 'react-dom/server'
import { VolumeGridCell, fmtCompact } from '../VolumeGridCell'
import type {
  VolumeGridCell as Cell,
  VolumeGridSchemaAxis,
} from '../../../types/volume-grid.types'

const baseCell: Cell = {
  fwd: 'spot',
  tenor: '5y',
  current: 1_200_000_000,
  idbCurrent: 480_000_000,
  custyCurrent: 720_000_000,
  tradeCount: 12,
  baseline: { p25: 0, p50: 5e8, p75: 1e9, min: 0, max: 2e9, n: 90 },
  percentile: 88,
}

const fwdAxis: VolumeGridSchemaAxis = {
  id: 'default',
  label: 'Default',
  buckets: [{ id: 'spot', label: 'Spot' }],
}
const tenorAxis: VolumeGridSchemaAxis = {
  id: 'default',
  label: 'Default',
  buckets: [{ id: '5y', label: '5Y' }],
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
      <VolumeGridCell
        cell={baseCell} metric="notional" period="today" viewMode="volume"
        forwardAxis={fwdAxis} tenorAxis={tenorAxis}
        onClick={() => {}}
      />,
    )
    expect(html).toMatch(/1\.2B/)
    expect(html).toMatch(/P88/)
  })

  it('disables itself when tradeCount is zero', () => {
    const html = renderToStaticMarkup(
      <VolumeGridCell
        cell={{ ...baseCell, tradeCount: 0, percentile: null, current: 0, idbCurrent: 0, custyCurrent: 0 }}
        metric="notional" period="today" viewMode="volume"
        forwardAxis={fwdAxis} tenorAxis={tenorAxis}
        onClick={() => {}}
      />,
    )
    expect(html).toMatch(/disabled/)
    expect(html).toMatch(/aria-disabled="true"/)
  })

  it('uses axis-resolved labels in the aria-label', () => {
    const html = renderToStaticMarkup(
      <VolumeGridCell
        cell={baseCell} metric="notional" period="today" viewMode="volume"
        forwardAxis={fwdAxis} tenorAxis={tenorAxis}
        onClick={() => {}}
      />,
    )
    expect(html).toMatch(/aria-label="[^"]*Spot[^"]*5Y[^"]*88th percentile/i)
  })

  it('aria-label cites period-specific phrasing', () => {
    const todayHtml = renderToStaticMarkup(
      <VolumeGridCell
        cell={baseCell} metric="notional" period="today" viewMode="volume"
        forwardAxis={fwdAxis} tenorAxis={tenorAxis}
        onClick={() => {}}
      />,
    )
    expect(todayHtml).toMatch(/same time-of-day/i)

    const hourHtml = renderToStaticMarkup(
      <VolumeGridCell
        cell={baseCell} metric="notional" period="1h" viewMode="volume"
        forwardAxis={fwdAxis} tenorAxis={tenorAxis}
        onClick={() => {}}
      />,
    )
    expect(hourHtml).toMatch(/same 1h slot/i)
  })

  it('renders IDB/CUSTY split percentages in idb_custy view mode', () => {
    const html = renderToStaticMarkup(
      <VolumeGridCell
        cell={baseCell} metric="notional" period="today" viewMode="idb_custy"
        forwardAxis={fwdAxis} tenorAxis={tenorAxis}
        onClick={() => {}}
      />,
    )
    // 480M / 1.2B = 40%, 720M / 1.2B = 60%
    expect(html).toMatch(/>40</)
    expect(html).toMatch(/>60</)
    // bar widths reflect the share
    expect(html).toMatch(/width:40%/)
    expect(html).toMatch(/width:60%/)
  })

  it('reverts to volume layout in volume view mode (no split bar)', () => {
    const html = renderToStaticMarkup(
      <VolumeGridCell
        cell={baseCell} metric="notional" period="today" viewMode="volume"
        forwardAxis={fwdAxis} tenorAxis={tenorAxis}
        onClick={() => {}}
      />,
    )
    expect(html).toMatch(/P88/)
    expect(html).not.toMatch(/width:40%/)
  })

  it('renders dash glyph for empty cells', () => {
    const html = renderToStaticMarkup(
      <VolumeGridCell
        cell={{ ...baseCell, tradeCount: 0, percentile: null, current: 0, idbCurrent: 0, custyCurrent: 0 }}
        metric="notional" period="today" viewMode="volume"
        forwardAxis={fwdAxis} tenorAxis={tenorAxis}
        onClick={() => {}}
      />,
    )
    expect(html).toMatch(/—/)
  })
})
