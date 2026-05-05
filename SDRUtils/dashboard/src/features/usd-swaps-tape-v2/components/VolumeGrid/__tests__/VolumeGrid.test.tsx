import { describe, expect, it } from '@jest/globals'
import { renderToStaticMarkup } from 'react-dom/server'
import { VolumeGrid } from '../VolumeGrid'
import type { VolumeGridResponse } from '../../../types/volume-grid.types'

const fixture: VolumeGridResponse = {
  asOf: '2026-05-05T14:32:00Z',
  metric: 'notional',
  period: 'today',
  lookbackDays: 90,
  forwardSchema: 'default',
  tenorSchema: 'default',
  packageType: 'outright',
  viewMode: 'volume',
  axes: {
    forward: {
      id: 'default',
      label: 'Default',
      buckets: [
        { id: 'spot',     label: 'Spot' },
        { id: '1w_3m',    label: '1W-3M' },
        { id: '3m_6m',    label: '3M-6M' },
        { id: '6m_1y',    label: '6M-1Y' },
        { id: '1y_2y',    label: '1Y-2Y' },
        { id: '2y_5y',    label: '2Y-5Y' },
        { id: '5y_10y',   label: '5Y-10Y' },
        { id: '10y_plus', label: '10Y+' },
      ],
    },
    tenor: {
      id: 'default',
      label: 'Default',
      buckets: [
        { id: '1m_3m',   label: '1M-3M' },
        { id: '6m_12m',  label: '6M-12M' },
        { id: '1y_18m',  label: '1Y-18M' },
        { id: '18m_2y',  label: '18M-2Y' },
        { id: '2y',      label: '2Y' },
        { id: '3y',      label: '3Y' },
        { id: '4y',      label: '4Y' },
        { id: '5y',      label: '5Y' },
        { id: '6y_7y',   label: '6Y-7Y' },
        { id: '8y_9y',   label: '8Y-9Y' },
        { id: '10y',     label: '10Y' },
        { id: '10y_12y', label: '10Y-12Y' },
        { id: '12y_15y', label: '12Y-15Y' },
        { id: '15y_20y', label: '15Y-20Y' },
        { id: '20y_25y', label: '20Y-25Y' },
        { id: '30y_plus', label: '30Y+' },
      ],
    },
  },
  cells: [
    { fwd: 'spot', tenor: '5y', current: 1e9, idbCurrent: 4e8, custyCurrent: 6e8, tradeCount: 5,
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
  it('renders 8 forward + 1 total row labels and 16 + 1 tenor col labels', () => {
    const html = renderToStaticMarkup(
      <VolumeGrid data={fixture} metric="notional" period="today" viewMode="volume" colorMode="activity" onCellClick={() => {}} />,
    )
    const rowLabelMatches = html.match(/data-testid="volume-grid-row-label"/g) ?? []
    const colLabelMatches = html.match(/data-testid="volume-grid-col-label"/g) ?? []
    const cellMatches = html.match(/data-testid="volume-grid-cell"/g) ?? []
    expect(rowLabelMatches.length).toBe(9)
    expect(colLabelMatches.length).toBe(17)
    expect(cellMatches.length).toBe(8 * 16)
  })

  it('renders the populated 1.0B cell with the correct percentile badge', () => {
    const html = renderToStaticMarkup(
      <VolumeGrid data={fixture} metric="notional" period="today" viewMode="volume" colorMode="activity" onCellClick={() => {}} />,
    )
    expect(html).toMatch(/1\.0B/)
    expect(html).toMatch(/P88/)
  })

  it('renders all tenor labels from axes payload', () => {
    const html = renderToStaticMarkup(
      <VolumeGrid data={fixture} metric="notional" period="today" viewMode="volume" colorMode="activity" onCellClick={() => {}} />,
    )
    expect(html).toMatch(/>1M-3M</)
    expect(html).toMatch(/>30Y\+</)
  })

  it('can color buckets by cross-sectional grid intensity', () => {
    const html = renderToStaticMarkup(
      <VolumeGrid data={fixture} metric="notional" period="today" viewMode="volume" colorMode="grid" onCellClick={() => {}} />,
    )
    expect(html).toMatch(/G100/)
    expect(html).toMatch(/max visible bucket/)
  })
})
