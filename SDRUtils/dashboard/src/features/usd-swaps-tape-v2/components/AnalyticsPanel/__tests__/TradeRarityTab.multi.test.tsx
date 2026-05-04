// ABOUTME: Source-string contract tests for the TradeRarityTab N-
// dot overlay variant. Single-mode rendering is unchanged; sequence
// mode renders one ReferenceDot per trade overlaid on the shared
// histogram with a tooltip identifying which trade.
import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const rarityTabSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/AnalyticsPanel/TradeRarityTab.tsx',
  ),
  'utf8',
)

describe('TradeRarityTab — N-dot overlay sequence mode', () => {
  it('declares an optional sequence prop typed as FocusedTrade[]', () => {
    expect(rarityTabSource).toMatch(
      /sequence\??\s*:\s*(?:readonly\s+)?FocusedTrade\[\]/,
    )
  })

  it('iterates over the sequence to emit N reference dots', () => {
    expect(rarityTabSource).toMatch(
      /(?:sequence|overlayTrades)[^.]*\.map[\s\S]{0,400}<ReferenceDot/,
    )
  })

  it('color-codes each dot by sequence index (palette indexed)', () => {
    expect(rarityTabSource).toContain('sequenceColor')
  })

  it('preserves the focused-dot rendering for single-mode regression', () => {
    expect(rarityTabSource).toContain('focusedBin')
    expect(rarityTabSource).toContain('focusedHistogramValue')
  })
})
