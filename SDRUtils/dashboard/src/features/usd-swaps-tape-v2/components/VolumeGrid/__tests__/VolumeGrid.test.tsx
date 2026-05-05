import { describe, expect, it } from '@jest/globals'
import { renderToStaticMarkup } from 'react-dom/server'
import { VolumeGrid } from '../VolumeGrid'
import type { VolumeGridResponse } from '../../../types/volume-grid.types'

const fixture: VolumeGridResponse = {
  asOf: '2026-05-05T14:32:00Z',
  metric: 'notional',
  period: 'today',
  lookbackDays: 90,
  cells: [
    { fwd: 'spot', tenor: '5y', current: 1e9, tradeCount: 5,
      baseline: { p25: 1e8, p50: 5e8, p75: 9e8, min: 0, max: 1.2e9, n: 90 },
      percentile: 88 },
  ],
  totals: {
    rowTotals: { spot: { current: 1e9, percentile: 88 } },
    colTotals: { '5y': { current: 1e9, percentile: 88 } },
    grand: { current: 1e9, percentile: 88 },
  },
}

describe('<VolumeGrid>', () => {
  it('renders 5 forward rows + total row + 11 tenor cols + total col', () => {
    const html = renderToStaticMarkup(
      <VolumeGrid data={fixture} metric="notional" period="today" onCellClick={() => {}} />,
    )
    const rowLabelMatches = html.match(/data-testid="volume-grid-row-label"/g) ?? []
    const colLabelMatches = html.match(/data-testid="volume-grid-col-label"/g) ?? []
    const cellMatches = html.match(/data-testid="volume-grid-cell"/g) ?? []
    expect(rowLabelMatches.length).toBe(6)
    expect(colLabelMatches.length).toBe(12)
    expect(cellMatches.length).toBe(55)
  })

  it('renders the populated 1.0B cell with the correct percentile badge', () => {
    const html = renderToStaticMarkup(
      <VolumeGrid data={fixture} metric="notional" period="today" onCellClick={() => {}} />,
    )
    expect(html).toMatch(/1\.0B/)
    expect(html).toMatch(/P88/)
  })

  it('renders all tenor labels in order', () => {
    const html = renderToStaticMarkup(
      <VolumeGrid data={fixture} metric="notional" period="today" onCellClick={() => {}} />,
    )
    expect(html).toMatch(/>1y</)
    expect(html).toMatch(/>50y</)
  })
})
