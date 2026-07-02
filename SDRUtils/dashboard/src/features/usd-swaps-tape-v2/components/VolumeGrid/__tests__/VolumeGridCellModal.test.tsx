// ABOUTME: Source-string contract test for VolumeGridCellModal.
import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const modalSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCellModal.tsx',
  ),
  'utf8',
)

describe('VolumeGridCellModal — Dialog wiring', () => {
  it('uses PrimeReact Dialog', () => {
    expect(modalSource).toMatch(/import\s+\{\s*Dialog\s*\}\s+from\s+['"]primereact\/dialog['"]/)
  })
  it('opens when cell != null and closes via onClose', () => {
    expect(modalSource).toMatch(/visible=\{props\.cell\s*!=\s*null\}/)
    expect(modalSource).toMatch(/onHide=\{props\.onClose\}/)
  })
})

describe('VolumeGridCellModal — schemas threaded', () => {
  it('forwards forwardSchema/tenorSchema/packageType to useVolumeGridCell', () => {
    // Props are threaded through cellArgs with null-safe defaults before being
    // passed to useVolumeGridCell(cellArgs). Test each prop key independently.
    expect(modalSource).toMatch(/forwardSchema:\s*props\.forwardSchema/)
    expect(modalSource).toMatch(/tenorSchema:\s*props\.tenorSchema/)
    expect(modalSource).toMatch(/packageType:\s*props\.packageType/)
    expect(modalSource).toMatch(/useVolumeGridCell\(cellArgs\)/)
  })
})

describe('VolumeGridCellModal — range toggle', () => {
  it('persists range to the documented localStorage key', () => {
    expect(modalSource).toMatch(/'usd-tape-v2:volume-grid:cell-range'/)
  })
  it('exposes 1M/3M/6M/1Y options', () => {
    expect(modalSource).toMatch(/\['1M', '3M', '6M', '1Y'\]/)
  })
})

describe('VolumeGridCellModal — click-through + empty states', () => {
  it('row click invokes onSelectPackage(package_id) and onClose', () => {
    expect(modalSource).toMatch(/onSelectPackage\(t\.package_id\)/)
    expect(modalSource).toMatch(/props\.onClose\(\)/)
  })
  // Regression guard: leg sub-rows must NOT have an onClick. Multi-leg
  // packages render as one clickable parent row plus collapsible
  // display-only leg rows, so the dispatched filter always carries the
  // parent package_id — never a leg-specific value.
  it('leg sub-rows are render-only (no onClick handler)', () => {
    // The leg-row <tr> opens with the data-testid attribute and must
    // NOT carry an onClick before the closing >.
    expect(modalSource).toMatch(
      /<tr key=\{`leg-\$\{i\}`\} data-testid="leg-row"[^>]*>/,
    )
    const legTrMatch = modalSource.match(
      /<tr key=\{`leg-\$\{i\}`\} data-testid="leg-row"[^>]*>/,
    )
    expect(legTrMatch).not.toBeNull()
    expect(legTrMatch![0]).not.toMatch(/onClick/)
  })
  // Regression guard: the click handler must dispatch t.package_id
  // (the parent package id), not a leg-scoped id. The expand chevron's
  // onClick uses stopPropagation so it never triggers the row click.
  it('parent row dispatches t.package_id and chevron stops propagation', () => {
    expect(modalSource).toMatch(/onClick=\{\(\) => \{[\s\S]*?onSelectPackage\(t\.package_id\)/)
    expect(modalSource).toMatch(/data-testid="leg-expand"[\s\S]*?e\.stopPropagation\(\)/)
  })
  it('shows empty states', () => {
    expect(modalSource).toMatch(/No trades in this bucket over the selected range/)
    expect(modalSource).toMatch(/No recent trades for this bucket/)
    expect(modalSource).toMatch(/No intraday seasonality for this bucket/)
  })
})

describe('VolumeGridCellModal intraday seasonality', () => {
  it('renders a current-vs-average line chart from intradaySeasonality', () => {
    expect(modalSource).toMatch(/IntradaySeasonalityChart/)
    expect(modalSource).toMatch(/intradaySeasonality/)
    expect(modalSource).toMatch(/dataKey="current"/)
    expect(modalSource).toMatch(/dataKey="average"/)
  })
})

describe('VolumeGridCellModal — leg-annotated recent trades (source contract)', () => {
  const src = readFileSync(
    resolve(
      process.cwd(),
      'src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCellModal.tsx',
    ),
    'utf8',
  )

  it('renders expand chevron for multi-leg trades', () => {
    expect(src).toContain('data-testid="leg-expand"')
  })

  it('renders leg sub-rows with inCell badge', () => {
    expect(src).toContain('data-testid="leg-row"')
    expect(src).toContain('inCell')
  })

  it('renders cell contribution column', () => {
    expect(src).toContain('data-testid="cell-contribution"')
  })

  it('renders per-leg risk/notional breakdown when 2+ legs share the cell', () => {
    expect(src).toContain('data-testid="cell-leg-breakdown"')
    // Breakdown only renders when isMultiLeg && inCellLegs.length > 1
    expect(src).toMatch(/showBreakdown\s*=\s*isMultiLeg\s*&&\s*inCellLegs\.length\s*>\s*1/)
    // Per-leg amount must use metric-appropriate field (risk for dv01, notional otherwise)
    expect(src).toMatch(/props\.metric\s*===\s*'dv01'\s*\?\s*l\.risk\s*:\s*l\.notional/)
  })

  it('renders package type badge', () => {
    expect(src).toContain('data-testid="pkg-type-badge"')
  })

  it('shows "all package types" subtitle when packageType is all', () => {
    expect(src).toContain('Includes all package types')
  })
})
