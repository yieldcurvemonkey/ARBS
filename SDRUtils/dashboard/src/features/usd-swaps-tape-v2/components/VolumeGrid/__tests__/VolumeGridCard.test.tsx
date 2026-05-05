// ABOUTME: Source-string contract test for VolumeGridCard. Pins the
// localStorage keys, enum options, and component wiring.
import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const cardSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx',
  ),
  'utf8',
)

describe('VolumeGridCard — localStorage keys', () => {
  it('uses the documented key for collapsed state', () => {
    expect(cardSource).toMatch(/'usd-tape-v2:volume-grid:collapsed'/)
  })
  it('uses the documented key for metric state', () => {
    expect(cardSource).toMatch(/'usd-tape-v2:volume-grid:metric'/)
  })
  it('uses the documented key for period state', () => {
    expect(cardSource).toMatch(/'usd-tape-v2:volume-grid:period'/)
  })
})

describe('VolumeGridCard — toggles', () => {
  it('exposes Notional and DV01 metric options', () => {
    expect(cardSource).toMatch(/id: 'notional'.*Notional/s)
    expect(cardSource).toMatch(/id: 'dv01'.*DV01/s)
  })
  it('exposes Today/1h/24h/1w period options', () => {
    expect(cardSource).toMatch(/id: 'today'.*Today/s)
    expect(cardSource).toMatch(/id: '1h'/)
    expect(cardSource).toMatch(/id: '24h'/)
    expect(cardSource).toMatch(/id: '1w'/)
  })
})

describe('VolumeGridCard — defaults', () => {
  it('starts collapsed=true', () => {
    expect(cardSource).toMatch(/readBool\(KEY_COLLAPSED, true\)/)
  })
  it('defaults metric to notional', () => {
    expect(cardSource).toMatch(/readEnum<VolumeMetric>\([^)]*'notional'\)/)
  })
  it('defaults period to today', () => {
    expect(cardSource).toMatch(/readEnum<VolumePeriod>\([^)]*'today'\)/)
  })
})

describe('VolumeGridCard — calls useVolumeGrid with collapse-aware polling', () => {
  it('passes collapsed flag to useVolumeGrid', () => {
    expect(cardSource).toMatch(/useVolumeGrid\(\{ metric, period, collapsed \}\)/)
  })
})

describe('VolumeGridCard — refresh button + Toggle volume grid label', () => {
  it('renders an aria-labeled refresh button', () => {
    expect(cardSource).toMatch(/aria-label="Refresh"/)
  })
  it('renders an aria-labeled toggle button', () => {
    expect(cardSource).toMatch(/aria-label="Toggle volume grid"/)
  })
})
