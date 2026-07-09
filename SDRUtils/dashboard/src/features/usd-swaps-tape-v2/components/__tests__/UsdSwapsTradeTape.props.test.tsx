// ABOUTME: Source-string contract test pinning that
// `UsdSwapsTradeTape` plumbs the new multi-trade dock props
// (`rows`, `selected`) into `<AnalyticsPanel>` alongside the legacy
// `focused` prop. The orchestrator exposes `tape.rows` and derives
// `selectedRows` from the leg-level `useTradeSelection`; this test guards
// against future refactors that drop the wiring.
import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const orchestratorSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx',
  ),
  'utf8',
)

// Extract only the JSX block that mounts <AnalyticsPanel ... /> so
// our assertions reflect what reaches the dock and not what reaches
// the table or links dialog.
function analyticsPanelJsxBlock(src: string): string {
  const open = src.indexOf('<AnalyticsPanel')
  if (open === -1) return ''
  const close = src.indexOf('/>', open)
  if (close === -1) return ''
  return src.slice(open, close + 2)
}

describe('UsdSwapsTradeTape — AnalyticsPanel passthrough', () => {
  const block = analyticsPanelJsxBlock(orchestratorSource)

  it('locates an <AnalyticsPanel ... /> mount in the orchestrator', () => {
    expect(block).toMatch(/^<AnalyticsPanel/)
  })

  it('passes rows={tape.rows} into AnalyticsPanel', () => {
    expect(block).toMatch(/rows=\{\s*tape\.rows\s*\}/)
  })

  it('passes selected={selectedRows} into AnalyticsPanel', () => {
    expect(block).toMatch(/selected=\{\s*selectedRows\s*\}/)
  })

  it('still passes focused={focus.focused} (single-mode preserved)', () => {
    expect(block).toMatch(/focused=\{\s*focus\.focused\s*\}/)
  })
})
