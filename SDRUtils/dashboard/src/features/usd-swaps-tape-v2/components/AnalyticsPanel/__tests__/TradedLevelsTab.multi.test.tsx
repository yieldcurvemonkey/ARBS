// ABOUTME: Source-string contract tests for the TradedLevelsTab
// side-by-side / aggregated toggle in sequence mode. Single-mode
// rendering is unchanged. The toggle state persists to localStorage
// under a documented key so the trader's preference survives reload.
import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const levelsTabSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/AnalyticsPanel/TradedLevelsTab.tsx',
  ),
  'utf8',
)

describe('TradedLevelsTab — side-by-side / aggregated toggle', () => {
  it('declares an optional sequence prop typed as FocusedTrade[]', () => {
    expect(levelsTabSource).toMatch(
      /sequence\??\s*:\s*(?:readonly\s+)?FocusedTrade\[\]/,
    )
  })

  it('exposes a side-by-side / aggregated toggle (state name documents intent)', () => {
    expect(levelsTabSource).toMatch(/side-by-side/)
    expect(levelsTabSource).toMatch(/aggregated/)
  })

  it('persists the toggle state to localStorage under levels-multi-view', () => {
    expect(levelsTabSource).toMatch(/levels-multi-view/)
    expect(levelsTabSource).toMatch(/localStorage/)
  })

  it('renders a side-by-side N-column table when in sequence mode + side-by-side view', () => {
    // The side-by-side path must reference the sequence so a column
    // is generated per trade. We assert the source-string contract
    // here; behaviour-level checks live in the helpers test once a
    // jsdom environment is added.
    expect(levelsTabSource).toMatch(
      /(?:sequence|overlayTrades|sequenceForLevels)[^.]*\.map[\s\S]{0,500}<th/,
    )
  })

  it('renders an aggregated extremes view scoped to the selection union', () => {
    // The aggregated view must reference the sequence to compute
    // the union of rates / DV01 / notional bounds.
    expect(levelsTabSource).toMatch(/aggregated[\s\S]{0,500}sequence/i)
  })

  it('preserves the existing single-mode tables when sequence is undefined', () => {
    expect(levelsTabSource).toContain('filteredExtremes')
    expect(levelsTabSource).toContain('recentSimilar')
  })
})
