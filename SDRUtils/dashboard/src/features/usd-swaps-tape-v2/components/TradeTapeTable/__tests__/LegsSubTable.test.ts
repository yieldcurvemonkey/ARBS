import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const legsSubTableSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/TradeTapeTable/LegsSubTable.tsx',
  ),
  'utf8',
)

const tradeTapeSource = readFileSync(
  resolve(process.cwd(), 'src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx'),
  'utf8',
)

describe('LegsSubTable', () => {
  it('omits tenor and duplicated top-level columns from the expanded legs table source', () => {
    expect(legsSubTableSource).not.toContain('>Tenor<')
    expect(legsSubTableSource).not.toContain('>Action<')
    expect(legsSubTableSource).not.toContain('>Time<')
    expect(legsSubTableSource).not.toContain('>Platform<')
    expect(legsSubTableSource).not.toContain(
      'leg.tenor_display ?? leg.tenor_label ?? EMPTY_VALUE',
    )
    // 14 baseline columns + Phase 3 Class + Phase 1 Exec Ts + Task 16
    // leading checkbox column = 17
    expect((legsSubTableSource.match(/<th /g) ?? []).length).toBe(17)
  })

  it('uses the reduced empty-state colspan after the column additions', () => {
    // P3-06: colSpan now references the LEG_COL_COUNT constant so a
    // future column add can't drift the empty-state width.
    expect(legsSubTableSource).toContain('colSpan={LEG_COL_COUNT}')
    expect(legsSubTableSource).toMatch(/const LEG_COL_COUNT = 17/)
  })

  it('surfaces the Phase 3 Class column for the matrix kind', () => {
    expect(legsSubTableSource).toContain('>Class<')
  })

  it('surfaces the Phase 1 Exec Ts column with original/clearing-accept split', () => {
    expect(legsSubTableSource).toContain('>Exec Ts<')
    expect(legsSubTableSource).toContain('execTimestampPair')
  })

  it('surfaces the per-leg Cleared status column', () => {
    expect(legsSubTableSource).toContain('>Cleared<')
    expect(legsSubTableSource).toContain('leg.cleared')
  })

  it('uses perLegLabel helper for per-leg tape label (handles fallback + derivation)', () => {
    expect(legsSubTableSource).toContain('perLegLabel(leg)')
    expect(legsSubTableSource).toContain("import { perLegLabel")
  })

  it('renders a Package Transaction Price header strip guarded on PTP not-null', () => {
    expect(legsSubTableSource).toContain('Package Transaction Price')
    expect(legsSubTableSource).toContain('row.package_transaction_price != null')
  })

  it('renders a per-leg OPA column in the expanded leg table', () => {
    expect(legsSubTableSource).toContain('>OPA<')
    expect(legsSubTableSource).toContain('leg.other_payment_amount')
  })

  it('renames DV01 header to Risk', () => {
    expect(legsSubTableSource).not.toContain('>DV01<')
    expect(legsSubTableSource).toContain('>Risk<')
  })

  it('renders DV01 without the "+" sign prefix (no signed mode)', () => {
    // signNegativeOnly:true drops the "+" for positive values but keeps the
    // "−" for negatives. signed:true would add the "+" back — exclude it.
    expect(legsSubTableSource).not.toMatch(/formatDv01\([^)]*\{[^}]*signed:\s*true[^}]*\}\)/)
  })

  it('adds PTP + PTS columns to the expanded leg table', () => {
    expect(legsSubTableSource).toContain('>PTP<')
    expect(legsSubTableSource).toContain('>PTS<')
    // Per-leg PTP / PTS values come from the top-level package row.
    expect(legsSubTableSource).toContain('row.package_transaction_price')
    expect(legsSubTableSource).toContain('row.package_transaction_spread')
  })

  it('sorts legs with the shared structure-aware comparator', () => {
    // Structure-aware sort (leg_order with tenor-ASC fallback) — legs_json
    // ordering from the view is not guaranteed, and raw tenor sorting
    // scrambles FOMC curves / gap flies.
    expect(legsSubTableSource).toContain('sortLegsForDisplay(')
  })

  it('# column shows the post-sort row index, not the stale pre-sort leg_order', () => {
    // If `leg.leg_order` is used, the # cells can render out of order
    // (e.g. 2, 0, 1 when tenor-ASC displays 5Y/10Y/30Y). The # column
    // must reflect the row ordering so the user can cross-reference it
    // with the aggregated summary row at the bottom.
    expect(legsSubTableSource).not.toContain('leg.leg_order ?? index + 1')
    expect(legsSubTableSource).not.toContain('leg.leg_order')
  })
})

