// ABOUTME: Source-string contract tests for the AnalyticsPanel
// passthrough refactor. The panel must accept `rows` + `selected`
// props alongside the legacy `focused` prop so the cards drawer (PR
// #286 cards) and sequence-mode tabs can read the loaded row set
// without lifting state into a parent context.
//
// Tests are source-string assertions because the dashboard test
// runner is `testEnvironment: node` (no jsdom). DOM-rendering
// component tests in this repo use `renderToStaticMarkup` instead;
// the props-shape tests here are intentionally lightweight.
import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const analyticsPanelSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/AnalyticsPanel/AnalyticsPanel.tsx',
  ),
  'utf8',
)

describe('AnalyticsPanel props — rows + selected passthrough', () => {
  it('declares a `rows` prop typed as a readonly UsdSwapTapeRow array', () => {
    expect(analyticsPanelSource).toMatch(
      /rows\s*:\s*readonly\s+UsdSwapTapeRow\[\]/,
    )
  })

  it('declares a `selected` prop typed as a readonly UsdSwapTapeRow array', () => {
    expect(analyticsPanelSource).toMatch(
      /selected\s*:\s*readonly\s+UsdSwapTapeRow\[\]/,
    )
  })

  it('imports the UsdSwapTapeRow type from the feature types module', () => {
    expect(analyticsPanelSource).toMatch(
      /import\s+type\s+\{[^}]*UsdSwapTapeRow[^}]*\}\s+from\s+['"](?:\.\.\/\.\.\/types|\.\.\/\.\.\/types\/?)['"]/,
    )
  })

  it('keeps the legacy focused prop for single-mode UX', () => {
    expect(analyticsPanelSource).toMatch(/focused\s*:\s*FocusedTrade\s*\|\s*null/)
  })
})

describe('AnalyticsPanel — CardsDrawer mount', () => {
  it('imports CardsDrawer from the local AnalyticsPanel module', () => {
    expect(analyticsPanelSource).toMatch(
      /import\s+\{[^}]*CardsDrawer[^}]*\}\s+from\s+['"]\.\/CardsDrawer['"]/,
    )
  })

  it('renders <CardsDrawer rows={...}/> below the tab area', () => {
    expect(analyticsPanelSource).toMatch(/<CardsDrawer\s+rows=\{[^}]*\}\s*\/>/)
  })

  it('passes the rows prop into the drawer (so cards can aggregate)', () => {
    expect(analyticsPanelSource).toMatch(/<CardsDrawer\s+rows=\{\s*(?:props\.rows|rows)\s*\}/)
  })
})

describe('AnalyticsPanel — sequence-mode branching', () => {
  it('imports deriveAnalyticsSelection from the hooks module', () => {
    expect(analyticsPanelSource).toContain('deriveAnalyticsSelection')
  })

  it('derives mode/focused/sequence from the selected prop', () => {
    expect(analyticsPanelSource).toMatch(
      /deriveAnalyticsSelection\(\s*selected\s*\)/,
    )
  })

  it('imports SequenceBar + computeSequenceAggregate', () => {
    expect(analyticsPanelSource).toContain('SequenceBar')
    expect(analyticsPanelSource).toContain('computeSequenceAggregate')
  })

  it('renders FocusedTradeBar in single mode and SequenceBar in sequence mode', () => {
    expect(analyticsPanelSource).toMatch(/mode\s*===\s*['"]single['"]/)
    expect(analyticsPanelSource).toMatch(/mode\s*===\s*['"]sequence['"]/)
    expect(analyticsPanelSource).toContain('<FocusedTradeBar')
    expect(analyticsPanelSource).toContain('<SequenceBar')
  })
})
