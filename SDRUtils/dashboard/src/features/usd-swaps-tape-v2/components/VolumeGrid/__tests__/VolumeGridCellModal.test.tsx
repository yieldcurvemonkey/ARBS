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
    expect(modalSource).toMatch(/useVolumeGridCell\(\{[\s\S]*forwardSchema:\s*props\.forwardSchema[\s\S]*tenorSchema:\s*props\.tenorSchema[\s\S]*packageType:\s*props\.packageType[\s\S]*\}\)/)
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
  it('shows empty states', () => {
    expect(modalSource).toMatch(/No trades in this bucket over the selected range/)
    expect(modalSource).toMatch(/No recent trades for this bucket/)
  })
})
