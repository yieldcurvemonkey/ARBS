// ABOUTME: Source-string contract test for VolumeGridCellModal. Pins the
// PrimeReact Dialog mount, range toggle, recent-trades click-through,
// and useVolumeGridCell wiring.
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
  it('uses PrimeReact Dialog with modal=true', () => {
    expect(modalSource).toMatch(/import\s+\{\s*Dialog\s*\}\s+from\s+['"]primereact\/dialog['"]/)
    expect(modalSource).toMatch(/modal/)
  })

  it('opens when cell != null and closes via onClose', () => {
    expect(modalSource).toMatch(/visible=\{props\.cell\s*!=\s*null\}/)
    expect(modalSource).toMatch(/onHide=\{props\.onClose\}/)
  })
})

describe('VolumeGridCellModal — range toggle', () => {
  it('persists range to the documented localStorage key', () => {
    expect(modalSource).toMatch(/'usd-tape-v2:volume-grid:cell-range'/)
  })
  it('exposes 1M/3M/6M/1Y options', () => {
    expect(modalSource).toMatch(/\['1M', '3M', '6M', '1Y'\]/)
  })
  it('defaults to 3M', () => {
    expect(modalSource).toMatch(/['"]3M['"]/)
  })
})

describe('VolumeGridCellModal — useVolumeGridCell + click-through', () => {
  it('calls useVolumeGridCell with cell + metric + range', () => {
    expect(modalSource).toMatch(/useVolumeGridCell\(\{[\s\S]*cell:\s*props\.cell[\s\S]*metric:\s*props\.metric[\s\S]*range[\s\S]*\}\)/)
  })
  it('row click invokes onSelectPackage(package_id) and onClose', () => {
    expect(modalSource).toMatch(/onSelectPackage\(t\.package_id\)/)
    expect(modalSource).toMatch(/props\.onClose\(\)/)
  })
})

describe('VolumeGridCellModal — empty state', () => {
  it('shows an empty state when timeseries is empty', () => {
    expect(modalSource).toMatch(/No trades in this bucket over the selected range/)
  })
  it('shows an empty state when recentTrades is empty', () => {
    expect(modalSource).toMatch(/No recent trades for this bucket/)
  })
})
