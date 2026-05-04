// ABOUTME: Renders the always-on cards drawer in its collapsed
// (default) state and asserts the toggle-button copy + storage-key
// contract via static markup + source-string scans. The dashboard
// test environment is `node` with no jsdom, so we cannot drive a
// click; we rely on renderToStaticMarkup for the SSR-stable initial
// state and source-string regexes for the dynamic localStorage path.
import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { renderToStaticMarkup } from 'react-dom/server'
import { CardsDrawer } from '../CardsDrawer'

const cardsDrawerSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/AnalyticsPanel/CardsDrawer.tsx',
  ),
  'utf8',
)

describe('CardsDrawer — initial collapsed render', () => {
  it('starts collapsed: only the expander button is in the static markup', () => {
    const html = renderToStaticMarkup(<CardsDrawer rows={[]} />)
    expect(html).toContain('Show analytics cards')
    // The four cards are not rendered until the drawer is expanded.
    expect(html).not.toContain('data-testid="underlier-mix-card"')
    expect(html).not.toContain('data-testid="rfr-adoption-card"')
    expect(html).not.toContain('data-testid="swap-spread-vwap-card"')
    expect(html).not.toContain('data-testid="ccp-switch-card"')
  })

  it('exposes an aria-label on the expander for accessibility', () => {
    const html = renderToStaticMarkup(<CardsDrawer rows={[]} />)
    expect(html).toMatch(/aria-label="(?:Show|Hide) analytics cards"/)
  })
})

describe('CardsDrawer — implementation contract', () => {
  it('persists expand state under the documented localStorage key', () => {
    expect(cardsDrawerSource).toMatch(/cards-drawer-expanded/)
    expect(cardsDrawerSource).toMatch(/localStorage\.setItem/)
    expect(cardsDrawerSource).toMatch(/localStorage\.getItem/)
  })

  it('mounts all four PR-#286 cards inside the expanded body', () => {
    expect(cardsDrawerSource).toMatch(/UnderlierMixCard\s+rows=/)
    expect(cardsDrawerSource).toMatch(/RfrAdoptionCard\s+rows=/)
    expect(cardsDrawerSource).toMatch(/SwapSpreadVwapCard\s+rows=/)
    expect(cardsDrawerSource).toMatch(/CcpSwitchCard\s+rows=/)
  })

  it('defaults to collapsed (expanded=false on first mount)', () => {
    // The hook init reads localStorage and falls back to false; the
    // SSR path must always start collapsed because there is no
    // localStorage on the server. Source-string scan documents that.
    expect(cardsDrawerSource).toMatch(
      /useState[^=]*=>\s*\{[\s\S]*?typeof\s+localStorage\s*===\s*['"]undefined['"][\s\S]*?return\s+false/,
    )
  })

  it('toggles expanded state via a button click handler', () => {
    expect(cardsDrawerSource).toMatch(/onClick=\{[^}]*setExpanded\(\(?v\)?\s*=>\s*!v\)/)
  })

  it('renders all four cards inside guarded data-testid wrappers', () => {
    expect(cardsDrawerSource).toContain('data-testid="underlier-mix-card"')
    expect(cardsDrawerSource).toContain('data-testid="rfr-adoption-card"')
    expect(cardsDrawerSource).toContain('data-testid="swap-spread-vwap-card"')
    expect(cardsDrawerSource).toContain('data-testid="ccp-switch-card"')
  })
})
