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
  it('omits tenor cells from the expanded legs table source', () => {
    expect(legsSubTableSource).not.toContain('>Tenor<')
    expect(legsSubTableSource).not.toContain('leg.tenor_display ?? leg.tenor_label ?? EMPTY_VALUE')
    // feedback-round-1: added OPA column → 14 <th> now.
    expect((legsSubTableSource.match(/<th /g) ?? []).length).toBe(14)
  })

  it('uses the reduced empty-state colspan after the column removal', () => {
    expect(legsSubTableSource).toContain('colSpan={14}')
  })

  it('prefers leg_tape_label over tape_label so CURVE/FLY legs show the per-leg outright description', () => {
    // The expanded row for a curve should render "5Y Outright" / "10Y Outright"
    // on each leg row, not the package-level "5Y/10Y CURVE" label. The backend
    // populates leg_tape_label per leg and keeps tape_label as the package
    // structure, so the UI must pick leg_tape_label first.
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
