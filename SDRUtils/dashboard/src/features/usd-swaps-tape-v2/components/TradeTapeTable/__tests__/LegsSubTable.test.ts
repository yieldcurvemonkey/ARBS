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
    // 14 baseline columns + Phase 3 Class + Phase 1 Exec Ts = 16
    expect((legsSubTableSource.match(/<th /g) ?? []).length).toBe(16)
  })

  it('uses the reduced empty-state colspan after the column additions', () => {
    // P3-06: colSpan now references the LEG_COL_COUNT constant so a
    // future column add can't drift the empty-state width.
    expect(legsSubTableSource).toContain('colSpan={LEG_COL_COUNT}')
    expect(legsSubTableSource).toMatch(/const LEG_COL_COUNT = 16/)
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

  it('prefers leg_tape_label over tape_label so CURVE/FLY legs show the per-leg outright description', () => {
    expect(legsSubTableSource).toContain('leg.leg_tape_label ?? leg.tape_label')
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

  it('sorts legs by tenor ascending so the front leg renders first', () => {
    // Defensive sort — legs_json ordering from the view is not guaranteed.
    expect(legsSubTableSource).toContain('.sort(')
    expect(legsSubTableSource).toContain('tenor_years')
    // The sort comparator must produce ASC order (a - b, not b - a).
    expect(legsSubTableSource).toMatch(/return\s+at\s*-\s*bt/)
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
