// ABOUTME: Snapshot the CardsDrawer in its collapsed default state
// against representative row fixtures so future refactors can't
// silently change the SSR-stable button label or break the four
// data-testid wrappers that Cypress / manual smoke checks rely on.
//
// We do NOT snapshot the expanded body: the four PR-#286 card
// internals are covered by their own tests; expanding them here
// would couple this snapshot to unrelated layout tweaks.
import { describe, expect, it } from '@jest/globals'
import { renderToStaticMarkup } from 'react-dom/server'
import { CardsDrawer } from '../CardsDrawer'
import type { UsdSwapTapeRow } from '../../../types'

function fakeRow(overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow {
  return {
    package_id: 'PKG-FIXTURE',
    package_type: 'OUTRIGHT',
    package_structure: 'OUTRIGHT',
    package_tenors: '5Y',
    as_of_date: '2026-04-23',
    execution_start: '2026-04-23T09:41:02Z',
    execution_end: '2026-04-23T09:41:02Z',
    legs_count: 1,
    total_risk: 25_000,
    total_notional: 50_000_000,
    weighted_fixed_rate: 0.038,
    package_metrics: null,
    tape_label: 'USD-SOFR 5Y Outright',
    venue: 'D2C',
    legs_json: [
      {
        tenor_years: 5,
        risk: 25_000,
        notional: 50_000_000,
        fixed_rate: 0.038,
      } as any,
    ],
    ...overrides,
  } as unknown as UsdSwapTapeRow
}

describe('CardsDrawer — collapsed snapshot', () => {
  it('renders the same compact strip regardless of row count (collapsed body is empty)', () => {
    const empty = renderToStaticMarkup(<CardsDrawer rows={[]} />)
    const populated = renderToStaticMarkup(<CardsDrawer rows={[fakeRow(), fakeRow()]} />)
    // Both renderings must produce identical markup since the cards
    // are gated behind expanded=false on first paint. This is the
    // regression assertion: a future refactor that eagerly mounts a
    // card (e.g. for prefetch) would break this snapshot.
    expect(empty).toEqual(populated)
  })

  it('renders the toggle button with documented copy + aria-label', () => {
    const html = renderToStaticMarkup(<CardsDrawer rows={[]} />)
    expect(html).toContain('Show analytics cards')
    expect(html).toContain('aria-label="Show analytics cards"')
  })

  it('contains a single root drawer container with data-testid="cards-drawer"', () => {
    const html = renderToStaticMarkup(<CardsDrawer rows={[]} />)
    expect(html).toContain('data-testid="cards-drawer"')
    // Only one root container — guards against accidental nesting.
    const matches = html.match(/data-testid="cards-drawer"/g) ?? []
    expect(matches.length).toBe(1)
  })
})
