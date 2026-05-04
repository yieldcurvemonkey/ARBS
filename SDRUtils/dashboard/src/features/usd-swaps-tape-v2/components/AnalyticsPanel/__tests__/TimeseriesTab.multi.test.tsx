// ABOUTME: Source-string contract tests for the TimeseriesTab
// multi-overlay variant. Single-mode rendering is the existing
// FocusedTrade-driven path (covered by other tests); the multi-
// overlay path adds N reference lines + N reference dots when the
// dock is in sequence mode and a per-trade legend with show/hide
// toggles. We assert the additive code paths via source-string
// regexes since the dashboard test runner is `node` (no jsdom
// component DOM).
import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const tsTabSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/AnalyticsPanel/TimeseriesTab.tsx',
  ),
  'utf8',
)

describe('TimeseriesTab — multi-overlay sequence mode', () => {
  it('declares an optional sequence prop typed as FocusedTrade[]', () => {
    expect(tsTabSource).toMatch(
      /sequence\??\s*:\s*(?:readonly\s+)?FocusedTrade\[\]/,
    )
  })

  it('renders N reference lines for the sequence (one per trade)', () => {
    // Multi-overlay path iterates over the sequence (or a derived
    // alias such as `overlayTrades`) and emits one ReferenceLine per
    // trade. The map callback must reach a ReferenceLine within a
    // bounded source-lookahead.
    expect(tsTabSource).toMatch(
      /(?:sequence|overlayTrades)[^.]*\.map[\s\S]{0,500}<ReferenceLine/,
    )
  })

  it('renders N reference dots for the sequence (one per trade)', () => {
    expect(tsTabSource).toMatch(
      /(?:sequence|overlayTrades)[^.]*\.map[\s\S]{0,500}<ReferenceDot/,
    )
  })

  it('color-codes overlays by sequence index (palette indexed)', () => {
    // The sequence colour palette is exported from analytics-format
    // (or an inline array within TimeseriesTab); either way the
    // .map callback must reference an index parameter so each trade
    // gets a stable colour.
    expect(tsTabSource).toMatch(/sequence[\s\S]{0,200}\.map\(\s*\([^,)]+,\s*(?:i|idx|index)\b/)
  })

  it('renders a per-trade legend chip with show/hide toggle', () => {
    expect(tsTabSource).toMatch(/(?:hiddenTrades|hiddenTradeIds|hiddenSet)/)
    // The legend block must reference the toggle state setter.
    expect(tsTabSource).toMatch(/setHidden(?:Trades|TradeIds|Set)/)
  })

  it('preserves single-mode rendering — the existing focused-overlay code is intact', () => {
    // Pulsing dot stays for single mode; reference line still
    // renders against `focusedValue`.
    expect(tsTabSource).toContain('PulsingDot')
    expect(tsTabSource).toContain('focusedValue')
  })
})
