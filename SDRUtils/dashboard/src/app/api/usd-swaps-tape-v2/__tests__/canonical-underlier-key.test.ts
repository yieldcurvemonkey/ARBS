// ABOUTME: Phase 4 contract test — every analytics-dock route that
// can group by underlier MUST expose the canonical_underlier_key
// column under the `canonical` groupBy key. Read the route source and
// look for the column reference; failing this test means the SDR feed
// name variations (USD-SOFR-COMPOUND vs USD-SOFR-OIS) won't collapse
// into one bucket on the dashboard.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))

const ROUTES = [
  'analytics-timeseries/route.ts',
  'rarity/route.ts',
  'extremes/route.ts',
  'timeseries/route.ts',
]

describe('canonical_underlier_key wiring', () => {
  for (const rel of ROUTES) {
    test(`${rel} references l.canonical_underlier_key under groupBy=canonical`, () => {
      const file = path.resolve(HERE, '..', rel)
      const src = fs.readFileSync(file, 'utf-8')
      expect(src).toMatch(/canonical:\s*['"]l\.canonical_underlier_key['"]/)
    })
  }

  test('rarity route accepts groupBy=canonical (no 400 on whitelist)', () => {
    const file = path.resolve(HERE, '..', 'rarity/route.ts')
    const src = fs.readFileSync(file, 'utf-8')
    expect(src).toMatch(/groupCol[\s\S]*canonical:/m)
  })
})
