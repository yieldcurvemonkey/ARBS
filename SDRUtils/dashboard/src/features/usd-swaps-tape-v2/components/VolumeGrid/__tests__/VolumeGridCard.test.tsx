// ABOUTME: Source-string contract test for VolumeGridCard.
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
  it('uses the documented keys for collapsed/metric/period state', () => {
    expect(cardSource).toMatch(/'usd-tape-v2:volume-grid:collapsed'/)
    expect(cardSource).toMatch(/'usd-tape-v2:volume-grid:metric'/)
    expect(cardSource).toMatch(/'usd-tape-v2:volume-grid:period'/)
  })
  it('uses keys for forward + tenor schema and package-type state', () => {
    expect(cardSource).toMatch(/'usd-tape-v2:volume-grid:forward-schema'/)
    expect(cardSource).toMatch(/'usd-tape-v2:volume-grid:tenor-schema'/)
    expect(cardSource).toMatch(/'usd-tape-v2:volume-grid:package-type'/)
  })
})

describe('VolumeGridCard — toggles', () => {
  it('exposes Notional and DV01 metric options', () => {
    expect(cardSource).toMatch(/id: 'notional'[\s\S]*Notional/)
    expect(cardSource).toMatch(/id: 'dv01'[\s\S]*DV01/)
  })
  it('exposes Today/1h/24h/1w period options', () => {
    expect(cardSource).toMatch(/id: 'today'[\s\S]*Today/)
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
  it('defaults forward schema to default', () => {
    expect(cardSource).toMatch(/readEnum<ForwardSchemaId>\([^)]*'default'\)/)
  })
  it('defaults tenor schema to default', () => {
    expect(cardSource).toMatch(/readEnum<TenorSchemaId>\([^)]*'default'\)/)
  })
  it('defaults package-type to outright', () => {
    expect(cardSource).toMatch(/readEnum<PackageTypeGroupId>\([^)]*'outright'\)/)
  })
})

describe('VolumeGridCard — wires schema args into useVolumeGrid', () => {
  it('passes forwardSchema, tenorSchema, packageType to the hook', () => {
    expect(cardSource).toMatch(/useVolumeGrid\(\{[\s\S]*forwardSchema[\s\S]*tenorSchema[\s\S]*packageType[\s\S]*\}\)/)
  })
})

describe('VolumeGridCard — exposes axis dropdowns', () => {
  it('renders a Package type select', () => {
    expect(cardSource).toMatch(/aria-label="Package type"/)
  })
  it('renders a Forward schema select', () => {
    expect(cardSource).toMatch(/aria-label="Forward schema"/)
  })
  it('renders a Tenor schema select', () => {
    expect(cardSource).toMatch(/aria-label="Tenor schema"/)
  })
})

describe('VolumeGridCard — refresh + toggle aria labels', () => {
  it('renders an aria-labeled refresh button', () => {
    expect(cardSource).toMatch(/aria-label="Refresh"/)
  })
  it('renders an aria-labeled toggle button', () => {
    expect(cardSource).toMatch(/aria-label="Toggle volume grid"/)
  })
})
