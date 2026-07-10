// ABOUTME: Tests for the MMS analytics tab (matched-maturity swap /
// UST asset-swap). Uses renderToStaticMarkup (node testEnvironment).
import { describe, expect, it } from '@jest/globals'
import { renderToStaticMarkup } from 'react-dom/server'
import { MmsTab } from '../MmsTab'
import type { UsdSwapTapeRow } from '../../../types'
import { MMS_DEFAULT_STATE } from '../constants'

function mmsRow(date: string): UsdSwapTapeRow {
  return {
    package_id: `mms-${date}`,
    as_of_date: date,
    execution_start: `${date}T16:00:00Z`,
    execution_end: `${date}T16:00:00Z`,
    legs_count: 2,
    package_metrics: null,
    package_type: 'MATCHED_MATURITY_CURVE',
    is_matched_maturity_all: true,
    total_risk: 80000,
    total_notional: 20_000_000,
    tape_label_ust_alias: 'USD-SOFR Spot 0536/0546 CURVE MMS PHYS',
    legs_json: [
      { matched_ust_maturity: true, ust_cusip: '91282CQQ7', tape_label_ust_alias: '0536' },
      { matched_ust_maturity: true, ust_cusip: '912810UV8', tape_label_ust_alias: '0546' },
    ],
  } as UsdSwapTapeRow
}

function nonMmsRow(date: string): UsdSwapTapeRow {
  return {
    package_id: `non-mms-${date}`,
    as_of_date: date,
    execution_start: `${date}T14:00:00Z`,
    execution_end: `${date}T14:00:00Z`,
    legs_count: 1,
    package_metrics: null,
    package_type: 'OUTRIGHT',
    is_matched_maturity_all: false,
    total_risk: 50000,
    total_notional: 10_000_000,
    legs_json: [],
  } as UsdSwapTapeRow
}

describe('MmsTab', () => {
  it('renders summary stats when MMS rows exist', () => {
    const html = renderToStaticMarkup(
      <MmsTab
        rows={[mmsRow('2026-07-08'), mmsRow('2026-07-09'), nonMmsRow('2026-07-08')]}
        state={MMS_DEFAULT_STATE}
        setState={() => {}}
      />,
    )
    expect(html).toContain('MMS Packages')
    // 2 MMS rows out of 3 total
    expect(html).toContain('>2<')
  })

  it('renders empty state when no rows are provided', () => {
    const html = renderToStaticMarkup(
      <MmsTab rows={[]} state={MMS_DEFAULT_STATE} setState={() => {}} />,
    )
    expect(html).toMatch(/[Nn]o MMS/)
  })

  it('renders empty state when no MMS rows exist in a non-empty dataset', () => {
    const html = renderToStaticMarkup(
      <MmsTab
        rows={[nonMmsRow('2026-07-08')]}
        state={MMS_DEFAULT_STATE}
        setState={() => {}}
      />,
    )
    expect(html).toMatch(/[Nn]o MMS/)
  })

  it('renders window selector pills', () => {
    const html = renderToStaticMarkup(
      <MmsTab
        rows={[mmsRow('2026-07-08')]}
        state={MMS_DEFAULT_STATE}
        setState={() => {}}
      />,
    )
    expect(html).toContain('Today')
    expect(html).toContain('7D')
    expect(html).toContain('30D')
    expect(html).toContain('90D')
    expect(html).toContain('YTD')
  })

  it('renders the top CUSIPs section heading', () => {
    const html = renderToStaticMarkup(
      <MmsTab
        rows={[mmsRow('2026-07-08')]}
        state={MMS_DEFAULT_STATE}
        setState={() => {}}
      />,
    )
    expect(html).toContain('Top CUSIPs')
  })

  it('renders CUSIP identifiers from the row data', () => {
    const html = renderToStaticMarkup(
      <MmsTab
        rows={[mmsRow('2026-07-08')]}
        state={MMS_DEFAULT_STATE}
        setState={() => {}}
      />,
    )
    expect(html).toContain('91282CQQ7')
    expect(html).toContain('912810UV8')
  })
})
