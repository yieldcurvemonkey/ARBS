// ABOUTME: Source-string contract test for the volume-grid integration
// in the tape orchestrator. Pins the VolumeGridCard mount, the URL-filter
// click-through callback, and the FilterMatchMode.EQUALS shape for the
// package_id constraint.
import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const tapeSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx',
  ),
  'utf8',
)

describe('UsdSwapsTradeTape — volume grid mount', () => {
  it('imports VolumeGridCard from the local feature module', () => {
    expect(tapeSource).toMatch(
      /import\s+\{\s*VolumeGridCard\s*\}\s+from\s+['"]\.\/VolumeGrid\/VolumeGridCard['"]/,
    )
  })

  it('mounts VolumeGridCard at the top of the tape shell', () => {
    expect(tapeSource).toMatch(
      /<VolumeGridCard\s+onSelectPackage=\{onSelectPackageFromGrid\}\s*\/>/,
    )
  })
})

describe('UsdSwapsTradeTape — onSelectPackageFromGrid wiring', () => {
  it('uses next/navigation router for URL writes', () => {
    expect(tapeSource).toMatch(/from\s+['"]next\/navigation['"]/)
    expect(tapeSource).toMatch(/useRouter|usePathname|useSearchParams/)
  })

  it('writes a package_id constraint via the COLUMN_FILTER_QUERY_KEY', () => {
    expect(tapeSource).toMatch(/COLUMN_FILTER_QUERY_KEY/)
    expect(tapeSource).toMatch(/package_id:\s*\{\s*value:\s*packageId,\s*matchMode:\s*FilterMatchMode\.EQUALS\s*\}/)
  })

  it('uses router.replace with scroll: false to avoid jumping to top', () => {
    expect(tapeSource).toMatch(/router\.replace\(/)
    expect(tapeSource).toMatch(/scroll:\s*false/)
  })
})