describe('UsdSwapsTradeTape', () => {
  it('does not compose the removed right rail or timeline controls', () => {
    expect(tradeTapeSource).not.toContain('SidecarDrawer')
    expect(tradeTapeSource).not.toContain('ClusterTimelineStrip')
    expect(tradeTapeSource).not.toContain('timelineVisible')
    expect(tradeTapeSource).not.toContain('Show timeline')
    expect(tradeTapeSource).not.toContain('Hide timeline')
  })
})

import { renderToStaticMarkup } from 'react-dom/server'
import { LegsSubTable } from '../LegsSubTable'

describe('LegsSubTable confidence strip', () => {
  it('renders confidence strip header (N/T) by default but hides per-signal detail until toggled', () => {
    const html = renderToStaticMarkup(
      LegsSubTable({
        row: {
          package_id: 'P-FLY',
          package_type: 'FLY',
          package_indicator: true,
          n_package_legs: 3,
          package_transaction_spread: 20,
          legs_json: [
            { tenor_years: 5, risk: -2_500, fixed_rate: 3.5, trade_id: 'L1' },
            { tenor_years: 10, risk: 5_000, fixed_rate: 3.85, trade_id: 'L2' },
            { tenor_years: 30, risk: -2_500, fixed_rate: 4.0, trade_id: 'L3' },
          ],
        } as any,
      }),
    )
    // Header chip stays visible.
    expect(html).toContain('data-testid="confidence-strip-P-FLY"')
    expect(html).toContain('5/5')
    // Toggle button is rendered with the expected label.
    expect(html).toContain('Show Package Confidence Details')
    expect(html).toContain('data-testid="confidence-toggle-P-FLY"')
    // Details list is collapsed by default — the per-signal rows are
    // not in the static markup until the user toggles the panel.
    expect(html).not.toContain('PTS match')
    expect(html).not.toContain('Risk balance')
  })

  it('does NOT surface the inferred-type override badge when the panel is collapsed (default)', () => {
    const html = renderToStaticMarkup(
      LegsSubTable({
        row: {
          package_id: 'P-OVR',
          package_type: 'SPREADOVER_FLY',
          package_indicator: true,
          n_package_legs: 3,
          package_transaction_spread: 0.0000125,
          legs_json: [
            {
              tenor_years: 8,
              risk: -1_500,
              fixed_rate: 0.03795,
              trade_id: 'L1',
              package_transaction_spread: 0.0000125,
            },
            {
              tenor_years: 9,
              risk: 3_000,
              fixed_rate: 0.03841,
              trade_id: 'L2',
              package_transaction_spread: 0.0000125,
            },
            {
              tenor_years: 10,
              risk: -1_500,
              fixed_rate: 0.03886,
              trade_id: 'L3',
              package_transaction_spread: 0.0000125,
            },
          ],
        } as any,
      }),
    )
    // Override is gated behind the "Show Package Confidence Details"
    // toggle — collapsed default markup should NOT carry the inferred
    // chip / banner. Toggle button is still visible so the user can
    // open it.
    expect(html).not.toContain('data-testid="confidence-inferred-P-OVR"')
    expect(html).not.toContain('Inferred type:')
    expect(html).toContain('(FLY)')
    expect(html).toContain('Show Package Confidence Details')
  })

  it('renders the summary derived rate in bps with extra precision (Enh 1b)', () => {
    const html = renderToStaticMarkup(
      LegsSubTable({
        row: {
          package_id: 'P-SUMMARY',
          package_type: 'FLY',
          package_indicator: true,
          n_package_legs: 3,
          legs_json: [
            { tenor_years: 8, risk: -1_500, fixed_rate: 0.03795, trade_id: 'L1' },
            { tenor_years: 9, risk: 3_000, fixed_rate: 0.0384125, trade_id: 'L2' },
            { tenor_years: 10, risk: -1_500, fixed_rate: 0.0388625, trade_id: 'L3' },
          ],
        } as any,
      }),
    )
    // Enhancement 1b: the calculated fly spread renders in bps (0.0000125
    // decimal -> 0.125bps) rather than the old "0.00125%".
    expect(html).toContain('0.125bps')
  })
})
