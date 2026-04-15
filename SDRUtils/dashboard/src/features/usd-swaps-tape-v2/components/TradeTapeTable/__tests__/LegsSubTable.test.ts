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
    expect((legsSubTableSource.match(/<th /g) ?? []).length).toBe(13)
  })

  it('uses the reduced empty-state colspan after the column removal', () => {
    expect(legsSubTableSource).toContain('colSpan={13}')
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
